"""Testes do ajuste de truncamento e seleção de modelo no IAProcessor."""

import os
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("PLAUD_IA_MODELO", raising=False)
    # Config lê os valores no momento da definição da classe (class-level attrs),
    # então monkeypatch.setenv sozinho não basta — precisamos forçar os attrs do Config.
    from src.config import Config
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", None)


def test_transcript_truncation_is_200k_chars(fake_env):
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    # Usa caractere raro (§) garantidamente ausente do template
    long_transcript = "§" * 250000  # 250k > novo limite de 200k
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as m:
        ia.processar(transcript=long_transcript, summary="", edital="edital simples")
        prompt_passado = m.call_args[0][0]
    # Confirma que NÃO truncou em 20000 (regressão do bug original)
    assert prompt_passado.count("§") > 20000
    # Confirma que truncou em 200000 (rede de segurança)
    assert prompt_passado.count("§") == 200000


def test_summary_truncation_is_30k_chars(fake_env):
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    long_summary = "¤" * 50000  # sentinel char fora do template (idem teste do transcript)
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as m:
        ia.processar(transcript="t", summary=long_summary, edital="edital")
        prompt_passado = m.call_args[0][0]
    assert prompt_passado.count("¤") == 30000


def test_env_var_forces_o3_skipping_gemini(fake_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("PLAUD_IA_MODELO", "o3")
    from src.config import Config
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "fake-gemini-key")
    from src.ia_processor import IAProcessor
    ia = IAProcessor()
    with patch.object(ia, "_processar_com_gpt", return_value={"sucesso": True, "ata": "OK", "modelo_usado": "o3", "mensagem": ""}) as gpt_mock, \
         patch.object(ia, "_processar_com_gemini") as gemini_mock:
        ia.processar(transcript="t", summary="s", edital="e")
    gpt_mock.assert_called_once()
    gemini_mock.assert_not_called()


def test_gpt_uses_model_from_env_var(fake_env, monkeypatch):
    from src.config import Config
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("PLAUD_IA_MODELO", "o3-mini")

    from src.ia_processor import IAProcessor
    ia = IAProcessor()

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="ATA fake"))]

    with patch("openai.OpenAI") as openai_mock:
        client_mock = openai_mock.return_value
        client_mock.chat.completions.create.return_value = fake_response

        result = ia.processar(transcript="t", summary="s", edital="e")

        call_kwargs = client_mock.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "o3-mini"
        assert call_kwargs["reasoning_effort"] == "high"
        assert result["sucesso"] is True
        assert result["modelo_usado"] == "o3-mini"


def test_gpt_skips_reasoning_effort_for_non_reasoning_models(fake_env, monkeypatch):
    from src.config import Config
    monkeypatch.setattr(Config, "OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("PLAUD_IA_MODELO", "gpt-4o-mini")

    from src.ia_processor import IAProcessor
    ia = IAProcessor()

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="ATA fake"))]

    with patch("openai.OpenAI") as openai_mock:
        client_mock = openai_mock.return_value
        client_mock.chat.completions.create.return_value = fake_response

        ia.processar(transcript="t", summary="s", edital="e")

        call_kwargs = client_mock.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert "reasoning_effort" not in call_kwargs
