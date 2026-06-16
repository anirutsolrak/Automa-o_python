"""
Leitor de Editais de Condomínio - VERSÃO FINAL ROBUSTA
Baseado nos padrões reais dos editais FM-019, FM-255, FM-272
"""

import logging
import os
import re
import unicodedata
from typing import List, Dict, Optional
from docx import Document

logger = logging.getLogger(__name__)


# Remove acentos e baixa pra minúsculas, pra casar texto de forma robusta.
def _normalizar_texto(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII").lower()


# Padrões regex que casam variações morfológicas de marcadores de início da pauta.
# Operam em texto já normalizado (sem acentos, minúsculas).
# Inclui formato de "retificação" (caso Condomínio Theta: "deliberará sobre
# os assuntos ora retificados") além do padrão "deliberar sobre os seguintes assuntos".
PATROES_INICIO_PAUTA = [
    # Padrão clássico: "...deliberar sobre os seguintes assuntos/pontos/itens"
    re.compile(r"delibera\w*\s+sobre\s+os?\s+seguintes\s+(assuntos|pontos|itens|temas)"),
    # Retificação: "...deliberará sobre os assuntos ora retificados"
    re.compile(r"delibera\w*\s+sobre\s+os?\s+(assuntos|pontos|itens|temas)(\s+ora)?\s+retificad"),
    # Variantes de tratamento: "tratar dos seguintes...", "tratará dos temas..."
    re.compile(r"trata\w*\s+(d[oa]s?\s+)?seguintes\s+(assuntos|pontos|itens|temas)"),
    re.compile(r"trata\w*\s+(d[oa]s?\s+)?(assuntos|pontos|itens|temas)(\s+ora)?\s+retificad"),
    # Marcadores explícitos de pauta
    re.compile(r"ordem\s+do\s+dia"),
    re.compile(r"assuntos\s+a\s+serem\s+tratados"),
    re.compile(r"para\s+delibera\w*"),
]

# Numeração explícita exigida pelo fallback: "1.", "1)", "I.", "II)", "a.", "b)", "(1)", "(a)"
RE_NUMERACAO_EXPLICITA = re.compile(
    r"^\s*\(?(?:\d+|[ivxlcdm]+|[a-z])\)?[\.\)]\s+",
    re.IGNORECASE,
)

# Sub-item decimal: "2.1", "2.1.", "2.1:", "2.1 Título". Capturas: (prefixo "2.1", título)
RE_SUB_DECIMAL = re.compile(r"^\s*(\d+\.\d+)[\.\:\)]?\s+(.+?)\s*$")


# Lê o .docx do edital e extrai a ORDEM DO DIA preservando a hierarquia
# (itens, sub-itens, alíneas) e a divisão AGO/AGE. Baseado nos formatos reais
# de edital do cliente (texto fixo "deliberar sobre os seguintes assuntos",
# pauta numerada ou em parágrafos).
class EditalReader:

    def __init__(self, caminho_arquivo: str = None):
        self.caminho_arquivo = caminho_arquivo
        self.conteudo_bruto = ""
        self.paragrafos = []
        self.pontos = []
        # Diagnóstico de extração (preenchido por extrair_pontos)
        self.indice_inicio: Optional[int] = None       # None = marcador "deliberar sobre" não casou
        self.indice_fim: Optional[int] = None
        self.marcador_inicio_encontrado: bool = False
    
    # Abre o .docx e extrai cada parágrafo já com seus metadados de formatação
    # (negrito, indentação, nível de lista do Word) — são esses metadados que
    # permitem reconstruir a hierarquia depois. Retorna dict {sucesso, ...}.
    def carregar(self, caminho: str = None) -> Dict:
        caminho = caminho or self.caminho_arquivo
        
        if not caminho or not os.path.exists(caminho):
            return {
                "sucesso": False,
                "mensagem": f"Arquivo não encontrado: {caminho}",
                "conteudo": None
            }
        
        try:
            logger.info(f"[EDITAL] Carregando: {os.path.basename(caminho)}")
            
            doc = Document(caminho)
            from docx.oxml.ns import qn as _qn

            paragrafos_texto = []
            for para in doc.paragraphs:
                texto = para.text.strip()
                if texto:
                    tem_negrito = any(run.bold for run in para.runs if run.text.strip())
                    indent = int(para.paragraph_format.left_indent or 0)
                    nivel_lista = None
                    eh_lista_num = False
                    pPr = para._element.find(_qn('w:pPr'))
                    if pPr is not None:
                        numPr = pPr.find(_qn('w:numPr'))
                        if numPr is not None:
                            eh_lista_num = True
                            ilvl = numPr.find(_qn('w:ilvl'))
                            nivel_lista = int(ilvl.get(_qn('w:val'))) if ilvl is not None else 0
                    paragrafos_texto.append({
                        'texto':        texto,
                        'negrito':      tem_negrito,
                        'runs':         len(para.runs),
                        'indent':       indent,
                        'nivel_lista':  nivel_lista,
                        'eh_lista_num': eh_lista_num,
                    })
            
            self.paragrafos = paragrafos_texto
            self.conteudo_bruto = "\n".join([p['texto'] for p in paragrafos_texto])
            self.caminho_arquivo = caminho
            
            logger.info(f"[EDITAL] ✓ Carregado: {len(self.conteudo_bruto)} chars, {len(paragrafos_texto)} parágrafos")
            
            return {
                "sucesso": True,
                "mensagem": "Edital carregado com sucesso",
                "conteudo": self.conteudo_bruto,
                "num_paragrafos": len(paragrafos_texto)
            }
            
        except Exception as e:
            logger.error(f"[EDITAL] ✗ Erro ao carregar: {e}", exc_info=True)
            return {
                "sucesso": False,
                "mensagem": str(e),
                "conteudo": None
            }
    
    # Extrai a ORDEM DO DIA usando os metadados XML do docx pra classificar
    # cada parágrafo:
    #   nivel_lista=0     → item principal
    #   nivel_lista=1     → sub-item automático do Word
    #   indent>0 sem num  → sub-item com prefixo manual (2.3, 2.5...)
    #   traços / "EM CARÁTER EXTRAORDINÁRIO" → separador AGO/AGE
    def extrair_pontos(self) -> List[Dict]:
        if not self.paragrafos:
            logger.warning("[EDITAL] Nenhum parágrafo carregado")
            return []

        pontos = []

        # Etapa 1: início da pauta (regex robusto contra variações morfológicas)
        indice_inicio = None
        for i, para in enumerate(self.paragrafos):
            tn = _normalizar_texto(para['texto'])
            if any(p.search(tn) for p in PATROES_INICIO_PAUTA):
                indice_inicio = i + 1
                self.marcador_inicio_encontrado = True
                logger.info(f"[EDITAL] Início da pauta: linha {i}")
                break
        if indice_inicio is None:
            logger.warning("[EDITAL] Início da pauta não identificado — usando índice 0 (risco de falsos positivos)")
            indice_inicio = 0
            self.marcador_inicio_encontrado = False
        self.indice_inicio = indice_inicio

        # Etapa 2: fim da pauta
        indice_fim = len(self.paragrafos)
        for i in range(indice_inicio, len(self.paragrafos)):
            tl = self.paragrafos[i]['texto'].lower()
            if any(t in tl for t in [
                "observações", "observação:", "art. 1.335", "grupo cliente",
                "administração.", "orientações em relação", "cond. do edif.", "cond. do "
            ]) or (("início:" in tl or "inicio:" in tl) and len(self.paragrafos[i]['texto']) < 80):
                indice_fim = i
                logger.info(f"[EDITAL] Fim da pauta: linha {i}")
                break

        self.indice_fim = indice_fim
        pauta = self.paragrafos[indice_inicio:indice_fim]
        logger.info(f"[EDITAL] Processando pauta: {len(pauta)} parágrafos")

        # Detecta separadores AGO/AGE: linha de underscores/hífens, ou
        # "EM CARÁTER (EXTRA)ORDINÁRIO" (aceita com/sem acento).
        def _eh_separador(texto):
            tn = _normalizar_texto(texto)  # sem acento, minúsculas
            if re.match(r'^[_\-]{5,}$', texto.strip()):
                return True
            # casa "ordinário" OU "extraordinário" + presença de "caráter"
            return 'carater' in tn and 'ordinari' in tn

        # Quando o marcador de início falhou, ficamos mais conservadores para evitar
        # que cabeçalho/título sejam capturados como itens (bug Theta).
        modo_estrito = not self.marcador_inicio_encontrado

        num_item       = 0
        ultimo_item    = None
        ultimo_subitem = None

        def _criar_item(titulo_raw, motivo=""):
            nonlocal num_item, ultimo_item, ultimo_subitem
            titulo_limpo = titulo_raw.rstrip(';').strip()
            if len(titulo_limpo) < 8:
                return None
            num_item += 1
            item = {
                "numero": num_item, "identificador": str(num_item),
                "titulo": titulo_limpo, "texto_completo": titulo_limpo,
                "subitens": []
            }
            pontos.append(item)
            ultimo_item = item
            ultimo_subitem = None
            logger.debug(f"[EDITAL] ITEM {num_item} {motivo}: {titulo_limpo[:60]}")
            return item

        for para in pauta:
            texto  = para['texto'].strip()
            nivel  = para.get('nivel_lista')
            eh_num = para.get('eh_lista_num', False)
            indent = para.get('indent', 0)
            negrito = para.get('negrito', False)

            if len(texto) < 3:
                continue

            # Separador AGO/AGE — reinicia contagem de itens
            if _eh_separador(texto):
                eh_underscore = bool(re.match(r'^[_\-]{5,}$', texto.strip()))
                if eh_underscore:
                    titulo_sep = "EM CARÁTER EXTRAORDINÁRIO"  # placeholder neutro
                else:
                    titulo_sep = texto.strip()
                # Deduplicar separadores adjacentes (caso clássico: '___' seguido de
                # 'EM CARÁTER EXTRAORDINÁRIO'). Se o último ponto também é separador,
                # apenas atualiza o título (preferindo o texto explícito) sem inserir
                # um novo separador.
                if pontos and pontos[-1].get('eh_separador'):
                    if not eh_underscore:
                        pontos[-1]['titulo'] = titulo_sep
                        pontos[-1]['texto_completo'] = titulo_sep
                else:
                    pontos.append({
                        "numero": None, "identificador": "SEPARADOR",
                        "titulo": titulo_sep, "texto_completo": titulo_sep,
                        "subitens": [], "eh_separador": True
                    })
                num_item = 0
                ultimo_item = None
                ultimo_subitem = None
                continue

            # ─── Sub-item decimal (2.1, 2.2, 3.1) — SEMPRE filho do último item ───
            m_dec = RE_SUB_DECIMAL.match(texto)
            if m_dec and ultimo_item is not None:
                prefixo = m_dec.group(1)
                titulo_sub = m_dec.group(2).rstrip(';').strip()
                if len(titulo_sub) >= 3:
                    subitem = {'prefixo': prefixo, 'texto': titulo_sub, 'alineas': []}
                    ultimo_item['subitens'].append(subitem)
                    ultimo_subitem = subitem
                    logger.debug(f"[EDITAL] Sub-item {prefixo} → ITEM {ultimo_item['numero']}: {titulo_sub[:50]}")
                continue

            # ─── Sub-item via lista Word nível 1 (indentado, numerado automaticamente) ───
            if nivel == 1 and eh_num and ultimo_item is not None:
                titulo_sub = texto.rstrip(';').strip()
                if len(titulo_sub) >= 3:
                    subitem = {'prefixo': '', 'texto': titulo_sub, 'alineas': []}
                    ultimo_item['subitens'].append(subitem)
                    ultimo_subitem = subitem
                    logger.debug(f"[EDITAL] Sub-item nível 1 → ITEM {ultimo_item['numero']}: {titulo_sub[:50]}")
                continue

            # ─── Alínea: indent > 0 + sub-item já aberto ───
            # Parágrafo indentado abaixo de um sub-item ativo é alternativa/alínea
            # do sub-item (caso clássico: 2.1 com (a) manter / (b) reduzir).
            if indent > 0 and ultimo_subitem is not None and len(texto) >= 5:
                ultimo_subitem.setdefault('alineas', []).append(texto.rstrip(';').strip())
                logger.debug(f"[EDITAL] Alínea de {ultimo_subitem.get('prefixo', '?')}: {texto[:50]}")
                continue

            # ─── Sub-item com indent>0 sem numeração explícita ───
            # Quando há item pai mas ainda não há sub-item, parágrafo indentado é sub-item.
            if indent > 0 and ultimo_item is not None and not eh_num:
                titulo_sub = texto.rstrip(';').strip()
                if len(titulo_sub) >= 3:
                    subitem = {'prefixo': '', 'texto': titulo_sub, 'alineas': []}
                    ultimo_item['subitens'].append(subitem)
                    ultimo_subitem = subitem
                continue

            # ─── ITEM principal: numeração explícita "1.", "2.", "3." ───
            m_num_explicit = re.match(r'^\s*(\d+)[\.\)]\s+(.+?)\s*$', texto)
            if m_num_explicit and indent == 0:
                _criar_item(m_num_explicit.group(2), motivo="(numerado)")
                continue

            # ─── ITEM principal: lista Word nível 0 OU negrito puro ───
            # Alíneas com L0+indent>0 já foram capturadas pela regra anterior
            # (que exige ultimo_subitem ativo). Aqui aceitamos L0+eh_num mesmo
            # com indent>0 — caso AGO+AGE onde Word indenta a lista por estilo
            # (FM-019, Iota).
            if (nivel == 0 and eh_num) or (negrito and indent == 0 and nivel is None):
                _criar_item(texto, motivo="(nivel0/negrito)")
                continue

            # ─── ITEM principal sem numeração — só aceito em modo NÃO-estrito ───
            # Caso clássico do edital de retificação (Theta): os itens da pauta
            # vêm como parágrafos sem prefixo numérico. Aceito apenas
            # quando o marcador de início casou (modo_estrito=False), pra evitar
            # que cabeçalho/título vazem como itens.
            if not modo_estrito and indent == 0 and len(texto) >= 15:
                _criar_item(texto, motivo="(parágrafo sem prefixo)")
                continue

        if not pontos:
            logger.warning("[EDITAL] Nenhum item estruturado — heurística de negrito.")
            for i, para in enumerate(pauta, 1):
                if para.get('negrito') and len(para['texto']) > 10:
                    pontos.append({
                        "numero": i, "identificador": str(i),
                        "titulo": para['texto'].rstrip(';').strip(),
                        "texto_completo": para['texto'].rstrip(';').strip(),
                        "subitens": []
                    })

        self.pontos = pontos
        n = sum(1 for p in pontos if not p.get('eh_separador'))
        logger.info(f"[EDITAL] ✓ {n} ponto(s) extraído(s)")
        for p in pontos:
            if p.get('eh_separador'):
                logger.info(f"  [---] {p['titulo']}")
            else:
                subs = p.get('subitens', [])
                sub_str = ""
                for s in subs:
                    prefix = s['prefixo'] if s.get('prefixo') else '  '
                    sub_str += f"\n      {prefix} → {s['texto'][:45]}"
                    for j, alinea in enumerate(s.get('alineas', [])):
                        letra = chr(ord('a') + j)
                        sub_str += f"\n           ({letra}) {alinea[:40]}"
                logger.info(f"  [{p['numero']}] {p['titulo'][:55]}{sub_str}")
        return pontos


    # Monta a ORDEM DO DIA formatada para o prompt da IA. Destaca a data oficial
    # e o nome do condomínio de forma inequívoca, e lista os sub-itens dentro do
    # item pai pra IA não os transformar em parágrafos soltos.
    def obter_texto_formatado(self) -> str:
        if not self.pontos:
            self.extrair_pontos()

        if not self.pontos:
            logger.warning("[EDITAL] Nenhum ponto extraído. Usando conteúdo bruto.")
            return self.conteudo_bruto[:3000]

        # ── Extrair data da reunião e nome do condomínio ──────────────────────
        data_reuniao   = None
        nome_condominio = None

        nums = {
            '01':'um','02':'dois','03':'três','04':'quatro','05':'cinco',
            '06':'seis','07':'sete','08':'oito','09':'nove','10':'dez',
            '11':'onze','12':'doze','13':'treze','14':'quatorze',
            '15':'quinze','16':'dezesseis','17':'dezessete','18':'dezoito',
            '19':'dezenove','20':'vinte','21':'vinte e um','22':'vinte e dois',
            '23':'vinte e três','24':'vinte e quatro','25':'vinte e cinco',
            '26':'vinte e seis','27':'vinte e sete','28':'vinte e oito',
            '29':'vinte e nove','30':'trinta','31':'trinta e um'
        }
        meses = {
            '01':'janeiro','02':'fevereiro','03':'março','04':'abril',
            '05':'maio','06':'junho','07':'julho','08':'agosto',
            '09':'setembro','10':'outubro','11':'novembro','12':'dezembro'
        }
        anos_ext = {
            '2024':'dois mil e vinte e quatro','2025':'dois mil e vinte e cinco',
            '2026':'dois mil e vinte e seis','2027':'dois mil e vinte e sete',
            '2028':'dois mil e vinte e oito','2029':'dois mil e vinte e nove',
            '2030':'dois mil e trinta',
        }

        for para in self.paragrafos:
            txt = para['texto']

            # Data no formato DD/MM/YYYY
            m = re.search(r'(\d{2})/(\d{2})/(\d{4})', txt)
            if m and not data_reuniao:
                dia, mes, ano = m.group(1), m.group(2), m.group(3)
                data_reuniao = {
                    'curta':   f"{dia}/{mes}/{ano}",
                    'extenso': f"{nums.get(dia, dia)} de {meses.get(mes, mes)} de {anos_ext.get(ano, ano)}",
                    'dia': dia, 'mes_nome': meses.get(mes, mes), 'ano': ano,
                }
                logger.info(f"[EDITAL] Data: {data_reuniao['curta']} → {data_reuniao['extenso']}")

            # Nome do condomínio: linha curta, maiúscula, contém "condomínio" ou "edifício"
            if not nome_condominio:
                t = txt.strip()
                if (len(t) < 80 and t.upper() == t
                        and ('CONDOM' in t or 'EDIF' in t)):
                    nome_condominio = t
                    logger.info(f"[EDITAL] Condomínio: {nome_condominio}")

        # ── Montar bloco de dados oficiais ────────────────────────────────────
        linhas = [
            "╔══════════════════════════════════════════════════════════╗",
            "║            DADOS OFICIAIS DO EDITAL                     ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            "⚠️  DATA OFICIAL DA REUNIÃO — USE ESTA. IGNORE DATAS DA TRANSCRIÇÃO.",
        ]

        if data_reuniao:
            linhas += [
                f"    Numérica  : {data_reuniao['curta']}",
                f"    Por extenso: {data_reuniao['extenso']}",
            ]
        else:
            linhas.append("    Data não encontrada — use ____")

        linhas.append("")

        if nome_condominio:
            linhas += [
                f"🏢  NOME DO CONDOMÍNIO: {nome_condominio}",
                "",
            ]

        linhas += [
            "═" * 60,
            "ORDEM DO DIA — estrutura EXATA do edital:",
            "▶ Cada ITEM e cada SUB-ITEM deve ter seu próprio parágrafo na ATA.",
            "▶ Sub-itens são identificados por número decimal (2.1, 2.3) ou traço (-).",
            "▶ Copie os títulos LITERALMENTE — não altere nem una os sub-itens.",
            "═" * 60,
        ]

        for ponto in self.pontos:
            if ponto.get('eh_separador'):
                linhas.append("")
                linhas.append("─" * 60)
                linhas.append(f"⚠️  SEÇÃO: {ponto['titulo'].upper()}")
                linhas.append("   (SEPARADOR DE SEÇÃO — não é item de pauta. Numeração reinicia em ITEM 1.)")
                linhas.append("─" * 60)
                linhas.append("")
                continue

            titulo = ponto.get('texto_completo') or ponto['titulo']
            subitens = ponto.get('subitens', [])

            linhas.append(f"ITEM {ponto['numero']}: {titulo}")

            # Sub-itens (com alíneas internas, se houver)
            for i, s in enumerate(subitens, 1):
                prefixo = s['prefixo'] if s.get('prefixo') else f"{ponto['numero']}.{i}"
                linhas.append(f"  {prefixo}: {s['texto']}")
                # Alíneas são alternativas de votação dentro do sub-item — listar como (a), (b), (c)
                for j, alinea in enumerate(s.get('alineas', [])):
                    letra = chr(ord('a') + j)
                    linhas.append(f"     ({letra}) {alinea}")

        linhas += [
            "═" * 60,
            f"Total: {sum(1 for p in self.pontos if not p.get('eh_separador'))} itens principais de pauta",
        ]

        return "\n".join(linhas)
    
    # Lista só os títulos dos pontos extraídos (usado pra conferência da IA).
    def obter_pontos_para_verificacao(self) -> List[str]:
        if not self.pontos:
            self.extrair_pontos()
        
        return [ponto['titulo'] for ponto in self.pontos]


# ============================================================================
# FUNÇÃO AUXILIAR
# ============================================================================

# Carrega o edital .docx mais recente de uma pasta e já extrai os pontos.
# Devolve um EditalReader pronto, ou None se a pasta não existe / está vazia.
def carregar_edital_da_pasta(pasta: str) -> Optional[EditalReader]:
    if not os.path.exists(pasta):
        logger.error(f"[EDITAL] Pasta não existe: {pasta}", exc_info=True)
        return None
    
    # Buscar arquivos .docx
    arquivos_docx = []
    for arquivo in os.listdir(pasta):
        if arquivo.lower().endswith('.docx') and not arquivo.startswith('~$'):
            caminho_completo = os.path.join(pasta, arquivo)
            arquivos_docx.append(caminho_completo)
    
    if not arquivos_docx:
        logger.warning(f"[EDITAL] Nenhum arquivo DOCX encontrado em: {pasta}")
        return None
    
    # Ordenar por data de modificação (mais recente primeiro)
    arquivos_docx.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    mais_recente = arquivos_docx[0]
    logger.info(f"[EDITAL] Mais recente: {os.path.basename(mais_recente)}")
    
    reader = EditalReader(mais_recente)
    resultado = reader.carregar()
    
    if resultado['sucesso']:
        reader.extrair_pontos()
        return reader

    return None


# ============================================================
# Validador de extração — sinaliza editais fora do padrão
# ============================================================

# Limiares heurísticos. Ajustáveis empiricamente conforme novos formatos aparecem.
NUM_ITENS_MAX_RAZOAVEL = 15
NUM_ITENS_MIN_RAZOAVEL = 1
RAZAO_OVERCAPTURE_LIMITE = 0.5  # >50% dos parágrafos da pauta viraram itens = suspeita


# Avalia a "saúde" da extração e devolve {ok, alertas, num_itens}. NÃO bloqueia
# o pipeline — só sinaliza (vai pro e-mail/log) pra um humano decidir se a ATA
# precisa de revisão extra. Alerta quando o marcador de início não casou, quando
# o nº de itens foge da faixa razoável, ou quando há sinal de overcapture.
def validar_extracao(reader: EditalReader) -> Dict:
    alertas: List[str] = []
    pontos_reais = [p for p in reader.pontos if not p.get('eh_separador')]
    num_itens = len(pontos_reais)

    # 1. Marcador "deliberar sobre" não casou — edital fora do padrão (caso Theta)
    if not reader.marcador_inicio_encontrado:
        alertas.append(
            "Marcador 'deliberar sobre os seguintes assuntos' (ou variante) NÃO foi "
            "identificado no edital. O sistema processou desde o primeiro parágrafo, "
            "o que pode ter incluído cabeçalho/título como itens da pauta."
        )

    # 2. Número de itens fora da faixa razoável
    if num_itens < NUM_ITENS_MIN_RAZOAVEL:
        alertas.append(f"Apenas {num_itens} item(ns) extraído(s) — possível falha de extração.")
    elif num_itens > NUM_ITENS_MAX_RAZOAVEL:
        alertas.append(
            f"{num_itens} itens extraídos — acima do esperado ({NUM_ITENS_MAX_RAZOAVEL}). "
            "Possível overcapture (parágrafos de outras seções viraram itens)."
        )

    # 3. Overcapture: razão pontos extraídos / parágrafos da pauta.
    # Só alerta quando o marcador de início TAMBÉM falhou — quando o marcador
    # foi encontrado, o filtro de início+fim já garante que só a seção da pauta
    # foi processada, então razão alta é esperada (cada parágrafo da pauta É um item).
    if (
        not reader.marcador_inicio_encontrado
        and reader.indice_inicio is not None
        and reader.indice_fim is not None
    ):
        paragrafos_pauta = reader.indice_fim - reader.indice_inicio
        if paragrafos_pauta > 0:
            razao = num_itens / paragrafos_pauta
            if razao > RAZAO_OVERCAPTURE_LIMITE and num_itens >= 5:
                alertas.append(
                    f"{num_itens} itens extraídos de {paragrafos_pauta} parágrafos "
                    f"({razao:.0%}) — proporção alta sugere overcapture."
                )

    return {
        "ok": len(alertas) == 0,
        "alertas": alertas,
        "num_itens": num_itens,
    }