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
