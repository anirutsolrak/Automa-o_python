# POC Migração CLI Plaud — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validar end-to-end que a migração do Selenium para o CLI oficial do Plaud entrega uma ATA equivalente ou superior, usando o áudio Alfa 3h (file_id `00000000000000000000000000000000`) como caso de teste.

**Architecture:** Wrapper Python (`PlaudClient`) que encapsula chamadas `subprocess` ao CLI Plaud, com parsers regex para os 3 formatos de output (tabela do `plaud files`, `key: value` do `plaud file`, e texto puro de `plaud transcript`/`summary`). Pipeline existente fica intocado; apenas o `IAProcessor` recebe ajuste de truncamento (20k→200k chars) e env var pra forçar modelo. Script `poc_cli_local.py` na raiz roda o fluxo end-to-end com edital lido de pasta local.

**Tech Stack:** Python 3.x, pytest, subprocess, `@plaud-ai/cli` (Node.js), o3 (OpenAI via SDK `openai>=1.40`), `python-docx` (já em uso).

---

## File Structure

**Criar:**
- `src/plaud_client.py` — Wrapper Python sobre o CLI Plaud
- `tests/__init__.py` — Marca `tests/` como pacote (arquivo vazio)
- `tests/test_plaud_client.py` — Testes unitários do wrapper (subprocess mockado)
- `tests/test_ia_processor_truncation.py` — Teste do ajuste de truncamento
- `poc_cli_local.py` — Script POC end-to-end na raiz do projeto

**Modificar:**
- `src/ia_processor.py` — Aumentar truncamento (linhas 386-388) e adicionar env var `PLAUD_IA_MODELO`
- `requirements.txt` — Adicionar `pytest` se ausente

---

## Task 1: Criar branch POC e estrutura de testes

**Files:**
- Create: `tests/__init__.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Criar branch a partir da branch atual**

Run:
```powershell
git checkout -b poc/migracao-cli
git branch --show-current
```
Expected: `poc/migracao-cli`

- [ ] **Step 2: Criar pasta `tests/` com `__init__.py` vazio**

Write `tests/__init__.py` com conteúdo vazio (0 bytes — só marca como pacote Python).

- [ ] **Step 3: Verificar e atualizar `requirements.txt`**

Read `requirements.txt`. Se não tiver `pytest`, anexar a linha:
```
pytest>=8.0
```

- [ ] **Step 4: Instalar pytest e rodar smoke test**

Run:
```powershell
pip install pytest
pytest --version
```
Expected: `pytest 8.x.x`

- [ ] **Step 5: Commit**

```powershell
git add tests/__init__.py requirements.txt
git commit -m "chore: setup tests/ folder e adiciona pytest para o POC"
```

---

## Task 2: `PlaudClient` skeleton + exceção customizada

**Files:**
- Create: `src/plaud_client.py`
- Create: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever teste do skeleton**

Create `tests/test_plaud_client.py` com:
```python
"""Testes do PlaudClient (subprocess mockado)."""

import pytest
from src.plaud_client import PlaudClient, PlaudCLIError


def test_plaud_client_initializes_with_default_cli_path():
    client = PlaudClient()
    assert client.cli_path == "plaud"


def test_plaud_client_accepts_custom_cli_path():
    client = PlaudClient(cli_path="C:/tools/plaud.exe")
    assert client.cli_path == "C:/tools/plaud.exe"


def test_plaud_cli_error_carries_returncode_and_stderr():
    err = PlaudCLIError(returncode=2, stderr="auth failed")
    assert err.returncode == 2
    assert "auth failed" in str(err)
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.plaud_client'` ou `ImportError`.

- [ ] **Step 3: Implementar skeleton**

Create `src/plaud_client.py`:
```python
"""Wrapper Python sobre o CLI @plaud-ai/cli.

Encapsula chamadas subprocess ao CLI e faz parsing dos outputs
(tabela do `plaud files`, key:value do `plaud file`, texto puro de
`plaud transcript` e `plaud summary`).

Toda comunicação com o Plaud passa por esta classe.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class PlaudCLIError(Exception):
    """Levantada quando o CLI retorna exit != 0 fora dos casos toleráveis."""

    def __init__(self, returncode: int, stderr: str):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"plaud CLI exited {returncode}: {stderr.strip()}")


class PlaudClient:
    """Wrapper Python sobre o CLI @plaud-ai/cli."""

    def __init__(self, cli_path: str = "plaud"):
        self.cli_path = cli_path
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): skeleton da classe e exceção PlaudCLIError"
```

