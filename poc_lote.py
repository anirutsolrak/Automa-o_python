"""POC em lote: processa 3 áudios (Theta, Gama, Delta).

Para cada job (edital, audio Plaud), baixa transcript/summary, gera ATA com IA,
salva .md, gera Word e envia por e-mail. Imprime métricas e custo estimado.

Uso:
  python poc_lote.py            # processa os 3 e envia 3 e-mails
  python poc_lote.py --no-email # gera .md e .docx local, sem envio
"""

import argparse
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)  # busca .env subindo dirs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.plaud_client import PlaudClient, PlaudCLIError
from src.ia_processor import IAProcessor
from src.edital_reader import EditalReader, validar_extracao
from src.email_sender import EmailSender
from src.ata_verifier import AtaVerifier


EDITAIS_DIR = Path("editais_local/lote_cliente")
OUTPUT_DIR = Path("output/lote_cliente")


# Um item do lote: nome amigável, arquivo do edital e id do áudio no Plaud.
@dataclass
class Job:
    nome: str
    edital_filename: str
    plaud_file_id: str


JOBS = [
    Job("Theta",   "17.03.2026 Theta.docx",        "00000000000000000000000000000000"),
    Job("Gama",        "08.04.2026 Gama.docx",             "00000000000000000000000000000000"),
    Job("Delta",      "29.04.2026 Delta.docx",           "00000000000000000000000000000000"),
    Job("Iota",    "20.05.2026 Iota.docx", "00000000000000000000000000000000"),
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("lote")


# Carrega um edital e devolve (texto_formatado_pro_prompt, validacao). A
# validação sinaliza editais fora do padrão.
def _carregar_edital(path: Path) -> tuple[str, dict]:
    reader = EditalReader(caminho_arquivo=str(path))
    r = reader.carregar()
    if not r["sucesso"]:
        raise RuntimeError(f"Falha ao carregar edital {path}: {r['mensagem']}")
    reader.extrair_pontos()
    validacao = validar_extracao(reader)
    return reader.obter_texto_formatado(), validacao


# Renderiza o HTML com os alertas do validador e do verificador, se houver.
def _montar_corpo_extra(validacao: dict, omissoes: dict) -> str:
    blocos = []
    if not validacao["ok"]:
        itens = "".join(f"<li>{a}</li>" for a in validacao["alertas"])
        blocos.append(
            f'<div style="border-left:4px solid #d97706;background:#fef3c7;'
            f'padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Alerta de extração do edital</b>'
            f'<ul>{itens}</ul>'
            f'</div>'
        )
    if omissoes.get("tem_omissoes"):
        relatorio = omissoes["relatorio"].replace("\n", "<br>")
        blocos.append(
            f'<div style="border-left:4px solid #dc2626;background:#fee2e2;'
            f'padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Possíveis omissões detectadas pelo verificador</b>'
            f'<p style="font-family:monospace;font-size:0.9em;white-space:pre-wrap">{relatorio}</p>'
            f'<p style="font-size:0.85em;color:#666">Modelo do verificador: {omissoes.get("modelo")}</p>'
            f'</div>'
        )
    return "".join(blocos)


# Processa um Job do lote (edital + áudio): gera a ATA, verifica e entrega.
def _processar_um(job: Job, plaud: PlaudClient, ia: IAProcessor,
                  verifier: AtaVerifier,
                  email_sender: EmailSender, enviar_email: bool) -> dict:
    res = {"nome": job.nome, "ok": False, "erro": None}

    logger.info("===== %s =====", job.nome)

    # 1. Edital + validação de extração
    edital_path = EDITAIS_DIR / job.edital_filename
    if not edital_path.exists():
        raise FileNotFoundError(edital_path)
    edital_texto, validacao = _carregar_edital(edital_path)
    logger.info("Edital: %d chars | validacao_ok=%s | itens=%d",
                len(edital_texto), validacao["ok"], validacao["num_itens"])
    for alerta in validacao["alertas"]:
        logger.warning("  [EDITAL ALERTA] %s", alerta)

    # 2. Verificar disponibilidade
    meta = plaud.get_file_meta(job.plaud_file_id)
    logger.info("Áudio: %s | %s | transcript=%s | summary=%s",
                meta.get("name"), meta.get("duration"),
                meta.get("transcript"), meta.get("summary"))
    if meta.get("transcript") != "available":
        raise RuntimeError("transcript não disponível")

    # 3. Download
    t0 = time.monotonic()
    transcript = plaud.get_transcript(job.plaud_file_id)
    summary = plaud.get_summary(job.plaud_file_id) if meta.get("summary") == "available" else ""
    dt_dl = time.monotonic() - t0
    logger.info("Transcript: %d chars (~%d min) | Summary: %d chars | dl=%.1fs",
                len(transcript), len(transcript) // 1100, len(summary), dt_dl)

    # 4. IA
    t1 = time.monotonic()
    resultado = ia.processar(transcript=transcript, summary=summary, edital=edital_texto)
    dt_ia = time.monotonic() - t1
    if not resultado["sucesso"]:
        raise RuntimeError(f"IA falhou: {resultado['mensagem']}")
    ata = resultado["ata"]
    logger.info("ATA gerada: %d chars | modelo=%s | ia=%.1fs",
                len(ata), resultado["modelo_usado"], dt_ia)

    # 5. Verificador de omissões (não bloqueia)
    t_v = time.monotonic()
    omissoes = verifier.verificar(ata=ata, transcript=transcript)
    dt_verifier = time.monotonic() - t_v
    logger.info("Verificador: tem_omissoes=%s | modelo=%s | %.1fs",
                omissoes.get("tem_omissoes"), omissoes.get("modelo"), dt_verifier)
    if omissoes.get("tem_omissoes"):
        logger.warning("  [OMISSÕES]\n%s", omissoes["relatorio"])

    # 6. Salvar md
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = job.nome.replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = OUTPUT_DIR / f"{stem}_{timestamp}.md"
    out_md.write_text(ata, encoding="utf-8")
    logger.info("ATA .md: %s", out_md)

    # 7. Word + e-mail (com alertas embutidos no corpo)
    nome_docx = f"ATA_{stem}_{timestamp}.docx"
    corpo_extra = _montar_corpo_extra(validacao, omissoes)
    if enviar_email:
        assunto = f"[ATA POC Lote] {job.nome} - {datetime.now().strftime('%d/%m/%Y')}"
        if not validacao["ok"]:
            assunto = "⚠️ " + assunto + " (edital fora do padrão)"
        if omissoes.get("tem_omissoes"):
            assunto = "⚠️ " + assunto + " (possíveis omissões)"
        r_email = email_sender.enviar(assunto=assunto, conteudo=ata,
                                       nome_arquivo=nome_docx, corpo_extra=corpo_extra)
        if r_email["sucesso"]:
            logger.info("E-mail OK: %s", r_email["mensagem"])
        else:
            logger.warning("E-mail FALHOU: %s", r_email["mensagem"])
    else:
        tmp = email_sender._gerar_word(ata, nome_docx)
        destino = OUTPUT_DIR / nome_docx
        Path(tmp).replace(destino)
        logger.info("Word local: %s", destino)

    res.update({
        "ok": True,
        "ata_chars": len(ata),
        "transcript_chars": len(transcript),
        "summary_chars": len(summary),
        "tempo_ia": round(dt_ia, 1),
        "tempo_verifier": round(dt_verifier, 1),
        "modelo": resultado["modelo_usado"],
        "audio_nome": meta.get("name"),
        "audio_duracao": meta.get("duration"),
        "edital_ok": validacao["ok"],
        "edital_alertas": validacao["alertas"],
        "tem_omissoes": omissoes.get("tem_omissoes", False),
    })
    return res


# POC em lote: roda vários Jobs (edital+áudio) de uma vez via CLI Plaud, pra
# validar a migração em volume antes de virar produção.
def main() -> int:
    parser = argparse.ArgumentParser(description="Processa lote de 3 áudios via CLI Plaud.")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument(
        "--jobs",
        help="Lista CSV de nomes pra filtrar (default: todos). Ex: 'Theta,Delta'",
    )
    args = parser.parse_args()

    jobs_to_run = JOBS
    if args.jobs:
        nomes_filtro = {n.strip().lower() for n in args.jobs.split(",")}
        jobs_to_run = [j for j in JOBS if j.nome.lower() in nomes_filtro]
        if not jobs_to_run:
            logger.error("Nenhum job casou com filtro '%s'. Disponíveis: %s",
                         args.jobs, [j.nome for j in JOBS])
            return 1
        logger.info("Filtro aplicado: rodando %d de %d jobs", len(jobs_to_run), len(JOBS))

    logger.info("=== POC LOTE — 3 áudios ===")
    Config.validar_credenciais()
    os.environ.setdefault("PLAUD_IA_MODELO", "o3-mini")

    plaud = PlaudClient()
    if not plaud.verify_auth():
        logger.error("Plaud CLI sem auth. Rode `plaud login`.")
        return 2

    ia = IAProcessor()
    verifier = AtaVerifier()
    email_sender = EmailSender()
    enviar = not args.no_email

    resultados = []
    t_total = time.monotonic()
    for job in jobs_to_run:
        try:
            r = _processar_um(job, plaud, ia, verifier, email_sender, enviar)
            resultados.append(r)
        except Exception as e:
            logger.error("FALHA em %s: %s", job.nome, e)
            logger.debug(traceback.format_exc())
            resultados.append({"nome": job.nome, "ok": False, "erro": str(e)})

    dt_total = time.monotonic() - t_total
    logger.info("=" * 60)
    logger.info("RESUMO FINAL — %.1fs", dt_total)
    for r in resultados:
        if r["ok"]:
            logger.info("  ✓ %s: ATA %d chars | %s | %ss",
                        r["nome"], r["ata_chars"], r["modelo"], r["tempo_ia"])
        else:
            logger.error("  ✗ %s: %s", r["nome"], r.get("erro"))

    sucessos = sum(1 for r in resultados if r["ok"])
    logger.info("Total: %d/%d sucesso", sucessos, len(jobs_to_run))
    return 0 if sucessos == len(jobs_to_run) else 1


if __name__ == "__main__":
    sys.exit(main())
