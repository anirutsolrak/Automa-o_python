"""Wrapper Python sobre o comando `smbclient` (samba userspace).

Substitui mount.cifs no kernel (que tem incompatibilidade NTLM com alguns
servidores Windows corporativos). Usa subprocess pra listar/baixar/subir
arquivos diretamente pela URL SMB.

Estrutura usada na Administradora:
    //10.0.0.10/Arquivos/Automacao/Editais/<ano>/<edital>.docx
    //10.0.0.10/Arquivos/Automacao/Atas (concluidas pela automacao)/<ano>/<ata>.docx
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class SMBClientError(Exception):
    def __init__(self, returncode: int, stderr: str):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"smbclient exited {returncode}: {stderr.strip()}")


# Cliente SMB que fala com o servidor de arquivos via subprocess do
# `smbclient` (userspace) — ver no topo do módulo por que não usa mount.cifs.
class SMBClient:

    def __init__(self, servidor: str, share: str, usuario: str, senha: str):
        self.servidor = servidor
        self.share = share
        self.usuario = usuario
        self.senha = senha
        self._bin = shutil.which("smbclient") or "smbclient"

    @property
    def _unc(self) -> str:
        return f"//{self.servidor}/{self.share}"

    # Executa um comando interno do smbclient (ls/get/put/...) via flag -c.
    # A senha vai pela variável PASSWD (lida pelo smbclient), não pela linha de
    # comando: argumentos de processo aparecem no `ps` para qualquer usuário.
    def _run(self, cmd_smb: str, timeout: int = 60) -> subprocess.CompletedProcess:
        args = [self._bin, self._unc, "-U", self.usuario, "-c", cmd_smb]
        logger.debug("smbclient cmd: %s", cmd_smb)
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env={**os.environ, "PASSWD": self.senha},
        )

    # ───── Listar ───────────────────────────────────────────────────────

    # Regex que casa linhas da saída de `ls`:
    #   "  nome do arquivo.docx           A    12345  Sun May 25 10:00:00 2026"
    # Grupos: nome, atributos, size, data (resto)
    _RE_LS = re.compile(
        r"^\s+(?P<nome>.+?)\s{2,}(?P<attr>[DAHSRN]+)\s+(?P<size>\d+)\s+"
        r"(?P<data>\w{3}\s+\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4})\s*$"
    )

    # Lista os arquivos (não-diretórios) de remote_dir, parseando a saída do
    # `ls` por regex. Devolve [{name, size, mtime, attr}], ignorando '.'/'..'.
    def listar(self, remote_dir: str) -> list[dict]:
        cmd = f'cd "{remote_dir}"; ls'
        result = self._run(cmd)
        if result.returncode != 0:
            raise SMBClientError(result.returncode, result.stderr)
        arquivos: list[dict] = []
        for linha in result.stdout.splitlines():
            m = self._RE_LS.match(linha)
            if not m:
                continue
            nome = m.group("nome").strip()
            if nome in (".", ".."):
                continue
            attr = m.group("attr")
            if "D" in attr:
                continue  # diretório
            try:
                mtime = datetime.strptime(m.group("data"), "%a %b %d %H:%M:%S %Y")
            except ValueError:
                mtime = datetime.now()
            arquivos.append({
                "name": nome,
                "size": int(m.group("size")),
                "mtime": mtime,
                "attr": attr,
            })
        return arquivos

    # ───── Baixar / Subir ───────────────────────────────────────────────

    # Baixa um arquivo do share pro disco local, criando os diretórios locais
    # que faltarem. Levanta SMBClientError se o get falhar ou o arquivo não
    # aparecer no destino.
    def baixar(self, remote_path: str, local_path: str, timeout: int = 120) -> None:
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        remote_dir = os.path.dirname(remote_path).replace("\\", "/")
        remote_file = os.path.basename(remote_path)
        if remote_dir:
            cmd = f'cd "{remote_dir}"; get "{remote_file}" "{local_path}"'
        else:
            cmd = f'get "{remote_file}" "{local_path}"'
        result = self._run(cmd, timeout=timeout)
        if result.returncode != 0:
            raise SMBClientError(result.returncode, result.stderr)
        if not os.path.exists(local_path):
            raise SMBClientError(0, f"arquivo não baixado: {local_path}")

    # Sobe um arquivo local pro share. Faz mkdir best-effort do diretório
    # remoto (ignora erro se já existe) antes do put.
    def subir(self, local_path: str, remote_path: str, timeout: int = 120) -> None:
        if not os.path.exists(local_path):
            raise SMBClientError(0, f"arquivo local não existe: {local_path}")
        remote_dir = os.path.dirname(remote_path).replace("\\", "/")
        remote_file = os.path.basename(remote_path)
        # mkdir é best-effort — ignora erro se já existe
        if remote_dir:
            self._run(f'mkdir "{remote_dir}"', timeout=10)
            cmd = f'cd "{remote_dir}"; put "{local_path}" "{remote_file}"'
        else:
            cmd = f'put "{local_path}" "{remote_file}"'
        result = self._run(cmd, timeout=timeout)
        if result.returncode != 0:
            raise SMBClientError(result.returncode, result.stderr)

    # Smoke test de conexão: tenta listar a raiz do share. Usado pelo
    # pipeline pra abortar cedo (exit 4) se o SMB não responder.
    def conectividade_ok(self) -> bool:
        try:
            r = self._run("ls", timeout=15)
            return r.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
