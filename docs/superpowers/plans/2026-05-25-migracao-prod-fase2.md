# Fase 2 — Migração Plaud CLI para Produção — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar os 3 componentes novos (`ProcessadosTracker`, `EditalScanner`, `AtaMatcher`) e o novo `pipeline.py` que substitui as etapas Selenium por `PlaudClient`, processando todos os editais pendentes da pasta SMB por execução do cron.

**Architecture:** Pipeline em 6 etapas — auth+VPN+SMB intactos, novo loop sobre editais pendentes com matching de 4 níveis pra cada um (data → título → transcript → eliminação). Tracking via JSON local com hash SHA256 pra idempotência. Rollback rápido mantendo `pipeline_legacy_<data>.py` no disco.

**Tech Stack:** Python 3.x, pytest (TDD), json/hashlib (tracker), unittest.mock (testes), componentes existentes do POC (`PlaudClient`, `IAProcessor`, `AtaVerifier`, `EditalReader`, `EmailSender`).

---

## File Structure

**Arquivos a criar:**
- `src/processados_tracker.py` — Persistência JSON com SHA256
- `src/edital_scanner.py` — Walk recursivo + filtro de pendentes
- `src/ata_matcher.py` — Matching 4 níveis
- `tests/test_processados_tracker.py`
- `tests/test_edital_scanner.py`
- `tests/test_ata_matcher.py`

**Arquivos a modificar/substituir:**
- `pipeline.py` — Reescrita total (backup como `pipeline_legacy_<YYYYMMDD>.py` ANTES)

**Arquivos intactos:**
- `src/plaud_client.py`, `src/ia_processor.py`, `src/ata_verifier.py`
- `src/edital_reader.py`, `src/email_sender.py`, `src/vpn_manager.py`, `src/config.py`

---

## Task 1: `ProcessadosTracker` — persistência JSON com SHA256

**Files:**
- Create: `src/processados_tracker.py`
- Create: `tests/test_processados_tracker.py`

- [ ] **Step 1: Escrever testes**

Create `tests/test_processados_tracker.py`:

```python
"""Testes do ProcessadosTracker."""

import json
import os
import pytest


@pytest.fixture
def tmp_tracker(tmp_path):
    from src.processados_tracker import ProcessadosTracker
    return ProcessadosTracker(caminho=str(tmp_path / "processados.json"))


@pytest.fixture
def edital_fake(tmp_path):
    p = tmp_path / "13.05.2026 Alfa.docx"
    p.write_bytes(b"conteudo fake do edital " * 100)
    return str(p)


def test_tracker_inicializa_com_arquivo_inexistente(tmp_tracker):
    """Sem arquivo, tracker começa vazio sem erro."""
    assert tmp_tracker.ja_processado("/qualquer/path.docx") is False


def test_marcar_processado_cria_entrada(tmp_tracker, edital_fake):
    tmp_tracker.marcar_processado(edital_fake, "audio_id_123", "/saida/ATA.docx")
    assert tmp_tracker.ja_processado(edital_fake) is True


def test_ja_processado_usa_hash_nao_caminho(tmp_tracker, edital_fake, tmp_path):
    """Edital com nome diferente mas mesmo conteúdo: já processado."""
    tmp_tracker.marcar_processado(edital_fake, "id1", "/x.docx")
    duplicado = tmp_path / "renomeado.docx"
    duplicado.write_bytes(open(edital_fake, "rb").read())
    assert tmp_tracker.ja_processado(str(duplicado)) is True


def test_edital_editado_reprocessa(tmp_tracker, edital_fake):
    tmp_tracker.marcar_processado(edital_fake, "id1", "/x.docx")
    # Modifica conteúdo
    with open(edital_fake, "wb") as f:
        f.write(b"conteudo MODIFICADO" * 100)
    assert tmp_tracker.ja_processado(edital_fake) is False


def test_persistencia_entre_instancias(tmp_path, edital_fake):
    from src.processados_tracker import ProcessadosTracker
    caminho = str(tmp_path / "processados.json")
    t1 = ProcessadosTracker(caminho=caminho)
    t1.marcar_processado(edital_fake, "id1", "/x.docx")
    # Nova instância lê o arquivo
    t2 = ProcessadosTracker(caminho=caminho)
    assert t2.ja_processado(edital_fake) is True


def test_arquivo_json_corrompido_nao_quebra(tmp_path, edital_fake):
    from src.processados_tracker import ProcessadosTracker
    caminho = str(tmp_path / "processados.json")
    with open(caminho, "w") as f:
        f.write("{ json invalido !!!")
    t = ProcessadosTracker(caminho=caminho)
    # Não levanta exceção, trata como vazio
    assert t.ja_processado(edital_fake) is False
    # E permite gravar normalmente depois
    t.marcar_processado(edital_fake, "id1", "/x.docx")
    assert t.ja_processado(edital_fake) is True
```

