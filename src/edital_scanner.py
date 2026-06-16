"""Lista editais .docx pendentes em uma pasta SMB recursiva.

Filtra os já registrados no ProcessadosTracker.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from src.processados_tracker import ProcessadosTracker

logger = logging.getLogger(__name__)


# Varre recursivamente a pasta de editais e devolve só os .docx que ainda
# não foram processados (cruzando com o ProcessadosTracker).
class EditalScanner:

    def __init__(self, pasta_raiz: str, tracker: ProcessadosTracker, max_depth: int = 5):
        self.pasta_raiz = pasta_raiz
        self.tracker = tracker
        self.max_depth = max_depth  # limita a profundidade do walk recursivo

    # Caminhos absolutos dos .docx pendentes, ordenados por mtime ascendente
    # (mais antigos primeiro). `limite` corta o resultado quando informado.
    def listar_pendentes(self, limite: Optional[int] = None) -> list[str]:
        if not os.path.isdir(self.pasta_raiz):
            logger.warning("[SCANNER] Pasta não existe: %s", self.pasta_raiz)
            return []

        encontrados: list[str] = []
        raiz_depth = self.pasta_raiz.count(os.sep)
        for root, dirs, files in os.walk(self.pasta_raiz):
            if root.count(os.sep) - raiz_depth > self.max_depth:
                dirs.clear()
                continue
            for nome in files:
                if not nome.lower().endswith(".docx"):
                    continue
                if nome.startswith("~$") or nome.startswith("."):
                    continue  # pula temporários do Word (~$) e arquivos ocultos
                caminho = os.path.join(root, nome)
                encontrados.append(caminho)

        # Ordena por mtime ascendente
        encontrados.sort(key=lambda p: os.path.getmtime(p))

        pendentes = [p for p in encontrados if not self.tracker.ja_processado(p)]
        logger.info("[SCANNER] %d encontrado(s), %d pendente(s) (de %s)",
                    len(encontrados), len(pendentes), self.pasta_raiz)

        if limite is not None and limite > 0:
            pendentes = pendentes[:limite]
        return pendentes
