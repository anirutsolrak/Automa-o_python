"""Persistência JSON de editais já processados.

Identidade dos editais por SHA256 do conteúdo (.docx). Se o cliente
reenviar o mesmo edital com nome diferente, não reprocessa. Se editar
o edital (correção), o hash muda e o sistema reprocessa naturalmente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


# SHA256 hex do conteúdo do arquivo — é a identidade do edital (ver módulo).
def _hash_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


# Mantém em JSON local a lista de editais já processados (por hash), pra o
# pipeline não gerar a mesma ATA duas vezes em execuções diferentes.
class ProcessadosTracker:

    def __init__(self, caminho: str = "/opt/plaud/processados.json"):
        self.caminho = caminho
        self._entradas: list[dict] = []
        self._carregar()

    # Carrega o JSON do disco. Arquivo ausente ou corrompido = começa vazio
    # (não derruba o pipeline por causa de um JSON quebrado).
    def _carregar(self) -> None:
        if not os.path.exists(self.caminho):
            self._entradas = []
            return
        try:
            with open(self.caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
            self._entradas = dados if isinstance(dados, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("[TRACKER] %s corrompido (%s) — iniciando vazio.", self.caminho, e)
            self._entradas = []

    # Grava num arquivo temporário e faz rename — escrita atômica, pra um
    # crash no meio não deixar o processados.json pela metade.
    def _salvar(self) -> None:
        diretorio = os.path.dirname(self.caminho) or "."
        os.makedirs(diretorio, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=diretorio, prefix=".processados_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._entradas, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.caminho)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # True se um edital com este conteúdo (hash) já foi processado antes.
    def ja_processado(self, edital_path: str) -> bool:
        if not os.path.exists(edital_path):
            return False
        h = _hash_arquivo(edital_path)
        return any(e.get("edital_hash") == h for e in self._entradas)

    # Registra (ou atualiza) o edital como processado, guardando o áudio
    # casado e o caminho da ATA gerada. Persiste no disco a cada chamada.
    def marcar_processado(self, edital_path: str, audio_file_id: str, ata_path: str) -> None:
        from datetime import datetime
        h = _hash_arquivo(edital_path)
        # se já existe entrada com esse hash, atualiza; senão adiciona nova
        for entrada in self._entradas:
            if entrada.get("edital_hash") == h:
                entrada.update({
                    "audio_file_id": audio_file_id,
                    "ata_path": ata_path,
                    "data_processamento": datetime.now().isoformat(timespec="seconds"),
                })
                self._salvar()
                return
        self._entradas.append({
            "edital_hash": h,
            "edital_nome": os.path.basename(edital_path),
            "data_processamento": datetime.now().isoformat(timespec="seconds"),
            "audio_file_id": audio_file_id,
            "ata_path": ata_path,
        })
        self._salvar()
