"""Pipeline Plaud — versão CLI (Fase 2).

Substitui as etapas Selenium por PlaudClient.
Processa todos os editais pendentes da pasta SMB por execução.
Mantém VPN/SMB/IA/e-mail intactos.

Uso:
    python3 pipeline.py              # execução completa
    python3 pipeline.py --test       # smoke test (sem chamadas a IA)
    python3 pipeline.py --no-email   # gera ATAs mas não envia
    python3 pipeline.py --no-vpn     # pula VPN (uso local apenas)
"""

import argparse
import logging
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

# Garante UTF-8 no stdout (Windows usa cp1252 por default e quebra com emoji/setas no log)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.plaud_client import PlaudClient
from src.ata_matcher import AtaMatcher
from src.ata_verifier import AtaVerifier
from src.processados_tracker import ProcessadosTracker
from src.edital_scanner import EditalScanner
from src.edital_reader import EditalReader, validar_extracao
from src.ia_processor import IAProcessor
from src.email_sender import EmailSender
from src.smb_client import SMBClient, SMBClientError

IS_LINUX = platform.system() == "Linux"
if IS_LINUX:
    from src.vpn_manager import VPNManager


# Busca recursivamente a pasta 'Editais' a partir do caminho base (limitada a
# max_depth). Inlined do pipeline.py legacy pra evitar dependência cross-file.
def encontrar_pasta_editais(caminho_base: str, max_depth: int = 3) -> str | None:
    def _buscar(caminho_atual: str, depth: int = 0) -> str | None:
        if depth > max_depth:
            return None
        try:
            itens = os.listdir(caminho_atual)
            for item in itens:
                caminho_item = os.path.join(caminho_atual, item)
                if os.path.isdir(caminho_item) and item.lower() == "editais":
                    return caminho_item
            for item in itens:
                caminho_item = os.path.join(caminho_atual, item)
                if os.path.isdir(caminho_item) and not item.startswith(".") and not item.startswith("$"):
                    resultado = _buscar(caminho_item, depth + 1)
                    if resultado:
                        return resultado
            return None
        except (PermissionError, OSError):
            return None
    return _buscar(caminho_base)

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# Monta o HTML opcional do e-mail com os alertas de extração (validador) e de
# omissões (verifier). Retorna "" quando não há nada a alertar.
def _montar_corpo_extra(validacao: dict, omissoes: dict) -> str:
    blocos = []
    if not validacao.get("ok", True):
        itens = "".join(f"<li>{a}</li>" for a in validacao.get("alertas", []))
        blocos.append(
            f'<div style="border-left:4px solid #d97706;background:#fef3c7;padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Alerta de extração do edital</b><ul>{itens}</ul></div>'
        )
    if omissoes.get("tem_omissoes"):
        rel = omissoes["relatorio"].replace("\n", "<br>")
        blocos.append(
            f'<div style="border-left:4px solid #dc2626;background:#fee2e2;padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Possíveis omissões detectadas</b>'
            f'<p style="font-family:monospace;font-size:0.9em;white-space:pre-wrap">{rel}</p></div>'
        )
    return "".join(blocos)