---

## Task 3: `verify_auth()` — checagem de token via `plaud me`

**Files:**
- Modify: `src/plaud_client.py`
- Modify: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever testes do verify_auth**

Append em `tests/test_plaud_client.py`:
```python
from unittest.mock import patch, MagicMock


def _mock_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_verify_auth_returns_true_on_exit_zero():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, "user@example.com")):
        assert client.verify_auth() is True


def test_verify_auth_returns_false_on_auth_error():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(2, "", "not logged in")):
        assert client.verify_auth() is False


def test_verify_auth_returns_false_on_any_nonzero_exit():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(3, "", "network error")):
        assert client.verify_auth() is False
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_plaud_client.py::test_verify_auth_returns_true_on_exit_zero -v
```
Expected: `AttributeError: 'PlaudClient' object has no attribute 'verify_auth'`.

- [ ] **Step 3: Implementar `verify_auth()` e helper `_run()`**

Append no fim de `src/plaud_client.py` (dentro da classe `PlaudClient`):
```python
    def _run(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        """Executa `plaud <args>` capturando stdout/stderr em UTF-8."""
        cmd = [self.cli_path] + args
        logger.debug("plaud cmd: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def verify_auth(self) -> bool:
        """Retorna True se `plaud me` retornar exit 0."""
        try:
            result = self._run(["me"], timeout=15)
        except subprocess.TimeoutExpired:
            logger.warning("plaud me: timeout")
            return False
        return result.returncode == 0
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): verify_auth() via 'plaud me'"
```

---

## Task 4: `list_recent()` + parser da tabela de arquivos

**Files:**
- Modify: `src/plaud_client.py`
- Modify: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever testes do parser e do list_recent**

Append em `tests/test_plaud_client.py`:
```python
SAMPLE_FILES_OUTPUT = """
Files on this page: 10

  ID                                  NAME                                  DATE          DURATION
  ──────────────────────────────────────────────────────────────────────────────────────────────────
  00000000000000000000000000000000    13.05.2026 Alfa                    2026-05-14    3h08m
  00000000000000000000000000000000    05.05.2026 Beta            2026-05-06    8m51s
  00000000000000000000000000000000    29.04.2026 Alice Quintela             2026-05-05    1h13m

Page 1
"""


def test_parse_files_table_extracts_id_name_date_duration():
    rows = PlaudClient._parse_files_table(SAMPLE_FILES_OUTPUT)
    assert len(rows) == 3
    assert rows[0]["id"] == "00000000000000000000000000000000"
    assert rows[0]["name"] == "13.05.2026 Alfa"
    assert rows[0]["date"] == "2026-05-14"
    assert rows[0]["duration_seconds"] == 3 * 3600 + 8 * 60


def test_parse_duration_handles_three_formats():
    assert PlaudClient._parse_duration("3h08m") == 3 * 3600 + 8 * 60
    assert PlaudClient._parse_duration("8m51s") == 8 * 60 + 51
    assert PlaudClient._parse_duration("45s") == 45


def test_list_recent_calls_cli_with_correct_args_and_parses():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_FILES_OUTPUT)) as m:
        rows = client.list_recent(days=7, page_size=50)
        m.assert_called_once()
        args = m.call_args[0][0]
        assert "recent" in args
        assert "--days" in args and "7" in args
        assert "--page-size" in args and "50" in args
    assert len(rows) == 3
    assert rows[1]["name"] == "05.05.2026 Beta"
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_plaud_client.py::test_parse_files_table_extracts_id_name_date_duration -v
```
Expected: `AttributeError: type object 'PlaudClient' has no attribute '_parse_files_table'`.

- [ ] **Step 3: Implementar parser e método**

