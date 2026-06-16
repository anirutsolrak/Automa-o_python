"""Matching áudio ↔ edital em 4 níveis de fallback.

1. Filtro por data (±1 dia)
2. Nome do condomínio no título do áudio
3. Nome do condomínio no conteúdo do transcript (download sob demanda)
4. Eliminação por outros pares já casados nesta rodada
+ fallback: primeiro candidato com log warning, ou None
"""

from __future__ import annotations

import logging
import os
import re
import string
import unicodedata
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


# Regex para extrair data do nome do edital
RE_DATA_NOME = re.compile(
    r"^\s*(\d{1,2})[\.\-/](\d{1,2})[\.\-/](\d{4})\s+(.+)$"
)


# Normaliza texto p/ matching fuzzy: minúsculas, sem acento, sem
# pontuação, espaços colapsados. Ex: "Edifício Alfa, S.A." -> "edificio alfa sa".
def normalizar_para_busca(texto: str) -> str:
    # NFKD separa o acento da letra; ASCII-ignore descarta só o acento
    s = unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("ASCII")
    s = s.lower()
    for c in string.punctuation:
        s = s.replace(c, "")
    return " ".join(s.split())  # colapsa espaços múltiplos em um só


# Extrai o nome do condomínio do nome do arquivo do edital.
# Convenção dos arquivos: "DD.MM.AAAA Nome do Condomínio.docx".
def extrair_nome_condominio_do_edital(filename: str) -> str:
    base = os.path.splitext(os.path.basename(filename))[0]
    m = RE_DATA_NOME.match(base)
    if m:
        return m.group(4).strip()  # grupo 4 = tudo que vem depois da data
    return base.strip()            # sem data no nome: usa o nome inteiro


# Extrai a data do nome do arquivo ("DD.MM.AAAA ...") como date.
# Retorna None se o nome não começar com uma data válida.
def extrair_data_do_edital(filename: str) -> Optional[date]:
    base = os.path.splitext(os.path.basename(filename))[0]
    m = RE_DATA_NOME.match(base)
    if not m:
        return None
    try:
        # grupos do regex: 1=dia, 2=mês, 3=ano
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except (ValueError, TypeError):
        return None  # data impossível (ex: "32.13.2026")