def _processar_um(edital_path: str, audio: dict, plaud: PlaudClient,
                  ia: IAProcessor, verifier: AtaVerifier,
                  email_sender: EmailSender, tracker: ProcessadosTracker,
                  enviar_email: bool,
                  smb_client: Optional["SMBClient"] = None,
                  pasta_remota_atas: Optional[str] = None) -> dict:
    # Processa um par (edital, áudio) fim a fim: lê o edital, gera a ATA com a
    # IA, valida/verifica, gera o Word, envia e-mail e (se smb_client +
    # pasta_remota_atas) sobe a ATA pro SMB. Retorna o dict de resultado.
    res = {"edital": os.path.basename(edital_path), "audio": audio.get("name"), "ok": False, "erro": None}

    # Carrega edital
    reader = EditalReader(caminho_arquivo=edital_path)
    r = reader.carregar()
    if not r["sucesso"]:
        raise RuntimeError(f"falha ao carregar edital: {r['mensagem']}")
    reader.extrair_pontos()
    validacao = validar_extracao(reader)
    edital_texto = reader.obter_texto_formatado()

    # Disponibilidade do áudio
    meta = plaud.get_file_meta(audio["id"])
    if meta.get("transcript") != "available":
        raise RuntimeError(f"transcript não disponível ainda ({meta.get('transcript')})")

    # Download
    transcript = plaud.get_transcript(audio["id"])
    if not transcript or len(transcript.strip()) < 50:
        raise RuntimeError(
            f"transcript disponível nos metadados mas conteúdo vazio/insuficiente "
            f"({len(transcript.strip()) if transcript else 0} chars) para áudio {audio['id']}. "
            f"O Plaud pode ainda estar processando o áudio."
        )
    logger.info("[OK] Transcript: %d chars", len(transcript))
    summary = plaud.get_summary(audio["id"]) if meta.get("summary") == "available" else ""

    # IA
    resultado = ia.processar(transcript=transcript, summary=summary, edital=edital_texto)
    if not resultado["sucesso"]:
        raise RuntimeError(f"IA falhou: {resultado['mensagem']}")
    ata = resultado["ata"]

    # Verificação de omissões
    omissoes = verifier.verificar(ata=ata, transcript=transcript)

    # Salva .md em saida/
    saida_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "saida"
    saida_dir.mkdir(exist_ok=True)
    nome_condo = os.path.splitext(os.path.basename(edital_path))[0]
    nome_condo_safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in nome_condo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = saida_dir / f"{nome_condo_safe}_{timestamp}.md"
    out_md.write_text(ata, encoding="utf-8")
    logger.info("[OK] ATA .md salva em %s", out_md)

    # Word: sempre gera local em saida/ (pra anexar email + subir SMB)
    nome_docx = f"ATA_{nome_condo_safe}_{timestamp}.docx"
    ata_docx_path = saida_dir / nome_docx
    tmp_docx = email_sender._gerar_word(ata, nome_docx)
    Path(tmp_docx).replace(ata_docx_path)
    logger.info("[OK] Word local: %s", ata_docx_path)

    # E-mail
    corpo_extra = _montar_corpo_extra(validacao, omissoes)
    email_marcado = False
    if enviar_email:
        assunto = f"[ATA] {nome_condo} - {datetime.now().strftime('%d/%m/%Y')}"
        if not validacao.get("ok", True):
            assunto = "⚠️ " + assunto + " (edital fora do padrão)"
        if omissoes.get("tem_omissoes"):
            assunto = "⚠️ " + assunto + " (possíveis omissões)"
        r_email = email_sender.enviar(assunto=assunto, conteudo=ata, nome_arquivo=nome_docx, corpo_extra=corpo_extra)
        if r_email["sucesso"]:
            logger.info("[OK] E-mail enviado: %s", r_email["mensagem"])
        else:
            logger.warning("[AVISO] E-mail falhou (mas ATA já existe em disco): %s", r_email["mensagem"])
    email_marcado = True  # ATA já existe localmente → marca

    # Upload SMB pra pasta Atas concluídas (best-effort, não bloqueia o marcar)
    if smb_client and pasta_remota_atas:
        remote = f"{pasta_remota_atas}/{nome_docx}"
        try:
            smb_client.subir(str(ata_docx_path), remote)
            logger.info("[OK] ATA subida pro SMB: %s", remote)
        except Exception as e:
            logger.warning("[AVISO] Falha ao subir ATA pro SMB (%s): %s", remote, e)

    # Marca como processado
    if email_marcado:
        tracker.marcar_processado(edital_path, audio["id"], str(out_md))

    res.update({"ok": True, "ata_chars": len(ata), "audio_id": audio["id"],
                "validacao_ok": validacao.get("ok"), "tem_omissoes": omissoes.get("tem_omissoes")})
    return res