Adicionar imports no topo de `src/plaud_client.py`:
```python
import re
```

Append na classe `PlaudClient` em `src/plaud_client.py`:
```python
    _ROW_RE = re.compile(r"^\s+([a-f0-9]{32})\s{2,}(.+?)\s{2,}(\d{4}-\d{2}-\d{2})\s{2,}(\S+)\s*$")
    _DURATION_HMS = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")

    @classmethod
    def _parse_duration(cls, raw: str) -> int:
        m = cls._DURATION_HMS.match(raw.strip())
        if not m:
            return 0
        h, mn, s = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mn * 60 + s

    @classmethod
    def _parse_files_table(cls, output: str) -> list[dict]:
        rows = []
        for line in output.splitlines():
            m = cls._ROW_RE.match(line)
            if not m:
                continue
            file_id, name, date, duration = m.groups()
            rows.append({
                "id": file_id,
                "name": name.strip(),
                "date": date,
                "duration_seconds": cls._parse_duration(duration),
            })
        return rows

    def list_recent(self, days: int = 7, page_size: int = 50) -> list[dict]:
        """Lista gravações dos últimos N dias via `plaud recent`."""
        result = self._run(["recent", "--days", str(days), "--page-size", str(page_size)])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return self._parse_files_table(result.stdout)
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 9 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): list_recent() e parser da tabela 'plaud files'"
```

---

## Task 5: `list_by_date_range()` — filtro server-side por data

**Files:**
- Modify: `src/plaud_client.py`
- Modify: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever teste**

Append em `tests/test_plaud_client.py`:
```python
def test_list_by_date_range_passes_from_and_to_flags():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_FILES_OUTPUT)) as m:
        rows = client.list_by_date_range("2026-05-01", "2026-05-19")
        args = m.call_args[0][0]
        assert "files" in args
        assert "--from" in args and "2026-05-01" in args
        assert "--to" in args and "2026-05-19" in args
    assert len(rows) == 3
```

- [ ] **Step 2: Rodar teste — deve falhar**

Run:
```powershell
pytest tests/test_plaud_client.py::test_list_by_date_range_passes_from_and_to_flags -v
```
Expected: `AttributeError: 'PlaudClient' object has no attribute 'list_by_date_range'`.

- [ ] **Step 3: Implementar método**

Append na classe `PlaudClient`:
```python
    def list_by_date_range(self, date_from: str, date_to: str, page_size: int = 100) -> list[dict]:
        """Lista gravações em intervalo de datas via `plaud files --from --to`."""
        result = self._run([
            "files",
            "--from", date_from,
            "--to", date_to,
            "--page-size", str(page_size),
        ])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return self._parse_files_table(result.stdout)
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): list_by_date_range() com filtro server-side"
```

---

## Task 6: `get_file_meta()` + parser key:value

**Files:**
- Modify: `src/plaud_client.py`
- Modify: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever testes**

Append em `tests/test_plaud_client.py`:
```python
SAMPLE_FILE_OUTPUT = """
File Details:

  id:           00000000000000000000000000000000
  name:         05.05.2026 Beta
  created_at:   2026-05-06T13:49:48
  start_at:     2026-05-05T22:04:02
  duration:     8m51s
  serial_number: 888316753912013887
  audio:        available
  transcript:   available
  summary:      available
"""


def test_parse_file_details_extracts_all_keys():
    meta = PlaudClient._parse_file_details(SAMPLE_FILE_OUTPUT)
    assert meta["id"] == "00000000000000000000000000000000"
    assert meta["name"] == "05.05.2026 Beta"
    assert meta["duration"] == "8m51s"
    assert meta["audio"] == "available"
    assert meta["transcript"] == "available"
    assert meta["summary"] == "available"


def test_get_file_meta_calls_cli_and_parses():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_FILE_OUTPUT)) as m:
        meta = client.get_file_meta("00000000000000000000000000000000")
        args = m.call_args[0][0]
        assert args[-2:] == ["file", "00000000000000000000000000000000"]
    assert meta["transcript"] == "available"
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_plaud_client.py::test_parse_file_details_extracts_all_keys -v
```
Expected: `AttributeError: type object 'PlaudClient' has no attribute '_parse_file_details'`.

