"""Regressão: bug onde cabeçalho/título/intro do edital virava ITEM."""

import os
import pytest


@pytest.fixture
def alfa_edital_path():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "editais", "Edital_Alfa.docx")
    if not os.path.exists(path):
        pytest.skip(f"Edital de teste não encontrado em {path}")
    return path


def test_alfa_extrai_apenas_4_itens_reais(alfa_edital_path):
    """O edital Alfa tem 4 itens reais — header/título/intro NÃO devem virar ITEM."""
    from src.edital_reader import EditalReader

    reader = EditalReader(caminho_arquivo=alfa_edital_path)
    reader.carregar()
    pontos = reader.extrair_pontos()

    pontos_reais = [p for p in pontos if not p.get('eh_separador')]
    assert len(pontos_reais) == 4, f"Esperado 4 itens, veio {len(pontos_reais)}: {[p['titulo'][:50] for p in pontos_reais]}"


def test_alfa_titulos_correspondem_aos_4_itens_da_pauta(alfa_edital_path):
    from src.edital_reader import EditalReader

    reader = EditalReader(caminho_arquivo=alfa_edital_path)
    reader.carregar()
    pontos = reader.extrair_pontos()
    titulos_lower = [p['titulo'].lower() for p in pontos if not p.get('eh_separador')]

    # 4 itens reais do edital
    assert any('pagamento antecipado' in t for t in titulos_lower), "Item de pagamento MASTER ausente"
    assert any('leilão das bicicletas' in t for t in titulos_lower), "Item de leilão ausente"
    assert any('destinação das bicicletas' in t for t in titulos_lower), "Item de destinação ausente"
    assert any('regimento interno' in t for t in titulos_lower), "Item de regimento ausente"


def test_alfa_nao_extrai_header_como_item(alfa_edital_path):
    """Regressão direta do bug: 'Vila Velha', 'Retificação', 'Informamos' NÃO podem ser itens."""
    from src.edital_reader import EditalReader

    reader = EditalReader(caminho_arquivo=alfa_edital_path)
    reader.carregar()
    pontos = reader.extrair_pontos()
    titulos_lower = [p['titulo'].lower() for p in pontos if not p.get('eh_separador')]

    assert not any('vila velha' in t for t in titulos_lower), "Header 'Vila Velha' vazou como item"
    assert not any('retificação de convocação' in t for t in titulos_lower), "Título do doc vazou"
    assert not any('informamos aos senhores' in t for t in titulos_lower), "Parágrafo intro vazou"
