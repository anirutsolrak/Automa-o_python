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
