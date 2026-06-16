"""
Gerenciador de conexão VPN e montagem SMB.
Conecta à rede do cliente via OpenFortiVPN e monta pasta compartilhada.
"""

import subprocess
import time
import logging
import os

logger = logging.getLogger(__name__)


# Sobe e monitora o túnel OpenFortiVPN que dá à VPS acesso à rede do cliente.
# O perfil de conexão (gateway, usuário, cert) vive em /etc/openfortivpn/config.
class VPNManager:

    def __init__(self):
        self.vpn_process = None
        self.conectado = False

    # Inicia a VPN via openfortivpn e espera até `timeout`s ela subir.
    # Retorna {"sucesso": bool, "mensagem": str}. Idempotente: se já estiver
    # conectada, retorna sucesso sem reabrir o túnel.
    def conectar(self, timeout=30):
        try:
            logger.info("Iniciando conexão VPN (openfortivpn)...")
            
            # Verificar se já está conectado
            if self._verificar_conexao():
                logger.info("[OK] VPN já está conectada")
                self.conectado = True
                return {"sucesso": True, "mensagem": "VPN já conectada"}
            
            # Iniciar openfortivpn em background
            self.vpn_process = subprocess.Popen(
                ["sudo", "openfortivpn"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Aguardar conexão
            inicio = time.time()
            while time.time() - inicio < timeout:
                time.sleep(2)
                if self._verificar_conexao():
                    self.conectado = True
                    logger.info("[OK] VPN conectada com sucesso")
                    return {"sucesso": True, "mensagem": "VPN conectada"}
                
                # Verificar se processo morreu
                if self.vpn_process.poll() is not None:
                    stderr = self.vpn_process.stderr.read()
                    logger.error(f"[ERRO] VPN falhou: {stderr}")
                    return {"sucesso": False, "mensagem": f"VPN falhou: {stderr}"}
            
            # Timeout
            self.desconectar()
            return {"sucesso": False, "mensagem": f"Timeout após {timeout}s"}
            
        except FileNotFoundError:
            logger.error("[ERRO] openfortivpn não encontrado")
            return {"sucesso": False, "mensagem": "openfortivpn não instalado"}
        except Exception as e:
            logger.error(f"[ERRO] Falha ao conectar VPN: {e}")
            return {"sucesso": False, "mensagem": str(e)}
    
    # Testa se o túnel está de pé pingando o servidor de arquivos interno
    # (só responde quando a rota da VPN está ativa).
    def _verificar_conexao(self):
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "10.0.0.10"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    # Encerra a VPN: termina o processo que subimos e ainda dá um pkill de
    # segurança em qualquer openfortivpn órfão.
    def desconectar(self):
        try:
            if self.vpn_process:
                self.vpn_process.terminate()
                self.vpn_process.wait(timeout=5)
                self.vpn_process = None
            
            # Forçar kill de qualquer processo openfortivpn
            subprocess.run(["sudo", "pkill", "-f", "openfortivpn"], capture_output=True)
            
            self.conectado = False
            logger.info("[OK] VPN desconectada")
            return {"sucesso": True, "mensagem": "VPN desconectada"}
        except Exception as e:
            logger.error(f"[ERRO] Falha ao desconectar: {e}")
            return {"sucesso": False, "mensagem": str(e)}


# Monta a pasta compartilhada do cliente (SMB/CIFS) num diretório local da
# VPS, acessível só depois que a VPN está de pé.
class SMBManager:

    # Servidor/credenciais têm default, mas o esperado é virem do .env
    # (SMB_USUARIO/SMB_SENHA) — nunca hardcodar senha real no código.
    def __init__(self, servidor="10.0.0.10", compartilhamento="Arquivos/Automação",
                 usuario=None, senha=None, ponto_montagem="/mnt/cliente"):
        self.servidor = servidor
        self.compartilhamento = compartilhamento
        self.usuario = usuario or os.environ.get("SMB_USUARIO", "svc_automacao")
        self.senha = senha or os.environ.get("SMB_SENHA", "")
        self.ponto_montagem = ponto_montagem
        self.montado = False
    
    # Monta o share via mount.cifs no ponto de montagem. Idempotente (não
    # remonta se já estiver montado). Retorna {sucesso, mensagem, caminho}.
    def montar(self):
        try:
            logger.info(f"Montando pasta SMB: //{self.servidor}/{self.compartilhamento}")
            
            # Criar ponto de montagem se não existir
            os.makedirs(self.ponto_montagem, exist_ok=True)
            
            # Verificar se já está montado
            if self._verificar_montagem():
                logger.info(f"[OK] Pasta já montada em {self.ponto_montagem}")
                self.montado = True
                return {
                    "sucesso": True,
                    "mensagem": "Pasta já montada",
                    "caminho": self.ponto_montagem
                }
            
            # Montar via mount.cifs
            # Formato: //servidor/compartilhamento
            unc_path = f"//{self.servidor}/{self.compartilhamento}"
            
            # Opções de montagem
            opcoes = f"username={self.usuario},password={self.senha},iocharset=utf8,file_mode=0777,dir_mode=0777"
            
            result = subprocess.run(
                ["sudo", "mount", "-t", "cifs", unc_path, self.ponto_montagem, "-o", opcoes],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self.montado = True
                logger.info(f"[OK] Pasta montada em {self.ponto_montagem}")
                return {
                    "sucesso": True,
                    "mensagem": "Pasta montada com sucesso",
                    "caminho": self.ponto_montagem
                }
            else:
                logger.error(f"[ERRO] Falha ao montar: {result.stderr}")
                return {
                    "sucesso": False,
                    "mensagem": f"Falha ao montar: {result.stderr}",
                    "caminho": None
                }
                
        except subprocess.TimeoutExpired:
            logger.error("[ERRO] Timeout ao montar pasta")
            return {"sucesso": False, "mensagem": "Timeout", "caminho": None}
        except Exception as e:
            logger.error(f"[ERRO] Falha ao montar: {e}")
            return {"sucesso": False, "mensagem": str(e), "caminho": None}
    
    # True se o ponto de montagem já é um mountpoint ativo.
    def _verificar_montagem(self):
        try:
            result = subprocess.run(
                ["mountpoint", "-q", self.ponto_montagem],
                capture_output=True
            )
            return result.returncode == 0
        except:
            return False
    
    # Desmonta o share (umount). Se não estiver montado, é no-op com sucesso.
    def desmontar(self):
        try:
            if not self._verificar_montagem():
                logger.info("Pasta não está montada")
                return {"sucesso": True, "mensagem": "Pasta não montada"}
            
            result = subprocess.run(
                ["sudo", "umount", self.ponto_montagem],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                self.montado = False
                logger.info("[OK] Pasta desmontada")
                return {"sucesso": True, "mensagem": "Pasta desmontada"}
            else:
                logger.error(f"[ERRO] Falha ao desmontar: {result.stderr}")
                return {"sucesso": False, "mensagem": result.stderr}
                
        except Exception as e:
            logger.error(f"[ERRO] Falha ao desmontar: {e}")
            return {"sucesso": False, "mensagem": str(e)}
    
    # Varre recursivamente o ponto de montagem e devolve os caminhos
    # absolutos dos arquivos com a extensão dada (None = todos).
    def listar_arquivos(self, extensao=".docx"):
        arquivos = []
        
        if not self.montado and not self._verificar_montagem():
            logger.warning("Pasta não está montada")
            return arquivos
        
        try:
            for root, dirs, files in os.walk(self.ponto_montagem):
                for file in files:
                    if extensao is None or file.lower().endswith(extensao.lower()):
                        arquivos.append(os.path.join(root, file))
            
            logger.info(f"Encontrados {len(arquivos)} arquivo(s) {extensao}")
            return arquivos
            
        except Exception as e:
            logger.error(f"[ERRO] Falha ao listar arquivos: {e}")
            return []
    
    # Devolve o .docx mais recente por data de modificação (ou None se vazio).
    # Legado: o pipeline atual processa TODOS os editais pendentes, não só este.
    def obter_edital_mais_recente(self):
        arquivos = self.listar_arquivos(".docx")
        
        if not arquivos:
            logger.warning("Nenhum arquivo DOCX encontrado")
            return None
        
        # Ordenar por data de modificação (mais recente primeiro)
        arquivos.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        
        mais_recente = arquivos[0]
        logger.info(f"Edital mais recente: {os.path.basename(mais_recente)}")
        
        return mais_recente