- [ ] **Step 3: Implementar parser e método**

Append na classe `PlaudClient`:
```python
    _KV_RE = re.compile(r"^\s+(\w+):\s+(.+?)\s*$")

    @classmethod
    def _parse_file_details(cls, output: str) -> dict:
        meta = {}
        for line in output.splitlines():
            m = cls._KV_RE.match(line)
            if m:
                meta[m.group(1)] = m.group(2)
        return meta

    def get_file_meta(self, file_id: str) -> dict:
        """Retorna metadata + flags de disponibilidade (audio/transcript/summary)."""
        result = self._run(["file", file_id])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return self._parse_file_details(result.stdout)
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 12 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): get_file_meta() + parser key:value"
```

---

## Task 7: `get_transcript()` e `get_summary()`

**Files:**
- Modify: `src/plaud_client.py`
- Modify: `tests/test_plaud_client.py`

- [ ] **Step 1: Escrever testes**

Append em `tests/test_plaud_client.py`:
```python
SAMPLE_TRANSCRIPT = """Transcript: 05.05.2026 Beta

[00:00 - 00:01] Speaker 1: Eu falei o que você ia dizer, você está aí?
[00:06 - 00:12] Speaker 1: Aí você coloca o quadro.
"""

SAMPLE_SUMMARY = """Summary: 05.05.2026 Beta

## Contexto e abertura
A conversa começou de modo informal...
"""


def test_get_transcript_returns_raw_stdout():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_TRANSCRIPT)) as m:
        tr = client.get_transcript("xyz")
        args = m.call_args[0][0]
        assert args[-2:] == ["transcript", "xyz"]
    assert "[00:00 - 00:01] Speaker 1:" in tr
    assert tr.startswith("Transcript:")


def test_get_summary_returns_raw_stdout():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_SUMMARY)) as m:
        sm = client.get_summary("xyz")
        args = m.call_args[0][0]
        assert args[-2:] == ["summary", "xyz"]
    assert sm.startswith("Summary:")
    assert "## Contexto" in sm


def test_get_transcript_raises_on_cli_error():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(1, "", "file not found")):
        with pytest.raises(PlaudCLIError) as exc:
            client.get_transcript("missing")
        assert exc.value.returncode == 1
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_plaud_client.py::test_get_transcript_returns_raw_stdout -v
```
Expected: `AttributeError: 'PlaudClient' object has no attribute 'get_transcript'`.

- [ ] **Step 3: Implementar métodos**

Append na classe `PlaudClient`:
```python
    def get_transcript(self, file_id: str, timeout: int = 120) -> str:
        """Retorna o transcript completo (texto bruto) de uma gravação."""
        result = self._run(["transcript", file_id], timeout=timeout)
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return result.stdout

    def get_summary(self, file_id: str, timeout: int = 60) -> str:
        """Retorna o summary (markdown bruto) gerado pela IA do Plaud."""
        result = self._run(["summary", file_id], timeout=timeout)
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return result.stdout
```

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_plaud_client.py -v
```
Expected: 15 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/plaud_client.py tests/test_plaud_client.py
git commit -m "feat(plaud_client): get_transcript() e get_summary()"
```

---

## Task 8: Ajustes no `IAProcessor` — truncamento + env var de modelo

**Files:**
- Modify: `src/ia_processor.py`
- Create: `tests/test_ia_processor_truncation.py`

- [ ] **Step 1: Escrever teste do novo comportamento de truncamento**