# Orquestra a execução completa em etapas: valida auth Plaud → VPN → SMB →
# lista editais pendentes → casa cada um com seu áudio → gera/entrega a ATA.
# Retorna o código de saída do processo (0 ok, 2 auth, 3 VPN, 4 SMB).
def executar_pipeline(usar_vpn: bool = True, enviar_email: bool = True,
                       max_editais: int = None, modo_teste: bool = False) -> int:
    vpn_manager = None
    relatorio = {"sucessos": [], "falhas": [], "ignorados": []}

    try:
        logger.info("=" * 70)
        logger.info("PIPELINE PLAUD CLI - Fase 2")
        logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        logger.info("=" * 70)

        # ETAPA 0
        logger.info("\n[ETAPA 0] Validando credenciais e auth Plaud...")
        Config.validar_credenciais()
        plaud = PlaudClient()
        if not plaud.verify_auth():
            logger.error("[CRÍTICO] Plaud CLI sem auth válida. Rode `plaud login` na VPS.")
            _alertar_reauth()
            return 2

        if modo_teste:
            logger.info("[TESTE] Smoke test passou. Saindo.")
            return 0

        # ETAPA 1 — VPN
        if IS_LINUX and usar_vpn:
            logger.info("\n[ETAPA 1] Conectando VPN...")
            vpn_manager = VPNManager()
            r = vpn_manager.conectar(timeout=60)
            if not r["sucesso"]:
                logger.error("[ERRO] VPN: %s", r["mensagem"])
                return 3
        else:
            logger.info("\n[ETAPA 1] VPN: ignorada")

        # ETAPA 2 — SMB via smbclient (igual ao legacy; mount.cifs falha em alguns servidores)
        caminho_editais = None
        smb_client: Optional[SMBClient] = None
        ano_atual = datetime.now().year
        pasta_remota_editais = f"Automacao/Editais/{ano_atual}"
        pasta_remota_atas = f"Automacao/Atas (concluidas pela automacao)/{ano_atual}"
        if IS_LINUX:
            logger.info("\n[ETAPA 2] Conectando SMB via smbclient...")
            smb_client = SMBClient(
                servidor="10.0.0.10",
                share="Arquivos",
                usuario=os.environ.get("SMB_USUARIO", "svc_automacao"),
                senha=os.environ.get("SMB_SENHA", "<SENHA_SMB>"),
            )
            if not smb_client.conectividade_ok():
                logger.error("[ERRO] SMB: smbclient não conseguiu listar share")
                return 4
            logger.info("[OK] SMB conectado")

            # Baixa todos editais remotos pra /tmp/plaud_editais/ pra processar
            caminho_editais = "/tmp/plaud_editais"
            # Limpa baixa anterior pra refletir estado atual do remoto
            if os.path.isdir(caminho_editais):
                import shutil as _sh
                _sh.rmtree(caminho_editais, ignore_errors=True)
            os.makedirs(caminho_editais, exist_ok=True)
            try:
                remotos = smb_client.listar(pasta_remota_editais)
            except SMBClientError as e:
                logger.error("[ERRO] SMB: falha ao listar %s: %s", pasta_remota_editais, e)
                return 5
            n_baixados = 0
            for arq in remotos:
                nome = arq["name"]
                if not nome.lower().endswith(".docx"):
                    continue
                if nome.startswith("~$") or nome.startswith("."):
                    continue
                remote_path = f"{pasta_remota_editais}/{nome}"
                local_path = os.path.join(caminho_editais, nome)
                try:
                    smb_client.baixar(remote_path, local_path)
                    # Preserva mtime do remoto pra ordenação por idade no scanner
                    ts = arq["mtime"].timestamp()
                    os.utime(local_path, (ts, ts))
                    n_baixados += 1
                except SMBClientError as e:
                    logger.warning("[SMB] falha ao baixar %s: %s", nome, e)
            logger.info("[OK] %d edital(is) baixado(s) de %s", n_baixados, pasta_remota_editais)
        else:
            # Modo dev/local
            caminho_editais = os.environ.get("CAMINHO_EDITAIS_LOCAL", "./editais_local")

        # ETAPA 3 — Pendentes
        logger.info("\n[ETAPA 3] Listando editais pendentes em %s ...", caminho_editais)
        tracker_path = os.environ.get("PROCESSADOS_JSON_PATH", "/opt/plaud/processados.json")
        if not IS_LINUX:
            tracker_path = os.environ.get("PROCESSADOS_JSON_PATH", "./processados.json")
        tracker = ProcessadosTracker(caminho=tracker_path)
        scanner = EditalScanner(caminho_editais, tracker)
        limite = max_editais or int(os.environ.get("MAX_EDITAIS_POR_RUN", "10"))
        pendentes = scanner.listar_pendentes(limite=limite)
        logger.info("[OK] %d edital(is) pendente(s)", len(pendentes))
        if not pendentes:
            logger.info("Nada a processar.")
            return 0

        # ETAPA 4 — Áudios candidatos
        logger.info("\n[ETAPA 4] Listando áudios Plaud (últimos 14 dias)...")
        hoje = datetime.now().date()
        candidatos = plaud.list_by_date_range(
            date_from=(hoje - timedelta(days=14)).strftime("%Y-%m-%d"),
            date_to=(hoje + timedelta(days=1)).strftime("%Y-%m-%d"),
            page_size=100,
        )
        logger.info("[OK] %d áudio(s) candidato(s)", len(candidatos))

        # ETAPA 5 — Loop de processamento
        logger.info("\n[ETAPA 5] Processando %d edital(is)...", len(pendentes))
        matcher = AtaMatcher(plaud)
        ia = IAProcessor()
        verifier = AtaVerifier()
        email_sender = EmailSender()

        for edital_path in pendentes:
            nome_curto = os.path.basename(edital_path)
            logger.info("\n----- %s -----", nome_curto)
            try:
                audio = matcher.match(edital_path, candidatos)
                if not audio:
                    logger.warning("[SKIP] sem áudio correspondente")
                    relatorio["ignorados"].append({"edital": nome_curto, "motivo": "sem audio"})
                    continue
                resultado = _processar_um(edital_path, audio, plaud, ia, verifier,
                                          email_sender, tracker, enviar_email,
                                          smb_client=smb_client,
                                          pasta_remota_atas=pasta_remota_atas)
                matcher.marcar_par_usado(audio["id"])
                relatorio["sucessos"].append(resultado)
            except Exception as e:
                logger.error("[FALHA] %s: %s", nome_curto, e)
                logger.debug(traceback.format_exc())
                relatorio["falhas"].append({"edital": nome_curto, "erro": str(e)})

        # Relatório final
        logger.info("\n" + "=" * 70)
        logger.info("RESUMO: %d sucesso(s), %d falha(s), %d ignorado(s)",
                    len(relatorio["sucessos"]), len(relatorio["falhas"]), len(relatorio["ignorados"]))

        if relatorio["falhas"]:
            _email_resumo_falhas(relatorio, email_sender)

        return 0 if not relatorio["falhas"] else 1

    finally:
        if IS_LINUX:
            if vpn_manager:
                try: vpn_manager.desconectar()
                except Exception: pass


