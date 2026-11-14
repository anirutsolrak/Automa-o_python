"""Gera os editais FICTÍCIOS usados nos testes do leitor de editais.

Reproduzem a estrutura dos editais reais (que não vão para o repositório):
cabeçalho, marcador de início da pauta, itens numerados à mão ou por lista
do Word, sub-itens, alíneas recuadas e divisão AGO/AGE.

    python tests/fixtures/gerar_editais.py
"""
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm

PASTA = Path(__file__).parent / "editais"
NUM_ID_LISTA = "5"  # numeração do estilo "List Number" no template padrão do python-docx


def _lista(par, nivel: int):
    """Marca o parágrafo como item de lista numerada do Word, no nível dado."""
    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), str(nivel))
    num_id = OxmlElement("w:numId")
    num_id.set(qn("w:val"), NUM_ID_LISTA)
    num_pr.extend([ilvl, num_id])
    par._p.get_or_add_pPr().append(num_pr)


def _novo(cabecalho: list[str]) -> Document:
    doc = Document()
    for linha in cabecalho:
        doc.add_paragraph(linha)
    return doc


def _item_lista(doc, texto, nivel=0, recuo=False):
    par = doc.add_paragraph(texto)
    _lista(par, nivel)
    if recuo:
        par.paragraph_format.left_indent = Cm(1.25)


def _recuado(doc, texto):
    doc.add_paragraph(texto).paragraph_format.left_indent = Cm(1.25)


def alfa():
    doc = _novo([
        "Vila Velha, 02 de maio de 2026",
        "RETIFICAÇÃO DE CONVOCAÇÃO",
        "CONDOMÍNIO DO EDIFÍCIO ALFA",
        "Informamos aos senhores condôminos que a convocação anterior foi retificada, conforme abaixo.",
        "Assembleia Geral Extraordinária em 13/05/2026, às 19h30, no salão de festas.",
        "A assembleia vai deliberar sobre os seguintes assuntos:",
        "1. Aprovação do pagamento antecipado da manutenção do sistema de bombas;",
        "2. Leilão das bicicletas abandonadas no bicicletário;",
        "3. Destinação das bicicletas que não forem arrematadas no leilão;",
        "4. Alteração do regimento interno quanto ao uso do bicicletário.",
        "Observações: a ausência não desobriga o condômino das decisões tomadas.",
    ])
    doc.save(PASTA / "Edital_Alfa.docx")


def theta():
    doc = _novo([
        "RETIFICAÇÃO DE EDITAL",
        "CONDOMÍNIO RESIDENCIAL THETA",
        "Assembleia Geral Extraordinária em 17/03/2026, às 20h, no salão de festas.",
        "A assembleia deliberará sobre os assuntos ora retificados:",
        "Aprovação da obra de recuperação da fachada, com rateio extra em seis parcelas.",
        "Alteração do regimento interno, nos seguintes pontos:",
        "2.1 Prazo mínimo de locação por temporada:",
    ])
    _recuado(doc, "manter o prazo mínimo de 60 dias;")
    _recuado(doc, "reduzir o prazo mínimo para 32 dias.")
    doc.add_paragraph("2.2 Horário de funcionamento da piscina nos fins de semana.")
    doc.add_paragraph("Observações: as procurações devem ser entregues até o início da assembleia.")
    doc.save(PASTA / "lote_cliente" / "17.03.2026 Theta.docx")


def gama():
    doc = _novo([
        "EDITAL DE CONVOCAÇÃO",
        "CONDOMÍNIO DO EDIFÍCIO GAMA",
        "Convocamos os senhores condôminos para a assembleia de 08/04/2026, às 19h, "
        "a fim de deliberar sobre os seguintes assuntos:",
    ])
    _item_lista(doc, "Aprovação do orçamento para troca dos elevadores;")
    _item_lista(doc, "Contratação de empresa de portaria remota;")
    _item_lista(doc, "Assuntos gerais.")
    doc.add_paragraph("Observações: a assembleia será realizada em segunda chamada às 19h30.")
    doc.save(PASTA / "lote_cliente" / "08.04.2026 Gama.docx")


def delta():
    doc = _novo([
        "EDITAL DE CONVOCAÇÃO",
        "CONDOMÍNIO DO EDIFÍCIO DELTA",
        "Assembleia em 29/04/2026, às 19h. Ordem do dia:",
    ])
    for texto in ["Ratificação da contratação da nova administradora", "Reforma do playground"]:
        doc.add_paragraph().add_run(texto).bold = True
    doc.add_paragraph("Observações: a lista de presença ficará disponível na portaria.")
    doc.save(PASTA / "lote_cliente" / "29.04.2026 Delta.docx")


def fm019_ago_age():
    doc = _novo([
        "EDITAL DE CONVOCAÇÃO - AGO E AGE",
        "CONDOMÍNIO DO EDIFÍCIO EPSILON",
        "Assembleias em 19/05/2026, às 19h, para deliberarem sobre os seguintes assuntos:",
        "EM CARÁTER ORDINÁRIO",
    ])
    _item_lista(doc, "Prestação de contas do exercício de 2025;")
    _item_lista(doc, "Eleição de síndico, subsíndico e conselho fiscal;")
    doc.add_paragraph("______________________________")
    doc.add_paragraph("EM CARÁTER EXTRAORDINÁRIO")
    _item_lista(doc, "Definição das prioridades de obras para 2026:")
    _item_lista(doc, "Troca dos portões da garagem;", nivel=1)
    _item_lista(doc, "Pintura das áreas comuns;", nivel=1)
    _item_lista(doc, "Assuntos gerais.")
    doc.add_paragraph("Observações: as contas estão disponíveis para consulta no aplicativo.")
    doc.save(PASTA / "lote_cliente" / "FM-019_AGO_AGE_19.05.2026.docx")


def iota():
    doc = _novo([
        "EDITAL DE CONVOCAÇÃO - AGE E AGO",
        "CONDOMÍNIO DO EDIFÍCIO IOTA",
        "Assembleias em 20/05/2026, às 19h30, para deliberarem sobre os seguintes assuntos:",
        "EM CARÁTER EXTRAORDINÁRIO",
    ])
    # Listas recuadas pelo estilo, como nos editais reais AGE+AGO.
    _item_lista(doc, "Apresentação do laudo de inspeção predial;", recuo=True)
    _item_lista(doc, "Impermeabilização da cobertura;", recuo=True)
    _item_lista(doc, "Fechamento do pilotis com gradil;", recuo=True)
    doc.add_paragraph("EM CARÁTER ORDINÁRIO")
    _item_lista(doc, "Prestação de contas do exercício de 2025;", recuo=True)
    _item_lista(doc, "Previsão orçamentária para 2026.", recuo=True)
    doc.add_paragraph("Observações: as procurações precisam de firma reconhecida.")
    doc.save(PASTA / "lote_cliente" / "20.05.2026 Iota.docx")


if __name__ == "__main__":
    (PASTA / "lote_cliente").mkdir(parents=True, exist_ok=True)
    for gerar in (alfa, theta, gama, delta, fm019_ago_age, iota):
        gerar()
    print(f"Editais fictícios gerados em {PASTA}")