Create `tests/test_ia_processor_truncation.py`:
```python
"""Testes do ajuste de truncamento e seleção de modelo no IAProcessor."""

import os
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PLAUD_IA_MODELO", raising=False)


def test_transcript_truncation_is_200k_chars(fake_env):
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    long_transcript = "x" * 250000  # 250k > novo limite de 200k
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as m:
        ia.processar(transcript=long_transcript, summary="", edital="edital simples")
        prompt_passado = m.call_args[0][0]
    # Confirma que NÃO truncou em 20000 (regressão do bug original)
    assert prompt_passado.count("x") > 20000
    # Confirma que truncou em 200000 (rede de segurança)
    assert prompt_passado.count("x") == 200000


def test_summary_truncation_is_30k_chars(fake_env):
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    long_summary = "y" * 50000
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as m:
        ia.processar(transcript="t", summary=long_summary, edital="edital")
        prompt_passado = m.call_args[0][0]
    assert prompt_passado.count("y") == 30000


def test_env_var_forces_o3_skipping_gemini(fake_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("PLAUD_IA_MODELO", "o3")
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as gpt_mock, \
         patch.object(ia, "_processar_com_gemini") as gemini_mock:
        ia.processar(transcript="t", summary="s", edital="e")
    gpt_mock.assert_called_once()
    gemini_mock.assert_not_called()
```

- [ ] **Step 2: Rodar testes — devem falhar**

Run:
```powershell
pytest tests/test_ia_processor_truncation.py -v
```
Expected: 2 falham (truncation tests) e 1 falha (env var não tem efeito).

- [ ] **Step 3: Ajustar truncamento e adicionar env var**

Read [src/ia_processor.py](src/ia_processor.py) nas linhas 382-416 para entender contexto.

Substituir o bloco em `IAProcessor.processar()` (próximo às linhas 382-408):

OLD:
```python
        # Escolher prompt
        if edital:
            prompt = self.PROMPT_COM_EDITAL.format(
                edital=edital[:8000],
                transcricao=transcript[:20000],
                resumo=summary[:8000]
            )
        else:
            logger.warning("Edital não fornecido - usando prompt simples")
            prompt = self.PROMPT_SEM_EDITAL.format(
                transcricao=transcript[:20000],
                resumo=summary[:8000]
            )

        # Tentar Gemini primeiro
        if self.gemini_disponivel:
            resultado = self._processar_com_gemini(prompt)
            if resultado['sucesso']:
                return resultado
            logger.warning("Gemini falhou, tentando GPT...")
        else:
            logger.info("Gemini não configurado, pulando...")

        # Fallback para GPT
        if self.gpt_disponivel:
            logger.info("Tentando processar com GPT...")
            return self._processar_com_gpt(prompt)
```

NEW:
```python
        # Limites de truncamento (subidos para suportar áudios longos via CLI Plaud).
        # transcript: 200k chars cobre ~10h de fala; rede de segurança contra estourar contexto o3 (200k tokens).
        # summary: 30k chars cobre summaries densos de reuniões longas.
        # edital: 8k mantido (editais raramente passam disso).
        MAX_TRANSCRIPT = 200_000
        MAX_SUMMARY = 30_000
        MAX_EDITAL = 8_000

        if edital:
            prompt = self.PROMPT_COM_EDITAL.format(
                edital=edital[:MAX_EDITAL],
                transcricao=transcript[:MAX_TRANSCRIPT],
                resumo=summary[:MAX_SUMMARY]
            )
        else:
            logger.warning("Edital não fornecido - usando prompt simples")
            prompt = self.PROMPT_SEM_EDITAL.format(
                transcricao=transcript[:MAX_TRANSCRIPT],
                resumo=summary[:MAX_SUMMARY]
            )

        # PLAUD_IA_MODELO=o3 força GPT direto (pula Gemini). Útil no POC.
        modelo_forcado = os.environ.get("PLAUD_IA_MODELO", "").lower()

        if modelo_forcado != "o3" and self.gemini_disponivel:
            resultado = self._processar_com_gemini(prompt)
            if resultado['sucesso']:
                return resultado
            logger.warning("Gemini falhou, tentando GPT...")
        elif modelo_forcado == "o3":
            logger.info("PLAUD_IA_MODELO=o3 — pulando Gemini, indo direto pro GPT")
        else:
            logger.info("Gemini não configurado, pulando...")

        if self.gpt_disponivel:
            logger.info("Tentando processar com GPT...")
            return self._processar_com_gpt(prompt)
```

Adicionar `import os` no topo de `src/ia_processor.py` se ainda não estiver presente.

- [ ] **Step 4: Rodar testes — devem passar**

