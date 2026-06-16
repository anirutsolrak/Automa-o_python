"""Testes do EditalScanner."""

import os
import time
import pytest


@pytest.fixture
def pasta_fake(tmp_path):
    """Estrutura: <root>/Editais/<arquivos>.docx + Processados/"""
    raiz = tmp_path / "Editais"
    raiz.mkdir()
    # Cria 3 editais com mtimes distintos
    a = raiz / "13.05.2026 Alfa.docx"
    a.write_bytes(b"A" * 1000)
    time.sleep(0.01)
    b = raiz / "14.05.2026 Zeta.docx"
    b.write_bytes(b"B" * 1000)
    time.sleep(0.01)
    c = raiz / "15.05.2026 Delta.docx"
    c.write_bytes(b"C" * 1000)
    # Subpasta com mais um
    sub = raiz / "subpasta"
    sub.mkdir()
    d = sub / "16.05.2026 Omega.docx"
    d.write_bytes(b"D" * 1000)
    return str(raiz)


@pytest.fixture
def tracker_vazio(tmp_path):
    from src.processados_tracker import ProcessadosTracker
    return ProcessadosTracker(caminho=str(tmp_path / "p.json"))


def test_lista_todos_quando_tracker_vazio(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert len(pendentes) == 4
    nomes = [os.path.basename(p) for p in pendentes]
    assert "13.05.2026 Alfa.docx" in nomes
    assert "16.05.2026 Omega.docx" in nomes  # da subpasta


def test_ordena_por_mtime_ascendente(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    # Alfa criado primeiro → vem primeiro
    assert "Alfa" in pendentes[0]


def test_filtra_ja_processados(pasta_fake, tracker_vazio):
    """Editais marcados no tracker não aparecem em pendentes."""
    from src.edital_scanner import EditalScanner
    # Marca Alfa como processado
    alfa_path = os.path.join(pasta_fake, "13.05.2026 Alfa.docx")
    tracker_vazio.marcar_processado(alfa_path, "audio_x", "/ata.docx")

    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert len(pendentes) == 3
    assert not any("Alfa" in p for p in pendentes)


def test_aplica_limite(pasta_fake, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes(limite=2)
    assert len(pendentes) == 2


def test_pasta_inexistente_retorna_vazio(tmp_path, tracker_vazio):
    from src.edital_scanner import EditalScanner
    scanner = EditalScanner(str(tmp_path / "inexistente"), tracker_vazio)
    assert scanner.listar_pendentes() == []


def test_ignora_arquivos_temporarios_word(pasta_fake, tracker_vazio):
    """Arquivos '~$nome.docx' do Word não devem aparecer."""
    from src.edital_scanner import EditalScanner
    lixo = os.path.join(pasta_fake, "~$13.05.2026 Alfa.docx")
    with open(lixo, "wb") as f:
        f.write(b"lock")
    scanner = EditalScanner(pasta_fake, tracker_vazio)
    pendentes = scanner.listar_pendentes()
    assert not any("~$" in p for p in pendentes)
