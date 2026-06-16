import os
from dotenv import load_dotenv

# Carregar variáveis do .env
load_dotenv()

# Configuração centralizada: lê tudo do .env (carregado acima) e expõe como
# atributos de classe. Os defaults aqui são placeholders — segredos vêm do .env.
class Config:

    # Credenciais Plaud (do .env)
    PLAUD_EMAIL = os.environ.get("PLAUD_EMAIL")
    PLAUD_SENHA = os.environ.get("PLAUD_SENHA")
    
    # URLs
    PLAUD_LOGIN_URL = "https://web.plaud.ai/login"
    
    # OpenAI
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    
    # Google Gemini
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    
    # Email para envio
    EMAIL_DESTINATARIO = os.environ.get("EMAIL_DESTINATARIO")
    EMAIL_REMETENTE = os.environ.get("EMAIL_REMETENTE")
    EMAIL_SENHA = os.environ.get("EMAIL_SENHA")
    
    # SMB - Pasta Compartilhada
    SMB_SERVIDOR = os.environ.get("SMB_SERVIDOR", "10.0.0.10")
    SMB_COMPARTILHAMENTO = os.environ.get("SMB_COMPARTILHAMENTO", "Arquivos")
    SMB_USUARIO = os.environ.get("SMB_USUARIO", "svc_automacao")
    SMB_SENHA = os.environ.get("SMB_SENHA")
    SMB_PONTO_MONTAGEM = os.environ.get("SMB_PONTO_MONTAGEM", "/mnt/cliente")
    
    # Caminhos
    CAMINHO_EDITAL_LOCAL = os.environ.get("CAMINHO_EDITAL_LOCAL", "./editais")
    CAMINHO_SAIDA_DOCX = os.environ.get("CAMINHO_SAIDA_DOCX", "./saida")
    CAMINHO_EDITAL_SMB = os.environ.get("CAMINHO_EDITAL_SMB", "/mnt/cliente/Editais")
    
    # NOVO: Pasta de downloads (para salvamento de arquivos)
    DOWNLOAD_PATH = os.environ.get("DOWNLOAD_PATH", "./downloads")
    
    # NOVO: Controle de uso do edital
    # True = Usa edital (prompt estruturado com verificação de pontos)
    # False = Não usa edital (prompt livre baseado apenas no transcript/summary)
    USAR_EDITAL = os.environ.get("USAR_EDITAL", "false").lower() == "true"
    
    # NOVO: Controle de envio de email com ATA
    # True = Envia email com ATA em anexo (útil para testes e notificações)
    # False = Apenas salva na pasta SMB
    ENVIAR_EMAIL_ATA = os.environ.get("ENVIAR_EMAIL_ATA", "false").lower() == "true"
    
    # Servidor Físico (SFTP) - legado
    SERVIDOR_FISICO_IP = os.environ.get("SERVIDOR_FISICO_IP")
    SERVIDOR_FISICO_USER = os.environ.get("SERVIDOR_FISICO_USER")
    SERVIDOR_FISICO_PASS = os.environ.get("SERVIDOR_FISICO_PASS")
    
    # Timeouts
    WAIT_TIMEOUT = 20
    LOGIN_TIMEOUT = 30
    
    CAMINHO_ENV = os.path.abspath('.env')

    # Garante que as credenciais obrigatórias existem no .env; levanta
    # ValueError com o caminho do .env procurado se faltar algo.
    @staticmethod
    def validar_credenciais():
        if not Config.PLAUD_EMAIL:
            raise ValueError(f"PLAUD_EMAIL não está configurado. Arquivo .env procurado em: {Config.CAMINHO_ENV}")
        if not Config.PLAUD_SENHA:
            raise ValueError(f"PLAUD_SENHA não está configurada. Arquivo .env procurado em: {Config.CAMINHO_ENV}")
        return True
    
    # True se a chave da OpenAI está configurada.
    @staticmethod
    def usar_openai_api():
        return bool(Config.OPENAI_API_KEY)

    # True se o pacote whisper está instalado (transcrição local, legado).
    @staticmethod
    def usar_whisper_local():
        try:
            import whisper
            return True
        except ImportError:
            return False
    
    # Cria as pastas de trabalho locais (editais/saída/downloads) se faltarem.
    @staticmethod
    def criar_pastas():
        pastas = [
            Config.CAMINHO_EDITAL_LOCAL,
            Config.CAMINHO_SAIDA_DOCX,
            Config.DOWNLOAD_PATH
        ]
        
        for pasta in pastas:
            if pasta:
                os.makedirs(pasta, exist_ok=True)
        
        return True