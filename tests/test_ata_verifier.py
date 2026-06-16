"""Testes do AtaVerifier (chamadas OpenAI mockadas)."""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def fake_env(monkeypatch):
    from src.config import Config
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "fake-key")


def _resp(text):
    """Mock de resposta OpenAI."""
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=text))]
    return r


def test_verifier_inicializa_com_modelo_default(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    assert v.model == "gpt-4o-mini"
    assert v.disponivel is True


def test_verifier_aceita_modelo_via_env(fake_env, monkeypatch):
    monkeypatch.setenv("PLAUD_VERIFIER_MODELO", "gpt-4.1-mini")
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    assert v.model == "gpt-4.1-mini"


def test_verifier_aceita_modelo_via_argumento(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier(model="o3-mini")
    assert v.model == "o3-mini"


def test_verifier_detecta_sem_omissoes(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    with patch("openai.OpenAI") as mock:
        mock.return_value.chat.completions.create.return_value = _resp("NENHUMA OMISSAO")
        r = v.verificar(ata="ata fake", transcript="transcript fake")
    assert r["tem_omissoes"] is False
    assert "NENHUMA OMISSAO" in r["relatorio"]
    assert r["modelo"] == "gpt-4o-mini"


def test_verifier_detecta_omissoes(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    relatorio_mock = "- Valor R$ 4.500,00 da proposta jurídica não aparece na ATA\n- Voto de 15 a favor da redução de prazo não foi registrado"
    with patch("openai.OpenAI") as mock:
        mock.return_value.chat.completions.create.return_value = _resp(relatorio_mock)
        r = v.verificar(ata="ata fake", transcript="transcript fake")
    assert r["tem_omissoes"] is True
    assert "R$ 4.500" in r["relatorio"]


def test_verifier_nao_bloqueia_em_caso_de_falha(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    with patch("openai.OpenAI") as mock:
        mock.return_value.chat.completions.create.side_effect = RuntimeError("rede caiu")
        r = v.verificar(ata="ata fake", transcript="transcript fake")
    assert r["tem_omissoes"] is False
    assert "rede caiu" in r["relatorio"]


def test_verifier_sem_api_key_retorna_desabilitado(monkeypatch):
    from src.config import Config
    monkeypatch.setattr(Config, "OPENAI_API_KEY", None)
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    assert v.disponivel is False
    r = v.verificar(ata="x", transcript="y")
    assert r["tem_omissoes"] is False
    assert "desabilitado" in r["relatorio"].lower()


def test_verifier_trunca_transcript_e_ata_grandes(fake_env):
    from src.ata_verifier import AtaVerifier
    v = AtaVerifier()
    longo_transcript = "¤" * 200_000  # sentinelas fora do prompt template
    longa_ata = "§" * 60_000
    with patch("openai.OpenAI") as mock:
        mock.return_value.chat.completions.create.return_value = _resp("NENHUMA OMISSAO")
        v.verificar(ata=longa_ata, transcript=longo_transcript)
        prompt = mock.return_value.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert prompt.count("¤") == 80_000
    assert prompt.count("§") == 30_000
