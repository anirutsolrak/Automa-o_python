"""POC utilitário: pega a ATA .md mais recente em output/, gera Word e envia por e-mail.

Não chama IA — só usa o conteúdo já gerado. Útil pra testar a etapa final
(Word + e-mail) sem gastar nova chamada de modelo.

Uso:
  python poc_finalize_word_email.py
  python poc_finalize_word_email.py --file output/Alfa_20260520_204650.md
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.email_sender import EmailSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("poc-final")


# Devolve o .md de ATA mais recente gerado na pasta (ou None se não houver).
def _ata_mais_recente(pasta: Path) -> Path | None:
    arquivos = sorted(pasta.glob("Alfa_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return arquivos[0] if arquivos else None


# POC utilitário: pega uma ATA .md já gerada, converte pra Word e (opcional)
# envia por e-mail — pra testar a etapa final sem rodar o pipeline inteiro.
def main() -> int:
    parser = argparse.ArgumentParser(description="Gera Word + e-mail a partir de uma ATA .md já existente.")
    parser.add_argument("--file", help="Caminho do .md (default: mais recente em output/).")
    parser.add_argument("--no-email", action="store_true", help="Só gera Word local, sem enviar e-mail.")
    args = parser.parse_args()

    if args.file:
        caminho = Path(args.file)
    else:
        caminho = _ata_mais_recente(Path("output"))

    if not caminho or not caminho.exists():
        logger.error("Nenhuma ATA encontrada (%s)", caminho)
        return 1

    logger.info("Usando ATA: %s", caminho)
    conteudo = caminho.read_text(encoding="utf-8")
    logger.info("Tamanho: %d chars", len(conteudo))

    sender = EmailSender()
    nome_docx = f"ATA_{caminho.stem}.docx"

    if args.no_email:
        # Gera só o Word local — usa o método interno e copia pra output/
        caminho_word_tmp = sender._gerar_word(conteudo, nome_docx)
        destino = Path("output") / nome_docx
        Path("output").mkdir(exist_ok=True)
        Path(caminho_word_tmp).replace(destino)
        logger.info("Word gerado em: %s", destino)
        return 0

    assunto = f"[ATA POC] Condomínio Alfa - {datetime.now().strftime('%d/%m/%Y')}"
    resultado = sender.enviar(assunto=assunto, conteudo=conteudo, nome_arquivo=nome_docx)
    if resultado["sucesso"]:
        logger.info("E-mail enviado: %s", resultado["mensagem"])
        return 0
    logger.error("Falha no e-mail: %s", resultado["mensagem"])
    return 2


if __name__ == "__main__":
    sys.exit(main())
