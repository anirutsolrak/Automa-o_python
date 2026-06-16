"""Wrapper Python sobre o CLI @plaud-ai/cli.

Encapsula chamadas subprocess ao CLI e faz parsing dos outputs
(tabela do `plaud files`, key:value do `plaud file`, texto puro de
`plaud transcript` e `plaud summary`).

Toda comunicação com o Plaud passa por esta classe.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)


# Erro levantado quando o CLI retorna exit != 0 fora dos casos toleráveis.
# Carrega returncode + stderr pra quem chamou decidir o que fazer.
class PlaudCLIError(Exception):

    def __init__(self, returncode: int, stderr: str):
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"plaud CLI exited {returncode}: {stderr.strip()}")


# Wrapper único sobre o CLI @plaud-ai/cli. Toda chamada ao Plaud passa por
# aqui: monta o comando, roda via subprocess e devolve o resultado parseado.
class PlaudClient:

    def __init__(self, cli_path: str = "plaud"):
        self.cli_path = cli_path

    # Executa `plaud <args>` capturando stdout/stderr em UTF-8.
    # Resolve cli_path via shutil.which pra honrar o PATHEXT no Windows: o npm
    # instala o CLI como `plaud.cmd`, que o subprocess não acha sem shell=True.
    def _run(self, args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
        resolved = shutil.which(self.cli_path) or self.cli_path
        cmd = [resolved] + args
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

    # True se a auth do Plaud está válida (`plaud me` retorna exit 0).
    # Usado no início do pipeline pra abortar cedo se o token expirou.
    def verify_auth(self) -> bool:
        try:
            result = self._run(["me"], timeout=15)
        except subprocess.TimeoutExpired:
            logger.warning("plaud me: timeout")
            return False
        return result.returncode == 0

    _ROW_RE = re.compile(r"^\s+([a-fA-F0-9]{32})\s{2,}(.+?)\s{2,}(\d{4}-\d{2}-\d{2})\s{2,}(\S+)\s*$")
    _DURATION_HMS = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")

    # Converte a duração textual do CLI ("3h08m", "8m51s", "45s") em segundos.
    @classmethod
    def _parse_duration(cls, raw: str) -> int:
        m = cls._DURATION_HMS.match(raw.strip())
        if not m:
            return 0
        h, mn, s = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mn * 60 + s

    # Faz o parsing da tabela alinhada do `plaud files`/`recent`. Como o CLI
    # não tem saída JSON, casa cada linha por regex (id hex + nome + data +
    # duração) e ignora cabeçalho, separadores e rodapé "Page N".
    @classmethod
    def _parse_files_table(cls, output: str) -> list[dict]:
        rows = []
        for line in output.splitlines():
            m = cls._ROW_RE.match(line)
            if not m:
                continue  # linha que não é de dados (cabeçalho/rodapé)
            file_id, name, date, duration = m.groups()
            rows.append({
                "id": file_id,
                "name": name.strip(),
                "date": date,
                "duration_seconds": cls._parse_duration(duration),
            })
        return rows

    # Lista as gravações dos últimos N dias via `plaud recent`.
    def list_recent(self, days: int = 7, page_size: int = 50) -> list[dict]:
        result = self._run(["recent", "--days", str(days), "--page-size", str(page_size)])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return self._parse_files_table(result.stdout)

    # Lista gravações num intervalo de datas (YYYY-MM-DD, inclusivo).
    # Contorno: o CLI atual removeu --from/--to do `plaud files`, então pega
    # `recent --days N` (N = dias entre hoje e date_from) e filtra em Python.
    def list_by_date_range(self, date_from: str, date_to: str, page_size: int = 100) -> list[dict]:
        from datetime import date as _date, datetime as _dt
        try:
            df = _dt.strptime(date_from, "%Y-%m-%d").date()
            dt = _dt.strptime(date_to, "%Y-%m-%d").date()
        except ValueError as e:
            raise PlaudCLIError(0, f"datas inválidas (esperado YYYY-MM-DD): {e}")

        hoje = _date.today()
        # +1 dia de margem pra fuso e arredondamento
        dias = max(1, (hoje - df).days + 1)

        result = self._run([
            "recent",
            "--days", str(dias),
        ])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        todos = self._parse_files_table(result.stdout)
        # Filtra inclusivamente
        filtrados = []
        for r in todos:
            try:
                d = _dt.strptime(r["date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            if df <= d <= dt:
                filtrados.append(r)
        return filtrados[:page_size] if page_size else filtrados

    _KV_RE = re.compile(r"^\s+(\w+):\s+(.+?)\s*$")

    # Faz o parsing da saída key:value do `plaud file <id>` num dict.
    # Inclui as flags audio/transcript/summary = available|processing.
    @classmethod
    def _parse_file_details(cls, output: str) -> dict:
        meta = {}
        for line in output.splitlines():
            m = cls._KV_RE.match(line)
            if m:
                meta[m.group(1)] = m.group(2)
        return meta

    # Metadata da gravação + flags de disponibilidade. O pipeline lê
    # transcript/summary pra decidir se a gravação já está pronta ou ainda
    # "processing" (nesse caso pula e tenta de novo no próximo cron).
    def get_file_meta(self, file_id: str) -> dict:
        result = self._run(["file", file_id])
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return self._parse_file_details(result.stdout)

    # Transcript completo (texto bruto) da gravação. Timeout maior porque
    # transcripts de reuniões longas (horas) demoram pra trafegar.
    def get_transcript(self, file_id: str, timeout: int = 120) -> str:
        result = self._run(["transcript", file_id], timeout=timeout)
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return result.stdout

    # Summary (markdown) gerado pela IA do Plaud. No pipeline serve só de
    # apoio/verificação — a fonte da ATA é o transcript + edital.
    def get_summary(self, file_id: str, timeout: int = 60) -> str:
        result = self._run(["summary", file_id], timeout=timeout)
        if result.returncode != 0:
            raise PlaudCLIError(result.returncode, result.stderr)
        return result.stdout
