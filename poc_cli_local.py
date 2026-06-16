"""POC: roda o pipeline Plaud usando CLI oficial + edital local.

Não toca em VPN nem SMB. Salva ATA em output/, gera Word e envia por e-mail
(se EMAIL_REMETENTE/SENHA/DESTINATARIO estiverem configurados).
Roda contra áudio Alfa 3h (file_id hardcoded) e edital em editais_local/.

Flags:
  --no-email   pula a etapa de envio de e-mail (gera Word só se quiser via
               EmailSender._gerar_word manualmente).
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.plaud_client import PlaudClient, PlaudCLIError
from src.ia_processor import IAProcessor
from src.edital_reader import carregar_edital_da_pasta
from src.email_sender import EmailSender

# Áudio de validação — Alfa 13/05/2026 (3h08m)
ALFA_FILE_ID = "00000000000000000000000000000000"
EDITAIS_LOCAIS = "editais_local"
OUTPUT_DIR = "output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("poc")


# POC local da migração: roda o pipeline (CLI Plaud + edital local) contra um
# áudio fixo, gera a ATA em output/ e imprime métricas. Sem VPN/SMB/e-mail.
def main() -> int:
    logger.info("=== POC CLI Plaud — Alfa 3h ===")

    # 1. Validar config + auth Plaud
    Config.validar_credenciais()
    os.environ.setdefault("PLAUD_IA_MODELO", "o3-mini")  # POC: o3-mini cabe no Tier 1 (200k TPM) e mantém reasoning

    plaud = PlaudClient()
    if not plaud.verify_auth():
        logger.error("Plaud CLI sem auth válida. Rode `plaud login` antes.")
        return 2

    # 2. Carregar edital local
    edital_reader = carregar_edital_da_pasta(EDITAIS_LOCAIS)
    if not edital_reader:
        logger.error("Nenhum edital .docx em %s", EDITAIS_LOCAIS)
        return 3
    edital_texto = edital_reader.obter_texto_formatado()
    logger.info("Edital carregado: %d chars", len(edital_texto))

    # 3. Confirmar disponibilidade do áudio
    meta = plaud.get_file_meta(ALFA_FILE_ID)
    logger.info("Áudio: %s | duração=%s | transcript=%s | summary=%s",
                meta.get("name"), meta.get("duration"),
                meta.get("transcript"), meta.get("summary"))
    if meta.get("transcript") != "available":
        logger.error("Transcript não disponível ainda.")
        return 4

    # 4. Baixar transcript + summary
    t0 = time.monotonic()
    transcript = plaud.get_transcript(ALFA_FILE_ID)
    summary = plaud.get_summary(ALFA_FILE_ID)
    dt_download = time.monotonic() - t0
    logger.info("Transcript: %d chars (%.1f min de fala est.)",
                len(transcript), len(transcript) / 1100)
    logger.info("Summary: %d chars", len(summary))
    logger.info("Download CLI: %.1fs", dt_download)

    # 5. Processar com IA (o3 forçado)
    ia = IAProcessor()
    t1 = time.monotonic()
    resultado = ia.processar(transcript=transcript, summary=summary, edital=edital_texto)
    dt_ia = time.monotonic() - t1

    if not resultado["sucesso"]:
        logger.error("IA falhou: %s", resultado["mensagem"])
        return 5

    ata = resultado["ata"]
    logger.info("ATA gerada: %d chars | modelo=%s | tempo=%.1fs",
                len(ata), resultado["modelo_usado"], dt_ia)

    # 6. Salvar saída em markdown
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_base = f"Alfa_{timestamp}"
    out_md = Path(OUTPUT_DIR) / f"{nome_base}.md"
    out_md.write_text(ata, encoding="utf-8")
    logger.info("ATA salva em: %s", out_md)

    # 7. Gerar Word + enviar email (a menos que --no-email)
    if "--no-email" in sys.argv:
        logger.info("Pulando geração de Word/email (--no-email).")
    else:
        logger.info("Gerando Word e enviando por e-mail...")
        email_sender = EmailSender()
        nome_word = f"ATA_{nome_base}.docx"
        assunto = f"[ATA POC] Condomínio Alfa - {datetime.now().strftime('%d/%m/%Y')}"
        resultado_email = email_sender.enviar(
            assunto=assunto,
            conteudo=ata,
            nome_arquivo=nome_word,
        )
        if resultado_email["sucesso"]:
            logger.info("E-mail enviado: %s", resultado_email["mensagem"])
        else:
            logger.warning("E-mail NÃO enviado: %s", resultado_email["mensagem"])

    logger.info("=== POC concluído com sucesso ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