Run:
```powershell
pytest tests/test_ia_processor_truncation.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Rodar suíte inteira — não pode regredir**

Run:
```powershell
pytest tests/ -v
```
Expected: 18 passed (15 do PlaudClient + 3 novos).

- [ ] **Step 6: Commit**

```powershell
git add src/ia_processor.py tests/test_ia_processor_truncation.py
git commit -m "feat(ia_processor): truncamento 200k chars + env var PLAUD_IA_MODELO"
```

---

## Task 9: Script `poc_cli_local.py` — orquestração end-to-end

**Files:**
- Create: `poc_cli_local.py`

- [ ] **Step 1: Escrever script POC**

Create `poc_cli_local.py`:
```python
"""POC: roda o pipeline Plaud usando CLI oficial + edital local.

Não toca em VPN, SMB, e-mail nem Selenium. Salva ATA em output/.
Roda contra áudio Alfa 3h (file_id hardcoded) e edital em editais_local/.
"""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=".env", override=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config import Config
from src.plaud_client import PlaudClient, PlaudCLIError
from src.ia_processor import IAProcessor
from src.edital_reader import carregar_edital_da_pasta

# Áudio de validação — Alfa 13/05/2026 (3h08m)
ALFA_FILE_ID = "00000000000000000000000000000000"
EDITAIS_LOCAIS = "editais_local"
OUTPUT_DIR = "output"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("poc")


