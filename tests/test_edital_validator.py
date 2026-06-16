"""Testes do validador de extração contra os editais reais em editais_local/."""

import os
import pytest


def _carregar(path):
    from src.edital_reader import EditalReader
    r = EditalReader(caminho_arquivo=path)
    r.carregar()
    r.extrair_pontos()
    return r


@pytest.fixture
def alfa_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "Edital_Alfa.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


@pytest.fixture
def theta_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "lote_cliente", "17.03.2026 Theta.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


@pytest.fixture
def gama_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "lote_cliente", "08.04.2026 Gama.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


@pytest.fixture
def delta_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "lote_cliente", "29.04.2026 Delta.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


@pytest.fixture
def fm019_ago_age_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "lote_cliente", "FM-019_AGO_AGE_19.05.2026.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


@pytest.fixture
def iota_path():
    p = os.path.join(os.path.dirname(__file__), "..", "editais_local", "lote_cliente", "20.05.2026 Iota.docx")
    if not os.path.exists(p):
        pytest.skip(f"Faltando: {p}")
    return p


def test_alfa_passa_validacao_sem_alertas(alfa_path):
    """Edital Alfa segue o padrão — deve passar sem alertas."""
    from src.edital_reader import validar_extracao
    r = _carregar(alfa_path)
    v = validar_extracao(r)
    assert v["ok"] is True, f"Alertas inesperados: {v['alertas']}"
    assert v["num_itens"] == 4


def test_theta_agora_extrai_2_itens_reais(theta_path):
    """Theta é retificação — após o suporte específico, esperamos
    extrair exatamente os 2 itens reais da pauta (não mais 6 com header espúrio)."""
    r = _carregar(theta_path)
    pontos_reais = [p for p in r.pontos if not p.get('eh_separador')]
    assert len(pontos_reais) == 2, f"Esperado 2 itens reais, veio {len(pontos_reais)}: {[p['titulo'][:50] for p in pontos_reais]}"

    # Item 1: obra de fachada
    assert "fachada" in pontos_reais[0]['titulo'].lower()
    # Item 2: regimento interno — deve ter sub-itens 2.1 e 2.2
    assert "regimento" in pontos_reais[1]['titulo'].lower()
    subitens = pontos_reais[1].get('subitens', [])
    assert len(subitens) == 2, f"Esperado 2 sub-itens (2.1 e 2.2), veio {len(subitens)}"
    assert subitens[0]['prefixo'] == '2.1'
    assert subitens[1]['prefixo'] == '2.2'
    # Sub-item 2.1 deve ter 2 alíneas (manter 60d / reduzir 32d)
    alineas_21 = subitens[0].get('alineas', [])
    assert len(alineas_21) >= 2, f"Esperado >=2 alíneas no 2.1, veio {len(alineas_21)}: {alineas_21}"


def test_theta_marcador_inicio_agora_casa(theta_path):
    """Com regex ampliado para 'ora retificados', o marcador deve casar."""
    r = _carregar(theta_path)
    assert r.marcador_inicio_encontrado is True
    from src.edital_reader import validar_extracao
    v = validar_extracao(r)
    # Sem alerta de marcador
    assert not any("Marcador" in a for a in v["alertas"]), f"Alertas inesperados: {v['alertas']}"


def test_gama_passa_validacao(gama_path):
    from src.edital_reader import validar_extracao
    r = _carregar(gama_path)
    v = validar_extracao(r)
    # Gama pode ter alguns alertas dependendo do parser, mas deve ter > 0 itens
    assert v["num_itens"] > 0


def test_delta_passa_validacao(delta_path):
    from src.edital_reader import validar_extracao
    r = _carregar(delta_path)
    v = validar_extracao(r)
    assert v["num_itens"] > 0


def test_fm019_ago_age_extrai_separadores_e_itens(fm019_ago_age_path):
    """FM-019 é AGO+AGE: 2 itens AGO + separador + 2 itens AGE (com sub-itens no 1º)."""
    r = _carregar(fm019_ago_age_path)
    itens_reais = [p for p in r.pontos if not p.get('eh_separador')]
    separadores = [p for p in r.pontos if p.get('eh_separador')]

    # 4 itens reais (2 AGO + 2 AGE)
    assert len(itens_reais) == 4, f"Esperado 4, veio {len(itens_reais)}: {[p['titulo'][:50] for p in itens_reais]}"
    # Pelo menos 1 separador entre AGO e AGE (idealmente exatamente 1 após dedupe)
    assert len(separadores) >= 1, f"Esperado >=1 separador, veio {len(separadores)}"

    titulos = [p['titulo'].lower() for p in itens_reais]
    assert any('presta' in t and 'conta' in t for t in titulos), "Item AGO prestação de contas ausente"
    assert any('eleic' in t or 'eleiç' in t for t in titulos), "Item AGO eleição ausente"
    assert any('prioridade' in t for t in titulos), "Item AGE prioridades ausente"
    assert any('assuntos gerais' in t for t in titulos), "Item AGE assuntos gerais ausente"


def test_iota_ago_age_extrai_5_itens(iota_path):
    """Iota é AGE+AGO (invertido): 3 itens AGE + 2 itens AGO."""
    r = _carregar(iota_path)
    itens_reais = [p for p in r.pontos if not p.get('eh_separador')]
    assert len(itens_reais) == 5, f"Esperado 5, veio {len(itens_reais)}: {[p['titulo'][:50] for p in itens_reais]}"

    titulos = [p['titulo'].lower() for p in itens_reais]
    assert any('laudo de inspec' in t or 'laudo de inspeç' in t for t in titulos), "Item AGE laudo ausente"
    assert any('cobertura' in t for t in titulos), "Item AGE cobertura ausente"
    assert any('pilotis' in t for t in titulos), "Item AGE pilotis ausente"
    assert any('presta' in t and 'conta' in t for t in titulos), "Item AGO prestação ausente"
    assert any('orcament' in t or 'orçament' in t for t in titulos), "Item AGO previsão orçamentária ausente"
