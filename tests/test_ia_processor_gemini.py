"""O fallback Gemini usa o SDK que o requirements.txt instala (google-genai)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_gemini_gera_ata_com_o_sdk_google_genai():
    from src.ia_processor import IAProcessor

    cliente = MagicMock()
    cliente.models.generate_content.return_value = SimpleNamespace(text="  ATA gerada  ")
    with patch("google.genai.Client", return_value=cliente) as construtor:
        resultado = IAProcessor()._processar_com_gemini("prompt da ata")

    assert resultado["sucesso"] is True, resultado["mensagem"]
    assert resultado["ata"] == "ATA gerada"
    construtor.assert_called_once()
    kwargs = cliente.models.generate_content.call_args.kwargs
    assert kwargs["contents"] == "prompt da ata"
    assert resultado["modelo_usado"] == kwargs["model"]