# Associa cada edital ao áudio correto aplicando os 4 níveis descritos no
# topo do módulo. Mantém estado por rodada (cache de transcript e pares já
# casados) pra não baixar o mesmo transcript 2x nem reusar o mesmo áudio.
class AtaMatcher:

    TOLERANCIA_DIAS = 1            # janela de ± dias entre data do edital e do áudio
    CHARS_BUSCA_TRANSCRIPT = 5000  # só os primeiros N chars do transcript entram na busca

    def __init__(self, plaud_client):
        self.plaud = plaud_client
        self._transcript_cache: dict[str, str] = {}  # file_id -> transcript (evita re-download)
        self._pares_usados: set[str] = set()          # áudios já atribuídos nesta rodada

    # Marca um áudio como usado, pra outro edital do mesmo dia não pegá-lo.
    def marcar_par_usado(self, file_id: str) -> None:
        self._pares_usados.add(file_id)

    # Data real da reunião do áudio. Prioriza a data contida no nome (ex:
    # "28.05.2026 Nome do Condomínio") porque o campo de data do Plaud é a
    # data de UPLOAD, que pode ser dias depois da reunião. Só usa o campo do
    # Plaud como fallback quando o nome não tem data.
    def _data_do_audio(self, candidato: dict) -> Optional[date]:
        nome = candidato.get("name", "")
        data_pelo_nome = extrair_data_do_edital(nome)  # reaproveita o regex DD.MM.AAAA
        if data_pelo_nome:
            return data_pelo_nome
        # fallback: data de criação (upload) registrada pelo Plaud
        try:
            return datetime.strptime(candidato["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            return None

    # Nível 1: mantém só os áudios cuja data cai dentro de TOLERANCIA_DIAS da
    # data do edital. Sem data no edital não dá pra filtrar: devolve todos.
    def _filtrar_por_data(self, edital_path: str, candidatos: list[dict]) -> list[dict]:
        data_edital = extrair_data_do_edital(edital_path)
        if data_edital is None:
            return list(candidatos)
        resultado = []
        for c in candidatos:
            d = self._data_do_audio(c)
            if d is None:
                continue
            if abs((d - data_edital).days) <= self.TOLERANCIA_DIAS:
                resultado.append(c)
        return resultado

    # Nível 2: mantém os áudios cujo título contém o nome do condomínio
    # (comparação normalizada, tolerante a acento/pontuação/caixa).
    def _filtrar_por_titulo(self, nome_condominio: str, candidatos: list[dict]) -> list[dict]:
        alvo = normalizar_para_busca(nome_condominio)
        if not alvo:
            return list(candidatos)  # edital sem nome: não dá pra filtrar por título
        return [c for c in candidatos if alvo in normalizar_para_busca(c.get("name", ""))]

    # Nível 3: desempate caro. Baixa o transcript de cada candidato (sob
    # demanda, cacheado) e mantém os que citam o nome do condomínio no início
    # da fala. Só roda quando o título não resolveu, pra evitar downloads.
    def _filtrar_por_transcript(self, nome_condominio: str, candidatos: list[dict]) -> list[dict]:
        alvo = normalizar_para_busca(nome_condominio)
        if not alvo:
            return list(candidatos)
        casados = []
        for c in candidatos:
            fid = c["id"]
            if fid not in self._transcript_cache:  # baixa só uma vez por áudio
                try:
                    self._transcript_cache[fid] = str(self.plaud.get_transcript(fid))
                except Exception as e:
                    logger.warning("[MATCHER] falha ao baixar transcript de %s: %s", fid, e)
                    self._transcript_cache[fid] = ""  # cacheia vazio: não retenta
            trecho = self._transcript_cache[fid][: self.CHARS_BUSCA_TRANSCRIPT]
            if alvo in normalizar_para_busca(trecho):
                casados.append(c)
        return casados

    # Ponto de entrada: recebe o edital e os áudios candidatos do dia e
    # devolve o áudio correspondente (ou None se ambíguo/inexistente).
    # Aplica os níveis em ordem e PARA assim que um deles isola 1 candidato.
    def match(self, edital_path: str, candidatos: list[dict]) -> Optional[dict]:
        nome = extrair_nome_condominio_do_edital(edital_path)
        logger.info("[MATCHER] '%s' → nome='%s', %d candidato(s)",
                    os.path.basename(edital_path), nome, len(candidatos))

        # Pré-filtro: remove áudios já atribuídos nesta rodada
        candidatos = [c for c in candidatos if c["id"] not in self._pares_usados]
        if not candidatos:
            logger.warning("[MATCHER] todos os candidatos já usados por outros editais → None")
            return None
        logger.info("[MATCHER] %d candidato(s) disponíveis após filtrar já usados", len(candidatos))

        # Nível 1: data
        por_data = self._filtrar_por_data(edital_path, candidatos)
        if not por_data:
            logger.warning("[MATCHER] nenhum candidato na data → None")
            return None
        if len(por_data) == 1:
            logger.info("[MATCHER] match por data (único candidato disponível)")
            return por_data[0]

        # Nível 2: título
        por_titulo = self._filtrar_por_titulo(nome, por_data)
        if len(por_titulo) == 1:
            logger.info("[MATCHER] match por título")
            return por_titulo[0]
        base = por_titulo if por_titulo else por_data

        # Nível 3: transcript
        if len(base) > 1:
            por_transcript = self._filtrar_por_transcript(nome, base)
            if len(por_transcript) == 1:
                logger.info("[MATCHER] match por transcript")
                return por_transcript[0]
            if por_transcript:
                base = por_transcript

        # Nível 4: ambíguo — fallback no primeiro disponível
        if base:
            logger.warning("[MATCHER] %d candidato(s) ambíguo(s), fallback no primeiro: %s",
                           len(base), base[0].get("name"))
            return base[0]

        logger.warning("[MATCHER] sem candidato disponível → None")
        return None