def main() -> int:
    logger.info("=== POC CLI Plaud — Alfa 3h ===")

    # 1. Validar config + auth Plaud
    Config.validar_credenciais()
    os.environ.setdefault("PLAUD_IA_MODELO", "o3")  # força o3 no POC

    plaud = PlaudClient()
    if not plaud.verify_auth():
        logger.error("Plaud CLI sem auth válida. Rode `plaud login` antes.")
        return 2

    # 2. Carregar edital local
    edital_reader = carregar_edital_da_pasta(EDITAIS_LOCAIS)
    if not edital_reader:
        logger.error("Nenhum edital .docx em %s", EDITAIS_LOCAIS)
        return 3
    edital_texto = edital_reader.obter_texto_formatado()
    logger.info("Edital carregado: %d chars", len(edital_texto))

    # 3. Confirmar disponibilidade do áudio
    meta = plaud.get_file_meta(ALFA_FILE_ID)
    logger.info("Áudio: %s | duração=%s | transcript=%s | summary=%s",
                meta.get("name"), meta.get("duration"),
                meta.get("transcript"), meta.get("summary"))
    if meta.get("transcript") != "available":
        logger.error("Transcript não disponível ainda.")
        return 4

    # 4. Baixar transcript + summary
    t0 = time.monotonic()
    transcript = plaud.get_transcript(ALFA_FILE_ID)
    summary = plaud.get_summary(ALFA_FILE_ID)
    dt_download = time.monotonic() - t0
    logger.info("Transcript: %d chars (%.1f min de fala est.)",
                len(transcript), len(transcript) / 1100)
    logger.info("Summary: %d chars", len(summary))
    logger.info("Download CLI: %.1fs", dt_download)

    # 5. Processar com IA (o3 forçado)
    ia = IAProcessor()
    t1 = time.monotonic()
    resultado = ia.processar(transcript=transcript, summary=summary, edital=edital_texto)
    dt_ia = time.monotonic() - t1

    if not resultado["sucesso"]:
        logger.error("IA falhou: %s", resultado["mensagem"])
        return 5

    ata = resultado["ata"]
    logger.info("ATA gerada: %d chars | modelo=%s | tempo=%.1fs",
                len(ata), resultado["modelo_usado"], dt_ia)

    # 6. Salvar saída
    Path(OUTPUT_DIR).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = Path(OUTPUT_DIR) / f"Alfa_{timestamp}.md"
    out_md.write_text(ata, encoding="utf-8")
    logger.info("ATA salva em: %s", out_md)

    logger.info("=== POC concluído com sucesso ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test de import (não roda IA ainda)**

Run:
```powershell
python -c "import poc_cli_local; print('import ok')"
```
Expected: `import ok` sem erro.

- [ ] **Step 3: Commit**

```powershell
git add poc_cli_local.py
git commit -m "feat(poc): script end-to-end Alfa 3h via CLI"
```

---

## Task 10: Rodar POC end-to-end e validar ATA

**Files:** nenhum (etapa de validação manual).

- [ ] **Step 1: Confirmar pré-requisitos**

Checar:
- `editais_local/Edital_Alfa.docx` existe
- `.env` tem `OPENAI_API_KEY` configurada
- `plaud me` retorna usuário autenticado (rode no shell se em dúvida)

- [ ] **Step 2: Rodar POC**

Run:
```powershell
python poc_cli_local.py
```
Expected (ordem de log esperada):
1. `=== POC CLI Plaud — Alfa 3h ===`
2. `Edital carregado: <N> chars`
3. `Áudio: 13.05.2026 Alfa | duração=3h08m | transcript=available | summary=available`
4. `Transcript: <N> chars (~180 min de fala est.)`
5. `Summary: <N> chars`
6. `Download CLI: <T>s`
7. `ATA gerada: <N> chars | modelo=o3 | tempo=<T>s`
8. `ATA salva em: output/Alfa_<timestamp>.md`
9. `=== POC concluído com sucesso ===`

Tempo total esperado: 1-4 minutos. Custo o3 esperado: ~US$ 0,10-0,20.

- [ ] **Step 3: Validar ATA gerada manualmente**

Abrir `output/Alfa_<timestamp>.md` e checar:

**Bloqueadores (qualquer falha = POC falhou):**
- [ ] Título em negrito + caixa alta: `ASSEMBLEIA GERAL EXTRAORDINÁRIA DO CONDOMÍNIO DO EDIFÍCIO ALFA REALIZADA AOS TREZE DE MAIO DE DOIS MIL E VINTE E SEIS`
- [ ] Caput literal do modelo, data **em minúsculas** (`treze de maio de dois mil e vinte e seis`)
- [ ] Presidente e secretário aparecem como `____` no caput (NUNCA o nome real)
- [ ] Os **4 itens** do edital aparecem todos:
  1. Pagamento antecipado MASTER
  2. Leilão das bicicletas
  3. Destinação das não arrematadas
  4. Alteração Regimento Interno (referencia 7.13.30 e 7.13.32)
- [ ] Ordem dos itens = ordem do edital
- [ ] Cada item tem parágrafo com contexto + apresentação + discussão + votação + resultado (não comprimido)
- [ ] Sub-itens (parágrafos primeiro/segundo/terceiro do Regimento) absorvidos no parágrafo do Item 4, NÃO viraram itens separados
- [ ] Encerramento: `Nada mais havendo a tratar...` + `Vila Velha/ES, treze de maio...`
- [ ] Sem bloco de assinaturas

**Não bloqueadores (anotar mas não falham POC):**
- [ ] Nomes de eleitos (síndico/conselho) mencionados se aparecerem no áudio
- [ ] Linguagem impessoal (sem "Speaker 1/2", sem ofensas)

- [ ] **Step 4: Registrar resultado**

Se POC passou: anotar tempo de execução, custo aproximado, e qualidade subjetiva. Avançar para Fase 2 (migração produção) é decisão sua após este passo.

Se POC falhou: identificar regra violada, abrir issue ou continuar conversa com Claude para iterar.

---

## Self-review

- **Spec coverage:** Tasks 2-7 cobrem `PlaudClient` (Seção do spec). Task 8 cobre os ajustes do `IAProcessor` (truncamento + env var). Task 9 cobre `poc_cli_local.py`. Task 10 cobre os critérios de sucesso do POC. AtaMatcher e AtaVerifier ficam para Fases 2 e 4 conforme spec — fora do escopo deste plano.
- **Placeholders:** nenhum "TBD"/"TODO"/"similar to Task N" — todo código presente.
- **Type consistency:** PlaudClient assinaturas estáveis em todas as tasks. `_parse_files_table` retorna `list[dict]` com chaves `id/name/date/duration_seconds`. `_parse_file_details` retorna `dict[str, str]`. `get_transcript`/`get_summary` retornam `str` bruta.

