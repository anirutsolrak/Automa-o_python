#!/usr/bin/env python3
"""
Teste rápido de envio de email.
Envia um email simples para verificar se a configuração SMTP está ok.

Uso:
    python3 diagnostico_email.py                          # envia para EMAIL_DESTINATARIO do .env
    python3 diagnostico_email.py --para seu@email.com     # envia para email específico
"""

import argparse
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(override=True)


# Envia um e-mail de teste isolado pra validar a config SMTP do .env
# (remetente, senha de app, destinatário) sem tocar em Plaud/SMB/IA.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--para", metavar="EMAIL",
                        help="Email de destino (padrão: EMAIL_DESTINATARIO do .env)")
    args = parser.parse_args()

    remetente = os.environ.get("EMAIL_REMETENTE")
    senha = os.environ.get("EMAIL_SENHA")
    destinatario = args.para or os.environ.get("EMAIL_DESTINATARIO")

    print("=" * 50)
    print("TESTE DE EMAIL")
    print("=" * 50)
    print(f"  Remetente:    {remetente}")
    print(f"  Destinatário: {destinatario}")
    print(f"  SMTP:         smtp.gmail.com:465")

    if not all([remetente, senha, destinatario]):
        print("\n[ERRO] Variáveis faltando no .env:")
        if not remetente: print("  - EMAIL_REMETENTE")
        if not senha:     print("  - EMAIL_SENHA")
        if not destinatario: print("  - EMAIL_DESTINATARIO (ou use --para)")
        sys.exit(1)

    print("\nEnviando...")

    msg = MIMEMultipart()
    msg["Subject"] = f"[TESTE] Automação Plaud — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    msg["From"] = remetente
    msg["To"] = destinatario

    corpo = f"""
    <html><body>
    <h2>✅ Teste de email da automação Plaud</h2>
    <p>Este email foi enviado às <b>{datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}</b>
    para confirmar que o envio de ATAs está funcionando.</p>
    <ul>
      <li><b>Remetente:</b> {remetente}</li>
      <li><b>Destinatário:</b> {destinatario}</li>
    </ul>
    <p><small>Sistema automático Plaud VPS</small></p>
    </body></html>
    """
    msg.attach(MIMEText(corpo, "html", _charset="utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(remetente, senha)
            server.send_message(msg)
        print(f"\n[OK] Email enviado com sucesso para {destinatario}")
    except smtplib.SMTPAuthenticationError:
        print("\n[ERRO] Autenticação falhou — verifique EMAIL_REMETENTE e EMAIL_SENHA no .env")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERRO] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
