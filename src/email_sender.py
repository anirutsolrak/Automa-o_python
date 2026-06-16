"""
Envio de atas geradas por email com anexo Word.
"""

import logging
import smtplib
import os
import tempfile
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from src.config import Config

logger = logging.getLogger(__name__)


# Envia a ATA gerada por e-mail, com o documento Word em anexo.
class EmailSender:

    # Lê as credenciais SMTP do .env (via Config) e marca como `configurado`
    # só quando remetente, senha e destinatário estão todos presentes.
    def __init__(self):
        self.remetente = Config.EMAIL_REMETENTE
        self.senha = Config.EMAIL_SENHA
        self.destinatario = Config.EMAIL_DESTINATARIO
        
        self.configurado = bool(self.remetente and self.senha and self.destinatario)
        
        if self.configurado:
            logger.info(f"[OK] Email configurado: {self.remetente}")
        else:
            logger.warning("[AVISO] Email não está completamente configurado")
            if not self.remetente:
                logger.warning("  - EMAIL_REMETENTE faltando")
            if not self.senha:
                logger.warning("  - EMAIL_SENHA faltando")
            if not self.destinatario:
                logger.warning("  - EMAIL_DESTINATARIO faltando")
    
    # Gera o .docx da ATA a partir de `conteudo` e envia por e-mail com ele
    # anexado. `corpo_extra` é HTML injetado entre cabeçalho e rodapé (alertas
    # do validador/verificador). Retorna {sucesso, mensagem}; nunca levanta.
    def enviar(self, assunto, conteudo, nome_arquivo=None, corpo_extra: str = ""):
        if not self.configurado:
            logger.error("Email não está configurado")
            return {
                "sucesso": False,
                "mensagem": "Email não está configurado (EMAIL_REMETENTE, EMAIL_SENHA ou EMAIL_DESTINATARIO faltando)"
            }
        
        try:
            logger.info(f"Preparando email para: {self.destinatario}")
            
            # Gerar arquivo Word
            nome_word = nome_arquivo or f"ATA_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
            caminho_word = self._gerar_word(conteudo, nome_word)
            logger.info(f"Arquivo Word gerado: {nome_word}")
            
            # Criar mensagem
            msg = MIMEMultipart()
            msg["Subject"] = assunto
            msg["From"] = self.remetente
            msg["To"] = self.destinatario
            
            # Corpo do email — corpo_extra é injetado entre o cabeçalho e o rodapé
            html = f"""
            <html>
                <head>
                    <meta charset="utf-8">
                </head>
                <body>
                    <h2>ATA DE REUNIÃO</h2>
                    <p>Olá,</p>
                    <p>Segue em anexo a ATA da reunião gerada automaticamente.</p>
                    <p><b>Arquivo:</b> {nome_word}</p>
                    {corpo_extra}
                    <hr>
                    <p><small>
                        Gerado automaticamente pelo sistema Plaud.
                        <br>Data: {self._get_data_hora()}
                    </small></p>
                </body>
            </html>
            """
            
            parte_html = MIMEText(html, "html", _charset="utf-8")
            msg.attach(parte_html)
            
            # Anexar arquivo Word
            with open(caminho_word, "rb") as arquivo:
                parte_anexo = MIMEBase("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")
                parte_anexo.set_payload(arquivo.read())
                encoders.encode_base64(parte_anexo)
                parte_anexo.add_header(
                    "Content-Disposition",
                    f"attachment; filename={nome_word}"
                )
                msg.attach(parte_anexo)
            
            # Conectar e enviar
            logger.info("Conectando ao servidor SMTP (Gmail)...")
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self.remetente, self.senha)
                logger.info("Autenticado com sucesso")
                
                server.send_message(msg)
                logger.info(f"[OK] Email enviado com sucesso para {self.destinatario}")
            
            # Limpar arquivo temporário
            if os.path.exists(caminho_word):
                os.remove(caminho_word)
            
            return {
                "sucesso": True,
                "mensagem": f"Email enviado com sucesso para {self.destinatario}"
            }
        
        except smtplib.SMTPAuthenticationError:
            logger.error("Erro de autenticação: Email/Senha incorretos")
            return {
                "sucesso": False,
                "mensagem": "Erro de autenticação: Verifique EMAIL_REMETENTE e EMAIL_SENHA"
            }
        
        except smtplib.SMTPException as e:
            logger.error(f"Erro SMTP: {e}")
            return {
                "sucesso": False,
                "mensagem": f"Erro ao enviar email: {str(e)}"
            }
        
        except Exception as e:
            logger.error(f"Erro ao enviar email: {e}")
            return {
                "sucesso": False,
                "mensagem": f"Erro: {str(e)}"
            }
    
    # Data e hora atual formatadas pro rodapé do e-mail.
    @staticmethod
    def _get_data_hora():
        return datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

    # Converte o texto da ATA num .docx formatado (título centralizado, itens
    # justificados, **negrito** inline) e devolve o caminho do arquivo temp.
    # Replica a mesma lógica de renderização do script principal.
    def _gerar_word(self, conteudo, nome_arquivo):
        import re as _re
        from docx.shared import RGBColor

        doc = Document()
        for section in doc.sections:
            section.top_margin    = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin   = Inches(1.2)
            section.right_margin  = Inches(1.2)

        PRETO = RGBColor(0, 0, 0)

        def _run(para, texto, bold=False, tamanho=12):
            run = para.add_run(texto)
            run.font.size      = Pt(tamanho)
            run.font.bold      = bold
            run.font.color.rgb = PRETO
            return run

        def _renderizar_negrito(para, texto, tamanho=12):
            for i, parte in enumerate(texto.split("**")):
                if parte:
                    _run(para, parte, bold=(i % 2 == 1), tamanho=tamanho)

        # Juntar blocos **negrito** quebrados em múltiplas linhas
        blocos = []; buffer = ""
        for linha_raw in conteudo.split("\n"):
            linha = linha_raw.strip()
            if not linha:
                if buffer: blocos.append(buffer); buffer = ""
                blocos.append(""); continue
            if buffer:
                buffer += " " + linha
                if buffer.count("**") % 2 == 0: blocos.append(buffer); buffer = ""
            else:
                if linha.startswith("**") and linha.count("**") % 2 != 0: buffer = linha
                else: blocos.append(linha)
        if buffer: blocos.append(buffer)

        # Filtrar metadados
        blocos_ok = []
        for b in blocos:
            if b.strip().upper() in ("ATA DE REUNIÃO", "ATA DE ASSEMBLEIA"): continue
            if b.startswith("Gerado em:"): continue
            if b.startswith("Documento gerado automaticamente"): continue
            blocos_ok.append(b)

        # Renderizar
        for bloco in blocos_ok:
            bloco = bloco.strip()
            if not bloco: continue
            if bloco.startswith('"') and bloco.endswith('"'): bloco = bloco[1:-1].strip()

            texto_limpo = bloco.replace("**", "").strip()
            tem_negrito = "**" in bloco
            e_titulo = (len(texto_limpo) > 30 and "ASSEMBLEIA" in texto_limpo.upper()
                        and texto_limpo.upper() == texto_limpo)
            e_item   = bool(_re.search(r"\bITEM\s+\d+", texto_limpo.upper()))

            if e_titulo:
                para = doc.add_paragraph()
                _run(para, texto_limpo.upper(), bold=True, tamanho=14)
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            elif e_item:
                para = doc.add_paragraph()
                if tem_negrito: _renderizar_negrito(para, bloco)
                else:
                    partes = bloco.split(":", 2)
                    if len(partes) >= 3:
                        _run(para, partes[0] + ":" + partes[1] + ":", bold=True)
                        _run(para, partes[2], bold=False)
                    else: _run(para, bloco, bold=False)
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            else:
                para = doc.add_paragraph()
                if tem_negrito: _renderizar_negrito(para, bloco)
                else: _run(para, bloco, bold=False)
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

        # Bloco de assinaturas
        for _ in range(3):
            doc.add_paragraph()

        campos = [
            ("Presidente da Mesa", "Sr(a). ____"),
            ("Secretário(a)",      "Sr(a). ____ (Administradora)"),
            ("Síndico(a)",         "Sr(a). ____"),
            ("Administradora",     "Administradora Exemplo"),
        ]
        for cargo, nome in campos:
            espaco = doc.add_paragraph()
            _run(espaco, "", tamanho=24)
            linha_sig = doc.add_paragraph()
            _run(linha_sig, "_" * 55, tamanho=11)
            linha_nome = doc.add_paragraph()
            _run(linha_nome, f"{cargo}: {nome}", tamanho=10)
            doc.add_paragraph()

        caminho = os.path.join(tempfile.gettempdir(), nome_arquivo)
        doc.save(caminho)
        return caminho