- [ ] **Step 2: Rodar — devem falhar**

```
pytest tests/test_processados_tracker.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.processados_tracker'`.

- [ ] **Step 3: Implementar**

Create `src/processados_tracker.py`:

```python
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


def _hash_arquivo(caminho: str) -> str:
    """SHA256 hex do conteúdo do arquivo."""
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(8192), b""):
            h.update(bloco)
    return h.hexdigest()


class ProcessadosTracker:
    """Mantém lista de hashes de editais já processados em JSON local."""

    def __init__(self, caminho: str = "/opt/plaud/processados.json"):
        self.caminho = caminho
        self._entradas: list[dict] = []
        self._carregar()

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

    def _salvar(self) -> None:
        """Write tmp + rename = atômico contra crash."""
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

    def ja_processado(self, edital_path: str) -> bool:
        if not os.path.exists(edital_path):
            return False
        h = _hash_arquivo(edital_path)
        return any(e.get("edital_hash") == h for e in self._entradas)

    def marcar_processado(self, edital_path: str, audio_file_id: str, ata_path: str) -> None:
        from datetime import datetime
        h = _hash_arquivo(edital_path)
        # Se já existe, atualiza; senão adiciona
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
```

- [ ] **Step 4: Rodar — devem passar**

```
pytest tests/test_processados_tracker.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/processados_tracker.py tests/test_processados_tracker.py
git commit -m "feat(tracker): ProcessadosTracker com SHA256 e gravação atômica"
```

---

## Task 2: `EditalScanner` — lista editais pendentes

**Files:**
- Create: `src/edital_scanner.py`
- Create: `tests/test_edital_scanner.py`

- [ ] **Step 1: Escrever testes**

Create `tests/test_edital_scanner.py`:

```python
"""Testes do EditalScanner."""

import os
import time
import pytest


@pytest.fixture
def pasta_fake(tmp_path):
    """Estrutura: <root>/Editais/<arquivos>.docx + Processados/"""
    raiz = tmp_path / "Editais"
    raiz.mkdir()
    # Cria 3 editais com mtimes distintos
    a = raiz / "13.05.2026 Alfa.docx"
    a.write_bytes(b"A" * 1000)
    time.sleep(0.01)
    b = raiz / "14.05.2026 Zeta.docx"
    b.write_bytes(b"B" * 1000)
    time.sleep(0.01)
    c = raiz / "15.05.2026 Delta.docx"
    c.write_bytes(b"C" * 1000)
    # Subpasta com mais um
    sub = raiz / "subpasta"
    sub.mkdir()
    d = sub / "16.05.2026 Omega.docx"
    d.write_bytes(b"D" * 1000)
    return str(raiz)


@pytest.fixture
def tracker_vazio(tmp_path):
    from src.processados_tracker import ProcessadosTracker
    return ProcessadosTracker(caminho=str(tmp_path / "p.json"))


def test_lista_todos_quando_tracker_vazio(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert len(pendentes) == 4
    nomes = [os.path.basename(p) for p in pendentes]
    assert "13.05.2026 Alfa.docx" in nomes
    assert "16.05.2026 Omega.docx" in nomes  # da subpasta


def test_ordena_por_mtime_ascendente(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    # Alfa criado primeiro → vem primeiro
    assert "Alfa" in pendentes[0]


def test_filtra_ja_processados(pasta_fake, tracker_vazio):
    """Editais marcados no tracker não aparecem em pendentes."""
    from src.edital_scanner import EditalScanner
    # Marca Alfa como processado
    alfa_path = os.path.join(pasta_fake, "13.05.2026 Alfa.docx")
    tracker_vazio.marcar_processado(alfa_path, "audio_x", "/ata.docx")

    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert len(pendentes) == 3
    assert not any("Alfa" in p for p in pendentes)


def test_aplica_limite(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes(limite=2)
    assert len(pendentes) == 2


def test_pasta_inexistente_retorna_vazio(tmp_path, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(str(tmp_path / "inexistente"), tracker_vazio)
    assert scanner.listar_pendentes() == []


def test_ignora_arquivos_temporarios_word(pasta_fake, tracker_vazio):
    """Arquivos '~$nome.docx' do Word não devem aparecer."""
    from src.edital_scanner import EditalScanner
    lixo = os.path.join(pasta_fake, "~$13.05.2026 Alfa.docx")
    with open(lixo, "wb") as f:
        f.write(b"lock")
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert not any("~$" in p for p in pendentes)
```

