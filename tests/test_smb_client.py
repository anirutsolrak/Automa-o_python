"""Testes do SMBClient (subprocess mockado)."""

from unittest.mock import MagicMock, patch
import pytest


SAMPLE_LS_OUTPUT = """\
Domain=[CLIENTE] OS=[Windows Server 2019] Server=[Windows Server]
  .                                   D        0  Mon May 26 10:00:00 2026
  ..                                  D        0  Mon May 26 10:00:00 2026
  25.05.2026 Uniplace.docx            A    45123  Sun May 25 09:30:15 2026
  26.05.2026 Delta.docx       A    52001  Mon May 26 08:12:42 2026
  ~$25.05.2026 Lock.docx              AH     162  Sun May 25 09:30:15 2026
  Subpasta                            D        0  Mon May 26 10:00:00 2026

        12345678 blocks of size 4096. 1234567 blocks available
"""


def _mock_run(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_listar_extrai_arquivos_e_ignora_diretorios():
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(0, SAMPLE_LS_OUTPUT)):
        files = cli.listar("Automacao/Editais/2026")
    nomes = [f["name"] for f in files]
    assert "25.05.2026 Uniplace.docx" in nomes
    assert "26.05.2026 Delta.docx" in nomes
    assert "~$25.05.2026 Lock.docx" in nomes  # listar bruto traz tudo
    assert "Subpasta" not in nomes  # diretórios filtrados
    assert "." not in nomes
    assert ".." not in nomes


def test_listar_extrai_size_e_mtime():
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(0, SAMPLE_LS_OUTPUT)):
        files = cli.listar("Automacao/Editais/2026")
    uniplace = next(f for f in files if "Uniplace" in f["name"])
    assert uniplace["size"] == 45123
    assert uniplace["mtime"].year == 2026
    assert uniplace["mtime"].month == 5
    assert uniplace["mtime"].day == 25


def test_listar_falha_levanta_erro():
    from src.smb_client import SMBClient, SMBClientError
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(1, "", "NT_STATUS_ACCESS_DENIED")):
        with pytest.raises(SMBClientError) as exc:
            cli.listar("Automacao/Editais/2026")
        assert exc.value.returncode == 1
        assert "ACCESS_DENIED" in str(exc.value)


def test_baixar_monta_comando_get_corretamente(tmp_path):
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    destino = tmp_path / "edital.docx"
    # Simula que o smbclient criou o arquivo
    def fake_run(args, **kwargs):
        destino.write_bytes(b"conteudo fake")
        return _mock_run(0, "")
    with patch("src.smb_client.subprocess.run", side_effect=fake_run) as m:
        cli.baixar("Automacao/Editais/2026/edital.docx", str(destino))
        cmd_arg = m.call_args[0][0][-1]  # último arg do args
        assert 'cd "Automacao/Editais/2026"' in cmd_arg
        assert 'get "edital.docx"' in cmd_arg
    assert destino.exists()


def test_baixar_falha_se_arquivo_nao_criado(tmp_path):
    from src.smb_client import SMBClient, SMBClientError
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    destino = tmp_path / "edital.docx"
    # subprocess.run retorna OK MAS arquivo não foi criado (smbclient retornou
    # 0 com erro silencioso). Devemos detectar.
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(0, "")):
        with pytest.raises(SMBClientError):
            cli.baixar("X/Y.docx", str(destino))


def test_subir_chama_mkdir_e_put(tmp_path):
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    local = tmp_path / "ata.docx"
    local.write_bytes(b"conteudo")
    chamadas = []
    def fake_run(args, **kwargs):
        chamadas.append(args[-1])  # comando -c
        return _mock_run(0, "")
    with patch("src.smb_client.subprocess.run", side_effect=fake_run):
        cli.subir(str(local), "Automacao/Atas/2026/ata.docx")
    assert any("mkdir" in c for c in chamadas)
    assert any('put "' in c and 'ata.docx' in c for c in chamadas)


def test_conectividade_ok():
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "user", "pass")
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(0, "")):
        assert cli.conectividade_ok() is True
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(1, "", "fail")):
        assert cli.conectividade_ok() is False


def test_senha_nao_vai_na_linha_de_comando():
    """A linha de comando aparece no `ps` para qualquer usuário; a senha vai por PASSWD."""
    from src.smb_client import SMBClient
    cli = SMBClient("srv", "Arquivos", "svc_automacao", "<SENHA_SMB>")
    assert cli._unc == "//srv/Arquivos"
    with patch("src.smb_client.subprocess.run", return_value=_mock_run(0, "")) as m:
        cli.conectividade_ok()
    args, kwargs = m.call_args
    assert not any("<SENHA_SMB>" in a for a in args[0])
    assert args[0][args[0].index("-U") + 1] == "svc_automacao"
    assert kwargs["env"]["PASSWD"] == "<SENHA_SMB>"
