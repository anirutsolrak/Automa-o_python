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


def test_list_by_date_range_usa_plaud_recent_e_filtra():
    """O CLI atual não tem --from/--to em `plaud files` — usamos `plaud recent
    --days N` e filtramos as datas em Python (intervalo inclusivo)."""
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_FILES_OUTPUT)) as m:
        # SAMPLE_FILES_OUTPUT tem datas 2026-05-14, 2026-05-06, 2026-05-05
        rows = client.list_by_date_range("2026-05-01", "2026-05-19")
        args = m.call_args[0][0]
        assert "recent" in args
        assert "--days" in args
    # Todas 3 datas estão entre 01/05 e 19/05
    assert len(rows) == 3


def test_list_by_date_range_filtra_fora_do_intervalo():
    client = PlaudClient()
    with patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, SAMPLE_FILES_OUTPUT)):
        # SAMPLE_FILES_OUTPUT tem 2026-05-14, 2026-05-06, 2026-05-05
        rows = client.list_by_date_range("2026-05-10", "2026-05-20")
    # Só Alfa (2026-05-14) entra
    assert len(rows) == 1
    assert "Alfa" in rows[0]["name"]


def test_list_by_date_range_rejeita_datas_invalidas():
    from src.plaud_client import PlaudCLIError
    client = PlaudClient()
    with pytest.raises(PlaudCLIError):
        client.list_by_date_range("hoje", "amanha")


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


SAMPLE_UPPERCASE_OUTPUT = """
Files on this page: 1

  ID                                  NAME                                  DATE          DURATION
  ──────────────────────────────────────────────────────────────────────────────────────────────────
  00000000000000000000000000000000    13.05.2026 Alfa                    2026-05-14    3h08m

Page 1
"""


def test_parse_files_table_accepts_uppercase_ids():
    """Regression: regex must be case-insensitive on hex IDs."""
    rows = PlaudClient._parse_files_table(SAMPLE_UPPERCASE_OUTPUT)
    assert len(rows) == 1
    assert rows[0]["id"] == "00000000000000000000000000000000"


def test_run_resolves_cli_path_via_shutil_which():
    """Garantia de que cli_path é resolvido via shutil.which (Windows .cmd)."""
    client = PlaudClient()
    with patch("src.plaud_client.shutil.which", return_value=r"C:\fake\path\plaud.cmd") as which_mock, \
         patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, "")) as run_mock:
        client._run(["me"])
    which_mock.assert_called_once_with("plaud")
    args = run_mock.call_args[0][0]
    assert args[0] == r"C:\fake\path\plaud.cmd"


def test_run_falls_back_to_cli_path_when_which_returns_none():
    """Se shutil.which não achar, usa cli_path original (deixa subprocess explodir)."""
    client = PlaudClient()
    with patch("src.plaud_client.shutil.which", return_value=None), \
         patch("src.plaud_client.subprocess.run", return_value=_mock_run(0, "")) as run_mock:
        client._run(["me"])
    args = run_mock.call_args[0][0]
    assert args[0] == "plaud"