- [ ] **Step 2: Rodar — devem falhar**

```
pytest tests/test_edital_scanner.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Create `src/edital_scanner.py`:

```python
"""Lista editais .docx pendentes em uma pasta SMB recursiva.

Filtra os já registrados no ProcessadosTracker.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from src.processados_tracker import ProcessadosTracker

logger = logging.getLogger(__name__)


class EditalScanner:
    """Walk recursivo + filtro de pendentes."""

    def __init__(self, pasta_raiz: str, tracker: ProcessadosTracker, max_depth: int = 5):
        self.pasta_raiz = pasta_raiz
        self.tracker = tracker
        self.max_depth = max_depth

    def listar_pendentes(self, limite: Optional[int] = None) -> list[str]:
        """Retorna caminhos absolutos de .docx pendentes, ordenados por mtime asc."""
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
                    continue
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
```

- [ ] **Step 4: Rodar — devem passar**

```
pytest tests/test_edital_scanner.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```
git add src/edital_scanner.py tests/test_edital_scanner.py
git commit -m "feat(scanner): EditalScanner lista pendentes ordenados por mtime"
```

---

## Task 3: `AtaMatcher` — matching de 4 níveis

**Files:**
- Create: `src/ata_matcher.py`
- Create: `tests/test_ata_matcher.py`

- [ ] **Step 1: Escrever testes**

Create `tests/test_ata_matcher.py`:

```python
"""Testes do AtaMatcher."""

from unittest.mock import MagicMock
import pytest


@pytest.fixture
def plaud_mock():
    return MagicMock()


@pytest.fixture
def candidatos_dia_13():
    return [
        {"id": "id_alfa",    "name": "13.05.2026 Alfa",        "date": "2026-05-14", "duration_seconds": 11280},
        {"id": "id_outro",      "name": "13.05.2026 Outro",          "date": "2026-05-14", "duration_seconds": 3600},
        {"id": "id_dia_errado", "name": "12.05.2026 Outro Dia",      "date": "2026-05-13", "duration_seconds": 3600},
    ]


def test_normalizar_para_busca_remove_acento_e_pontuacao():
    from src.ata_matcher import normalizar_para_busca
    assert normalizar_para_busca("Edifício Alfa, S.A.") == "edificio alfa sa"


def test_extrair_nome_condominio_formato_data_ponto():
    from src.ata_matcher import extrair_nome_condominio_do_edital
    assert extrair_nome_condominio_do_edital("13.05.2026 Alfa.docx") == "Alfa"


def test_extrair_nome_condominio_formato_data_traco():
    from src.ata_matcher import extrair_nome_condominio_do_edital
    assert extrair_nome_condominio_do_edital("13-05-2026 Gama.docx") == "Gama"


def test_extrair_nome_condominio_sem_data():
    from src.ata_matcher import extrair_nome_condominio_do_edital
    assert extrair_nome_condominio_do_edital("Theta.docx") == "Theta"


def test_match_nivel1_por_data_unico_candidato(plaud_mock, candidatos_dia_13):
    """Quando data+nome do edital filtra para 1 candidato, retorna direto."""
    from src.ata_matcher import AtaMatcher
    matcher = AtaMatcher(plaud_mock)
    # Edital "13.05.2026 Alfa" — só id_alfa tem data correta E nome no título
    resultado = matcher.match("/x/13.05.2026 Alfa.docx", candidatos_dia_13)
    assert resultado["id"] == "id_alfa"


def test_match_nivel2_busca_nome_no_titulo(plaud_mock):
    """2 candidatos na mesma data, nome do edital aparece em apenas 1 título."""
    from src.ata_matcher import AtaMatcher
    candidatos = [
        {"id": "id_alfa", "name": "13.05.2026 Alfa", "date": "2026-05-14", "duration_seconds": 11280},
        {"id": "id_alice",   "name": "13.05.2026 Alice",   "date": "2026-05-14", "duration_seconds": 3600},
    ]
    matcher = AtaMatcher(plaud_mock)
    resultado = matcher.match("/x/13.05.2026 Alfa.docx", candidatos)
    assert resultado["id"] == "id_alfa"


def test_match_nivel3_busca_no_transcript(plaud_mock):
    """2 candidatos mesma data, nenhum com nome no título → busca transcript."""
    from src.ata_matcher import AtaMatcher
    candidatos = [
        {"id": "id_audio_a", "name": "13.05.2026 Reuniao", "date": "2026-05-14", "duration_seconds": 3600},
        {"id": "id_audio_b", "name": "13.05.2026 Outro",   "date": "2026-05-14", "duration_seconds": 3600},
    ]
    plaud_mock.get_transcript.side_effect = lambda fid: (
        "Boa noite a todos do Condomínio Alfa..." if fid == "id_audio_a" else "Reuniao do edificio Zeta..."
    )
    matcher = AtaMatcher(plaud_mock)
    resultado = matcher.match("/x/13.05.2026 Alfa.docx", candidatos)
    assert resultado["id"] == "id_audio_a"
    plaud_mock.get_transcript.assert_called()


def test_match_nivel4_eliminacao_de_pares_usados(plaud_mock, candidatos_dia_13):
    """Se id_alfa já foi casado, próximo edital sem match único pega outro."""
    from src.ata_matcher import AtaMatcher
    matcher = AtaMatcher(plaud_mock)
    matcher.marcar_par_usado("id_alfa")
    # Edital genérico "Outro" — só id_outro sobra na mesma data
    resultado = matcher.match("/x/13.05.2026 Outro.docx", candidatos_dia_13)
    assert resultado is not None
    assert resultado["id"] == "id_outro"


def test_match_retorna_none_sem_candidatos_na_data(plaud_mock):
    from src.ata_matcher import AtaMatcher
    candidatos = [
        {"id": "id_x", "name": "01.01.2026 Outro", "date": "2026-01-02", "duration_seconds": 3600},
    ]
    matcher = AtaMatcher(plaud_mock)
    resultado = matcher.match("/x/13.05.2026 Alfa.docx", candidatos)
    assert resultado is None


def test_match_fallback_aceita_data_proxima_1_dia(plaud_mock):
    """Edital de 13/05, áudio gravado dia 14/05 (lag de fuso) — match com tolerância."""
    from src.ata_matcher import AtaMatcher
    candidatos = [
        {"id": "id_x", "name": "Reuniao", "date": "2026-05-15", "duration_seconds": 3600},  # +2 dias = nope
        {"id": "id_y", "name": "Reuniao", "date": "2026-05-14", "duration_seconds": 3600},  # +1 dia = ok
    ]
    matcher = AtaMatcher(plaud_mock)
    resultado = matcher.match("/x/13.05.2026 Alfa.docx", candidatos)
    assert resultado is not None
    assert resultado["id"] == "id_y"
```

- [ ] **Step 2: Rodar — devem falhar**

```
pytest tests/test_ata_matcher.py -v
```
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Create `src/ata_matcher.py`:

```python
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


def normalizar_para_busca(texto: str) -> str:
    """Lower + sem acento + sem pontuação + espaços normalizados."""
    s = unicodedata.normalize("NFKD", texto).encode("ASCII", "ignore").decode("ASCII")
    s = s.lower()
    for c in string.punctuation:
        s = s.replace(c, " ")
    return " ".join(s.split())


def extrair_nome_condominio_do_edital(filename: str) -> str:
    """Tenta extrair o nome do condomínio do nome do arquivo .docx."""
    base = os.path.splitext(os.path.basename(filename))[0]
    m = RE_DATA_NOME.match(base)
    if m:
        return m.group(4).strip()
    return base.strip()


def extrair_data_do_edital(filename: str) -> Optional[date]:
    base = os.path.splitext(os.path.basename(filename))[0]
    m = RE_DATA_NOME.match(base)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except (ValueError, TypeError):
        return None


class AtaMatcher:
    """Matcher áudio ↔ edital."""

    TOLERANCIA_DIAS = 1
    CHARS_BUSCA_TRANSCRIPT = 5000

    def __init__(self, plaud_client):
        self.plaud = plaud_client
        self._transcript_cache: dict[str, str] = {}
        self._pares_usados: set[str] = set()

    def marcar_par_usado(self, file_id: str) -> None:
        self._pares_usados.add(file_id)

    def _filtrar_por_data(self, edital_path: str, candidatos: list[dict]) -> list[dict]:
        data_edital = extrair_data_do_edital(edital_path)
        if data_edital is None:
            return list(candidatos)
        resultado = []
        for c in candidatos:
            try:
                d = datetime.strptime(c["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            if abs((d - data_edital).days) <= self.TOLERANCIA_DIAS:
                resultado.append(c)
        return resultado

    def _filtrar_por_titulo(self, nome_condominio: str, candidatos: list[dict]) -> list[dict]:
        alvo = normalizar_para_busca(nome_condominio)
        if not alvo:
            return list(candidatos)
        return [c for c in candidatos if alvo in normalizar_para_busca(c.get("name", ""))]

    def _filtrar_por_transcript(self, nome_condominio: str, candidatos: list[dict]) -> list[dict]:
        alvo = normalizar_para_busca(nome_condominio)
        if not alvo:
            return list(candidatos)
        casados = []
        for c in candidatos:
            fid = c["id"]
            if fid not in self._transcript_cache:
                try:
                    self._transcript_cache[fid] = self.plaud.get_transcript(fid)
                except Exception as e:
                    logger.warning("[MATCHER] falha ao baixar transcript de %s: %s", fid, e)
                    self._transcript_cache[fid] = ""
            trecho = self._transcript_cache[fid][: self.CHARS_BUSCA_TRANSCRIPT]
            if alvo in normalizar_para_busca(trecho):
                casados.append(c)
        return casados

    def match(self, edital_path: str, candidatos: list[dict]) -> Optional[dict]:
        nome = extrair_nome_condominio_do_edital(edital_path)
        logger.info("[MATCHER] '%s' → nome='%s', %d candidato(s)",
                    os.path.basename(edital_path), nome, len(candidatos))

        # Nível 1: data
        por_data = self._filtrar_por_data(edital_path, candidatos)
        if not por_data:
            logger.warning("[MATCHER] nenhum candidato na data → None")
            return None
        if len(por_data) == 1:
            return por_data[0]

        # Nível 2: título
        por_titulo = self._filtrar_por_titulo(nome, por_data)
        if len(por_titulo) == 1:
            return por_titulo[0]
        base = por_titulo if por_titulo else por_data

        # Nível 3: transcript
        if len(base) > 1:
            por_transcript = self._filtrar_por_transcript(nome, base)
            if len(por_transcript) == 1:
                return por_transcript[0]
            if por_transcript:
                base = por_transcript

        # Nível 4: eliminação por pares já usados
        livres = [c for c in base if c["id"] not in self._pares_usados]
        if len(livres) == 1:
            return livres[0]
        if livres:
            logger.warning("[MATCHER] %d candidato(s) ambíguo(s), fallback no primeiro: %s",
                           len(livres), livres[0].get("name"))
            return livres[0]

        logger.warning("[MATCHER] sem candidato livre, fallback no primeiro candidato: %s",
                       base[0].get("name") if base else "(vazio)")
        return base[0] if base else None
```

- [ ] **Step 4: Rodar — devem passar**

```
pytest tests/test_ata_matcher.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```
git add src/ata_matcher.py tests/test_ata_matcher.py
git commit -m "feat(matcher): AtaMatcher 4 níveis (data → título → transcript → eliminação)"
```

---

## Task 4: Backup do pipeline atual

**Files:**
- Create: `pipeline_legacy.py` (cópia do `pipeline.py` atual)

- [ ] **Step 1: Backup**

```
cp pipeline.py pipeline_legacy.py
```

- [ ] **Step 2: Commit**

```
git add pipeline_legacy.py
git commit -m "chore: backup do pipeline.py Selenium como pipeline_legacy.py"
```

---

## Task 5: Novo `pipeline.py` (orquestrador)

**Files:**
- Modify: `pipeline.py` (substituição total)

- [ ] **Step 1: Substituir conteúdo de `pipeline.py`**

```python
"""Pipeline Plaud — versão CLI (Fase 2).