# Dispara o e-mail de alerta quando a auth do Plaud expirou (precisa de
# `plaud login` manual na VPS). Best-effort: não derruba o pipeline se falhar.
def _alertar_reauth():
    try:
        EmailSender().enviar(
            assunto="[REAUTH NECESSÁRIO] Plaud CLI",
            conteudo="Token expirado. SSH na VPS + `plaud login`.",
            nome_arquivo="reauth.docx",
        )
    except Exception as e:
        logger.warning("Falha ao enviar e-mail de reauth: %s", e)


# Envia o e-mail-resumo da execução: sucessos, falhas e ignorados (editais
# pulados por ambiguidade de matching, com o motivo). Best-effort.
def _email_resumo_falhas(relatorio: dict, email_sender: EmailSender):
    linhas = ["# Relatório de execução\n"]
    for s in relatorio["sucessos"]:
        linhas.append(f"✓ {s['edital']} → {s.get('audio_id')}")
    for f in relatorio["falhas"]:
        linhas.append(f"✗ {f['edital']}: {f['erro']}")
    for i in relatorio["ignorados"]:
        linhas.append(f"- {i['edital']}: {i['motivo']}")
    try:
        email_sender.enviar(
            assunto=f"[RESUMO PIPELINE] {datetime.now().strftime('%d/%m/%Y')} - {len(relatorio['falhas'])} falha(s)",
            conteudo="\n\n".join(linhas),
            nome_arquivo="resumo.docx",
        )
    except Exception as e:
        logger.warning("Falha ao enviar resumo: %s", e)


# Ponto de entrada CLI: parseia as flags (--no-vpn/--no-email/--test/--max) e
# chama executar_pipeline, propagando o código de saída pro shell/cron.
def main():
    parser = argparse.ArgumentParser(description="Pipeline Plaud CLI (Fase 2)")
    parser.add_argument("--no-vpn", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--test", action="store_true", help="Smoke test (sem chamadas IA)")
    parser.add_argument("--max", type=int, default=None, help="Máximo de editais por execução")
    args = parser.parse_args()

    sys.exit(executar_pipeline(
        usar_vpn=not args.no_vpn,
        enviar_email=not args.no_email,
        max_editais=args.max,
        modo_teste=args.test,
    ))


if __name__ == "__main__":
    main()
