"""Testes do ProcessadosTracker."""

import json
import os
import pytest


@pytest.fixture
def tmp_tracker(tmp_path):
    from src.processados_tracker import ProcessadosTracker
    return ProcessadosTracker(caminho=str(tmp_path / "processados.json"))


@pytest.fixture
def edital_fake(tmp_path):
    p = tmp_path / "13.05.2026 Alfa.docx"
    p.write_bytes(b"conteudo fake do edital " * 100)
    return str(p)


def test_tracker_inicializa_com_arquivo_inexistente(tmp_tracker):
    """Sem arquivo, tracker começa vazio sem erro."""
    assert tmp_tracker.ja_processado("/qualquer/path.docx") is False


def test_marcar_processado_cria_entrada(tmp_tracker, edital_fake):
    tmp_tracker.marcar_processado(edital_fake, "audio_id_123", "/saida/ATA.docx")
    assert tmp_tracker.ja_processado(edital_fake) is True


def test_ja_processado_usa_hash_nao_caminho(tmp_tracker, edital_fake, tmp_path):
    """Edital com nome diferente mas mesmo conteúdo: já processado."""
    tmp_tracker.marcar_processado(edital_fake, "id1", "/x.docx")
    duplicado = tmp_path / "renomeado.docx"
    duplicado.write_bytes(open(edital_fake, "rb").read())
    assert tmp_tracker.ja_processado(str(duplicado)) is True


def test_edital_editado_reprocessa(tmp_tracker, edital_fake):
    tmp_tracker.marcar_processado(edital_fake, "id1", "/x.docx")
    # Modifica conteúdo
    with open(edital_fake, "wb") as f:
        f.write(b"conteudo MODIFICADO" * 100)
    assert tmp_tracker.ja_processado(edital_fake) is False


def test_persistencia_entre_instancias(tmp_path, edital_fake):
    from src.processados_tracker import ProcessadosTracker
    caminho = str(tmp_path / "processados.json")
    t1 = ProcessadosTracker(caminho=caminho)
    t1.marcar_processado(edital_fake, "id1", "/x.docx")
    # Nova instância lê o arquivo
    t2 = ProcessadosTracker(caminho=caminho)
    assert t2.ja_processado(edital_fake) is True


def test_arquivo_json_corrompido_nao_quebra(tmp_path, edital_fake):
    from src.processados_tracker import ProcessadosTracker
    caminho = str(tmp_path / "processados.json")
    with open(caminho, "w") as f:
        f.write("{ json invalido !!!")
    t = ProcessadosTracker(caminho=caminho)
    # Não levanta exceção, trata como vazio
    assert t.ja_processado(edital_fake) is False
    # E permite gravar normalmente depois
    t.marcar_processado(edital_fake, "id1", "/x.docx")
    assert t.ja_processado(edital_fake) is True