Substitui as etapas Selenium por PlaudClient.
Processa todos os editais pendentes da pasta SMB por execução.
Mantém VPN/SMB/IA/e-mail intactos.

Uso:
    python3 pipeline.py              # execução completa
    python3 pipeline.py --test       # smoke test (sem chamadas a IA)
    python3 pipeline.py --no-email   # gera ATAs mas não envia
    python3 pipeline.py --no-vpn     # pula VPN (uso local apenas)
"""

import argparse
import logging
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.plaud_client import PlaudClient
from src.ata_matcher import AtaMatcher
from src.ata_verifier import AtaVerifier
from src.processados_tracker import ProcessadosTracker
from src.edital_scanner import EditalScanner
from src.edital_reader import EditalReader, validar_extracao
from src.ia_processor import IAProcessor
from src.email_sender import EmailSender

IS_LINUX = platform.system() == "Linux"
if IS_LINUX:
    from src.vpn_manager import VPNManager, SMBManager

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _montar_corpo_extra(validacao: dict, omissoes: dict) -> str:
    blocos = []
    if not validacao.get("ok", True):
        itens = "".join(f"<li>{a}</li>" for a in validacao.get("alertas", []))
        blocos.append(
            f'<div style="border-left:4px solid #d97706;background:#fef3c7;padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Alerta de extração do edital</b><ul>{itens}</ul></div>'
        )
    if omissoes.get("tem_omissoes"):
        rel = omissoes["relatorio"].replace("\n", "<br>")
        blocos.append(
            f'<div style="border-left:4px solid #dc2626;background:#fee2e2;padding:10px 14px;margin:14px 0;">'
            f'<b>⚠️ Possíveis omissões detectadas</b>'
            f'<p style="font-family:monospace;font-size:0.9em;white-space:pre-wrap">{rel}</p></div>'
        )
    return "".join(blocos)


def _processar_um(edital_path: str, audio: dict, plaud: PlaudClient,
                  ia: IAProcessor, verifier: AtaVerifier,
                  email_sender: EmailSender, tracker: ProcessadosTracker,
                  enviar_email: bool) -> dict:
    """Processa um par (edital, áudio). Retorna dict do resultado."""
    res = {"edital": os.path.basename(edital_path), "audio": audio.get("name"), "ok": False, "erro": None}

    # Carrega edital
    reader = EditalReader(caminho_arquivo=edital_path)
    r = reader.carregar()
    if not r["sucesso"]:
        raise RuntimeError(f"falha ao carregar edital: {r['mensagem']}")
    reader.extrair_pontos()
    validacao = validar_extracao(reader)
    edital_texto = reader.obter_texto_formatado()

    # Disponibilidade do áudio
    meta = plaud.get_file_meta(audio["id"])
    if meta.get("transcript") != "available":
        raise RuntimeError(f"transcript não disponível ainda ({meta.get('transcript')})")

    # Download
    transcript = plaud.get_transcript(audio["id"])
    summary = plaud.get_summary(audio["id"]) if meta.get("summary") == "available" else ""

    # IA
    resultado = ia.processar(transcript=transcript, summary=summary, edital=edital_texto)
    if not resultado["sucesso"]:
        raise RuntimeError(f"IA falhou: {resultado['mensagem']}")
    ata = resultado["ata"]

    # Verificação de omissões
    omissoes = verifier.verificar(ata=ata, transcript=transcript)

    # Salva .md em saida/
    saida_dir = Path(os.path.dirname(os.path.abspath(__file__))) / "saida"
    saida_dir.mkdir(exist_ok=True)
    nome_condo = os.path.splitext(os.path.basename(edital_path))[0]
    nome_condo_safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in nome_condo)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = saida_dir / f"{nome_condo_safe}_{timestamp}.md"
    out_md.write_text(ata, encoding="utf-8")
    logger.info("[OK] ATA .md salva em %s", out_md)

    # Word + e-mail
    nome_docx = f"ATA_{nome_condo_safe}_{timestamp}.docx"
    corpo_extra = _montar_corpo_extra(validacao, omissoes)
    email_marcado = False
    if enviar_email:
        assunto = f"[ATA] {nome_condo} - {datetime.now().strftime('%d/%m/%Y')}"
        if not validacao.get("ok", True):
            assunto = "⚠️ " + assunto + " (edital fora do padrão)"
        if omissoes.get("tem_omissoes"):
            assunto = "⚠️ " + assunto + " (possíveis omissões)"
        r_email = email_sender.enviar(assunto=assunto, conteudo=ata, nome_arquivo=nome_docx, corpo_extra=corpo_extra)
        if r_email["sucesso"]:
            logger.info("[OK] E-mail enviado: %s", r_email["mensagem"])
            email_marcado = True
        else:
            logger.warning("[AVISO] E-mail falhou (mas ATA já existe em disco): %s", r_email["mensagem"])
            email_marcado = True  # ATA gerada, marca mesmo assim
    else:
        # Gera Word local sem enviar
        tmp = email_sender._gerar_word(ata, nome_docx)
        destino = saida_dir / nome_docx
        Path(tmp).replace(destino)
        logger.info("[OK] Word local: %s", destino)
        email_marcado = True

    # Marca como processado (somente após sucesso da IA + tentativa de e-mail)
    if email_marcado:
        tracker.marcar_processado(edital_path, audio["id"], str(out_md))

    res.update({"ok": True, "ata_chars": len(ata), "audio_id": audio["id"],
                "validacao_ok": validacao.get("ok"), "tem_omissoes": omissoes.get("tem_omissoes")})
    return res


def executar_pipeline(usar_vpn: bool = True, enviar_email: bool = True,
                       max_editais: int = None, modo_teste: bool = False) -> int:
    vpn_manager = None
    smb_manager = None
    relatorio = {"sucessos": [], "falhas": [], "ignorados": []}

    try:
        logger.info("=" * 70)
        logger.info("PIPELINE PLAUD CLI - Fase 2")
        logger.info(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        logger.info("=" * 70)

        # ETAPA 0
        logger.info("\n[ETAPA 0] Validando credenciais e auth Plaud...")
        Config.validar_credenciais()
        plaud = PlaudClient()
        if not plaud.verify_auth():
            logger.error("[CRÍTICO] Plaud CLI sem auth válida. Rode `plaud login` na VPS.")
            _alertar_reauth()
            return 2

        if modo_teste:
            logger.info("[TESTE] Smoke test passou. Saindo.")
            return 0

        # ETAPA 1 — VPN
        if IS_LINUX and usar_vpn:
            logger.info("\n[ETAPA 1] Conectando VPN...")
            vpn_manager = VPNManager()
            r = vpn_manager.conectar(timeout=60)
            if not r["sucesso"]:
                logger.error("[ERRO] VPN: %s", r["mensagem"])
                return 3
        else:
            logger.info("\n[ETAPA 1] VPN: ignorada")

        # ETAPA 2 — SMB
        caminho_editais = None
        if IS_LINUX:
            logger.info("\n[ETAPA 2] Montando SMB...")
            smb_manager = SMBManager(
                servidor="10.0.0.10",
                compartilhamento="Arquivos",
                usuario=os.environ.get("SMB_USUARIO", "svc_automacao"),
                senha=os.environ.get("SMB_SENHA", ""),
                ponto_montagem="/mnt/cliente",
            )
            r = smb_manager.montar()
            if not r["sucesso"]:
                logger.error("[ERRO] SMB: %s", r["mensagem"])
                return 4
            from pipeline_legacy import encontrar_pasta_editais
            caminho_editais = encontrar_pasta_editais(r["caminho"], max_depth=3)
            if not caminho_editais:
                logger.error("[ERRO] Pasta 'Editais' não encontrada no SMB")
                return 5
        else:
            # Modo dev/local
            caminho_editais = os.environ.get("CAMINHO_EDITAIS_LOCAL", "./editais_local")

        # ETAPA 3 — Pendentes
        logger.info("\n[ETAPA 3] Listando editais pendentes em %s ...", caminho_editais)
        tracker_path = os.environ.get("PROCESSADOS_JSON_PATH", "/opt/plaud/processados.json")
        if not IS_LINUX:
            tracker_path = os.environ.get("PROCESSADOS_JSON_PATH", "./processados.json")
        tracker = ProcessadosTracker(caminho=tracker_path)
        scanner = EditalScanner(caminho_editais, tracker)
        limite = max_editais or int(os.environ.get("MAX_EDITAIS_POR_RUN", "10"))
        pendentes = scanner.listar_pendentes(limite=limite)
        logger.info("[OK] %d edital(is) pendente(s)", len(pendentes))
        if not pendentes:
            logger.info("Nada a processar.")
            return 0

        # ETAPA 4 — Áudios candidatos
        logger.info("\n[ETAPA 4] Listando áudios Plaud (últimos 14 dias)...")
        hoje = datetime.now().date()
        candidatos = plaud.list_by_date_range(
            date_from=(hoje - timedelta(days=14)).strftime("%Y-%m-%d"),
            date_to=(hoje + timedelta(days=1)).strftime("%Y-%m-%d"),
            page_size=100,
        )
        logger.info("[OK] %d áudio(s) candidato(s)", len(candidatos))

        # ETAPA 5 — Loop de processamento
        logger.info("\n[ETAPA 5] Processando %d edital(is)...", len(pendentes))
        matcher = AtaMatcher(plaud)
        ia = IAProcessor()
        verifier = AtaVerifier()
        email_sender = EmailSender()

        for edital_path in pendentes:
            nome_curto = os.path.basename(edital_path)
            logger.info("\n----- %s -----", nome_curto)
            try:
                audio = matcher.match(edital_path, candidatos)
                if not audio:
                    logger.warning("[SKIP] sem áudio correspondente")
                    relatorio["ignorados"].append({"edital": nome_curto, "motivo": "sem audio"})
                    continue
                resultado = _processar_um(edital_path, audio, plaud, ia, verifier,
                                          email_sender, tracker, enviar_email)
                matcher.marcar_par_usado(audio["id"])
                relatorio["sucessos"].append(resultado)
            except Exception as e:
                logger.error("[FALHA] %s: %s", nome_curto, e)
                logger.debug(traceback.format_exc())
                relatorio["falhas"].append({"edital": nome_curto, "erro": str(e)})

        # Relatório final
        logger.info("\n" + "=" * 70)
        logger.info("RESUMO: %d sucesso(s), %d falha(s), %d ignorado(s)",
                    len(relatorio["sucessos"]), len(relatorio["falhas"]), len(relatorio["ignorados"]))

        if relatorio["falhas"]:
            _email_resumo_falhas(relatorio, email_sender)

        return 0 if not relatorio["falhas"] else 1

    finally:
        if IS_LINUX:
            if smb_manager:
                try: smb_manager.desmontar()
                except Exception: pass
            if vpn_manager:
                try: vpn_manager.desconectar()
                except Exception: pass


def _alertar_reauth():
    try:
        EmailSender().enviar(
            assunto="[REAUTH NECESSÁRIO] Plaud CLI",
            conteudo="Token expirado. SSH na VPS + `plaud login`.",
            nome_arquivo="reauth.docx",
        )
    except Exception as e:
        logger.warning("Falha ao enviar e-mail de reauth: %s", e)


def _email_resumo_falhas(relatorio: dict, email_sender: EmailSender):
    linhas = ["# Relatório de execução\n"]
    for s in relatorio["sucessos"]:
        linhas.append(f"✓ {s['edital']} → {s.get('audio_id')}")
    for f in relatorio["falhas"]:
        linhas.append(f"✗ {f['edital']}: {f['erro']}")
    for i in relatorio["ignorados"]:
        linhas.append(f"- {i['edital']}: {i['motivo']}")
    try:
        email_sender.enviar(
            assunto=f"[RESUMO PIPELINE] {datetime.now().strftime('%d/%m/%Y')} - {len(relatorio['falhas'])} falha(s)",
            conteudo="\n\n".join(linhas),
            nome_arquivo="resumo.docx",
        )
    except Exception as e:
        logger.warning("Falha ao enviar resumo: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Pipeline Plaud CLI (Fase 2)")
    parser.add_argument("--no-vpn", action="store_true")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--test", action="store_true", help="Smoke test (sem chamadas IA)")
    parser.add_argument("--max", type=int, default=None, help="Máximo de editais por execução")
    args = parser.parse_args()

    sys.exit(executar_pipeline(
        usar_vpn=not args.no_vpn,
        enviar_email=not args.no_email,
        max_editais=args.max,
        modo_teste=args.test,
    ))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test de import**

```
python -c "import pipeline; print('import OK')"
```
Expected: `import OK`.

- [ ] **Step 3: Rodar suíte completa**

```
pytest tests/ -v
```
Expected: todos os testes anteriores + 3 novos arquivos passam (~60+ testes).

- [ ] **Step 4: Commit**

```
git add pipeline.py
git commit -m "feat(pipeline): novo orquestrador CLI Plaud com multi-edital + matching + tracker"
```

---

## Task 6: Smoke test local + ajustes finais

**Files:** nenhum (validação manual).

- [ ] **Step 1: Rodar `--test` local**

```
python pipeline.py --test
```
Expected: passa pela ETAPA 0 (auth Plaud) e sai com exit 0.

- [ ] **Step 2: Rodar contra `editais_local/lote_cliente/` (sem VPN, sem e-mail)**

```
set CAMINHO_EDITAIS_LOCAL=editais_local/lote_cliente
set PROCESSADOS_JSON_PATH=./processados_local.json
python pipeline.py --no-vpn --no-email --max 1
```

Expected: lista 1 edital pendente, faz matching com áudio Plaud, gera ATA em `saida/`, marca no `processados_local.json`.

- [ ] **Step 3: Validar idempotência**

Rodar de novo:
```
python pipeline.py --no-vpn --no-email --max 1
```

Expected: `0 edital(is) pendente(s)`. O tracker filtrou.

- [ ] **Step 4: Limpeza dos artefatos locais (opcional antes de prod)**

```
del processados_local.json
rmdir /s /q saida
```

- [ ] **Step 5: Commit final do plano executado**

```
git status
# se houver mudanças não commitadas (logs, etc.), .gitignore deve cobrir
git log --oneline -10
```

---

## Self-review

- **Spec coverage:**
  - Task 1 → `ProcessadosTracker` (Seção Componentes do spec) ✓
  - Task 2 → `EditalScanner` ✓
  - Task 3 → `AtaMatcher` 4 níveis ✓
  - Task 4 → backup `pipeline_legacy.py` (rollback rápido) ✓
  - Task 5 → novo `pipeline.py` com ETAPAS 0-6 ✓
  - Task 6 → smoke test (critério de sucesso do spec) ✓
  - Deploy via Termius / OAuth na VPS: NÃO está no plano de IMPLEMENTAÇÃO — é deploy operacional, executado pelo Carlos depois com base na Seção 5 do spec.

- **Placeholders:** nenhum TBD/TODO/"similar to". Código completo em cada step.

- **Type consistency:**
  - `ProcessadosTracker.ja_processado(edital_path: str) -> bool` consistente entre Tasks 1, 2 e 5.
  - `EditalScanner.listar_pendentes(limite: Optional[int]) -> list[str]` consistente entre Tasks 2 e 5.
  - `AtaMatcher.match(edital_path: str, candidatos: list[dict]) -> Optional[dict]` consistente entre Tasks 3 e 5.
  - `AtaMatcher.marcar_par_usado(file_id: str)` chamado em Task 5 — definido na Task 3 ✓.

