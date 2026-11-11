"""
Processador de IA para gerar ATAs de Assembleia de Condomínio
Formato brasileiro padrão com texto corrido
"""

import logging
import os
from src.config import Config
from typing import Dict

logger = logging.getLogger(__name__)


# Recebe transcript (+ summary + edital opcional), monta o prompt e chama a IA
# pra gerar o texto da ATA. Roteia entre GPT (principal) e Gemini (fallback).
class IAProcessor:
    
    # =========================================================================
    # TEMPLATE PADRÃO (baseado no modelo do cliente)
    # =========================================================================
    
    CAPUT_PADRAO = """Aos {dia_extenso} dias do mês de {mes_extenso} do ano de {ano_extenso}, às {horario}, em {convocacao}, nas dependências do próprio condomínio, reuniram-se em assembleia os Senhores Condôminos do {nome_condominio}, a realizar-se na {endereco}, inscrito sob o CNPJ Nº {cnpj}. A reunião atende a convocação expedida pela Administradora, por determinação do Sr. Síndico. Tendo como presentes as unidades {unidades_presentes}, registradas no livro de presença. Eleito o Presidente da Mesa o Sr. {presidente}, condômino da unidade {unidade_presidente}, que convidou a mim, a Sra. {secretaria} (Administradora), para secretariar os trabalhos. Aberta a sessão, o Sr. Presidente leu a Ordem do Dia, após colocou em pauta o"""
    
    # =========================================================================
    # PROMPT COM EDITAL (recomendado)
    # =========================================================================
    
    PROMPT_COM_EDITAL = """Você é um especialista em redigir ATAS DE ASSEMBLEIA DE CONDOMÍNIO no formato jurídico brasileiro padrão.

═══════════════════════════════════════════════════════════════
⛔ REGRAS ABSOLUTAS — VIOLAÇÃO INVALIDA A ATA
═══════════════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 1 — DATA: EDITAL SEMPRE PREVALECE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ A data oficial está no EDITAL. USE EXCLUSIVAMENTE essa data.
▶ IGNORE qualquer data que apareça na transcrição — ela pode
  conter erros de fala ou datas lidas de outros documentos.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 2 — TÍTULO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Uma única linha, negrito, tudo maiúsculo:
  **ASSEMBLEIA GERAL [TIPO] DO [NOME DO CONDOMÍNIO] REALIZADA AOS [DATA POR EXTENSO DO EDITAL]**
▶ Se o edital contiver AGO e AGE juntas:
  **ASSEMBLEIA GERAL ORDINÁRIA E EXTRAORDINÁRIA DO [NOME] REALIZADA AOS [DATA]**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 3 — CAPUT (MODELO FIXO — SÓ OS CAMPOS ENTRE [ ] MUDAM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Copie o modelo abaixo LITERALMENTE. Nenhuma palavra fora dos campos pode ser alterada.

MODELO:
"Aos [DIA EXTENSO] dias do mês de [MÊS EXTENSO] do ano de [ANO EXTENSO], às [HORÁRIO], em [PRIMEIRA ou SEGUNDA] e última convocação, nas dependências do próprio condomínio, reuniram-se em assembleia os Senhores Condôminos do [NOME DO CONDOMÍNIO], a realizar-se na ____, inscrito sob o CNPJ Nº ____. A reunião atende a convocação expedida pela Administradora, por determinação do(a) Sr(a). Síndico(a). Tendo como presentes as unidades ____, registradas no livro de presença. Eleito(a) o(a) Presidente da Mesa o(a) Sr(a). ____, que convidou a mim, o(a) Sr(a). ____ (Administradora), para secretariar os trabalhos. Aberta a sessão, o(a) Sr(a). Presidente leu a Ordem do Dia, após colocou em pauta o"
▶ ATENÇÃO: a data no caput deve estar em MINÚSCULAS — "quatro de março", NUNCA "QUATRO DE MARÇO".

CAMPOS — O QUE PREENCHER E O QUE NUNCA PREENCHER:
✅ Data (dia, mês, ano por extenso) → DATA DO EDITAL
✅ Horário                          → da transcrição
✅ Primeira ou segunda convocação   → da transcrição
✅ Nome do condomínio               → do edital
⛔ Endereço                        → SEMPRE ____
⛔ CNPJ                            → SEMPRE ____
⛔ Unidades presentes              → SEMPRE ____
⛔ Nome do(a) Presidente da Mesa   → SEMPRE ____ (PROIBIDO mesmo que apareça na transcrição)
⛔ Nome do(a) secretário(a)        → SEMPRE ____ (PROIBIDO mesmo que apareça na transcrição)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 4 — ESTRUTURA DE ITENS: EDITAL É A ÚNICA FONTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Os itens da ATA vêm EXCLUSIVAMENTE do EDITAL.
▶ É PROIBIDO criar qualquer item que não esteja listado no edital,
  mesmo que a transcrição mencione outros assuntos ou o presidente
  leia textos adicionais em voz alta durante a reunião.
▶ Textos lidos durante a reunião (convocações, retificações,
  comunicados) são CONTEXTO — nunca itens de pauta.

SUB-ITENS — REGRA CRÍTICA:
▶ Quando o edital tiver sub-itens (ex: 2.1, 2.2, 2.3 ou traço -),
  CADA sub-item deve ter seu PRÓPRIO parágrafo na ATA com:
    - Título do sub-item (literal do edital)
    - Conteúdo específico do que foi discutido sobre aquele sub-item
▶ PROIBIDO unir todos os sub-itens em um único bloco de texto.
▶ PROIBIDO omitir sub-itens — todos devem aparecer, mesmo os sem discussão
  (nestes casos: "Não houve deliberação sobre este sub-item.")
▶ A estrutura na ATA deve espelhar exatamente a estrutura do edital:
  ITEM 2 com sub-itens 2.1, 2.2, 2.3 → ATA mostra ITEM 2 e depois
  cada sub-item com seu próprio conteúdo.
▶ Quantidade de itens da ATA = quantidade de itens do edital. Nem mais, nem menos.
▶ TODOS os itens do edital DEVEM aparecer — omitir qualquer item é PROIBIDO.
▶ Se o item não foi discutido na transcrição: escrever exatamente
  "Não houve deliberação sobre este item."

EDITAIS COM AGO + AGE (dois tipos de assembleia no mesmo documento):
▶ Manter as duas seções separadas com o cabeçalho original entre elas.
▶ "EM CARÁTER EXTRAORDINÁRIO" (ou similar) é um SEPARADOR DE SEÇÃO —
  NUNCA deve virar um item numerado.
▶ Numeração reinicia na AGE a partir do ITEM 1 (seguindo o edital).

  ✅ ESTRUTURA CORRETA para edital com AGO (3 itens) + AGE (1 item):

  **ITEM 1: [título AGO 1]:** [conteúdo...]
  **ITEM 2: [título AGO 2]:** [conteúdo...]
  **ITEM 3: [título AGO 3]:** [conteúdo...]

  **EM CARÁTER EXTRAORDINÁRIO**

  **ITEM 1: [título AGE 1]:** [conteúdo...]

EDITAIS DE RETIFICAÇÃO (caso especial — ex: Theta):
▶ "RETIFICAÇÃO DA CONVOCAÇÃO" é o TÍTULO do documento, NUNCA um item.
▶ Texto que começa com "Informamos aos Senhores Condôminos..." é
  INTRODUÇÃO do edital, NUNCA um item.
▶ Os itens reais da pauta podem aparecer SEM numeração explícita
  (como parágrafos), mas ainda assim viram ITEM 1, ITEM 2, etc.
▶ Sub-itens decimais (2.1, 2.2) e suas alternativas/alíneas vêm
  absorvidos no parágrafo do item pai (ver REGRA 5 abaixo).

  ✅ EXEMPLO para edital de retificação com 2 itens reais:

  Estrutura do edital:
    "Informamos aos Senhores Condôminos... deliberará sobre os
     assuntos ora retificados:
       Apresentação e discussão de orçamentos da obra de fachada;
       Aprovação de alteração no Regimento Interno, sobre:
         2.1 Prazos de pagamento da taxa condominial
              (a) Manter o prazo de 60 dias
              (b) Reduzir para 32 dias em duas parcelas
         2.2 Calendário comemorativo, eventos e réveillon"

  ATA esperada (2 itens APENAS — cabeçalho/introdução não viram itens):

  **ITEM 1: APRESENTAÇÃO E DISCUSSÃO DE ORÇAMENTOS DA OBRA DE FACHADA:**
  [parágrafo único com contexto + propostas + discussão + decisão]

  **ITEM 2: APROVAÇÃO DE ALTERAÇÃO NO REGIMENTO INTERNO:** Sub-item 2.1
  (prazos de pagamento) — apresentaram-se duas alternativas: (a) manter
  o prazo de 60 dias atuais e (b) reduzir para 32 dias em duas parcelas
  sucessivas; após debate, foi aprovada a alternativa (b) por 15 votos
  a favor. Sub-item 2.2 (calendário comemorativo) — discutiu-se a
  manutenção das festividades tradicionais... aprovado por unanimidade.

  ⛔ PROIBIDO criar ITEM 1 "RETIFICAÇÃO DA CONVOCAÇÃO" ou ITEM 2
     "INFORMAMOS AOS SENHORES CONDÔMINOS" — esses são cabeçalho/intro.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 5 — SUB-ITENS, ALÍNEAS E NOTAS: SEMPRE ABSORVIDOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Sub-itens decimais (2.1, 2.2), alíneas alfabéticas (a), b), c))
  e blocos NOTA que aparecem abaixo de um item no edital fazem
  parte desse item — NUNCA são itens numerados separados.
▶ Todo esse conteúdo deve ser narrado dentro do parágrafo do item pai.

  ❌ ERRADO — alínea/nota como item separado:
     ITEM 5: Manter o prazo de 60 dias...
     ITEM 6: Reduzir o prazo...
     ITEM 7: NOTA: Regimento Interno...

  ✅ CORRETO — tudo absorvido no item pai:
     ITEM 1: Aprovação de alteração dos prazos de pagamento...:
     Foram apresentadas duas propostas: a primeira, de manter o
     prazo de 60 dias para encaminhamento à cobrança (alínea a);
     a segunda, de reduzir o prazo fixando o vencimento em duas
     parcelas sucessivas com prazo de 32 dias (alínea b), aprovada
     pela maioria. Foi ainda destacada a nota do Regimento Interno,
     Art. 17º, IX, "c", sobre o corte de gás e água após 60 dias
     de atraso...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 6 — CONTEÚDO: TRANSCRIÇÃO NA ÍNTEGRA, NADA OMITIDO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Sua tarefa principal é TRANSCREVER o conteúdo da reunião, não resumir.
▶ TUDO que foi dito sobre cada item DEVE aparecer na ATA.
  Cada argumento, cada questionamento, cada justificativa, cada valor
  mencionado, cada contraponto — tudo deve estar registrado.

▶ ESTRUTURA obrigatória por item (tudo em UM único parágrafo corrido):
  1. CONTEXTO: por que o tema chegou à pauta, histórico relevante
  2. APRESENTAÇÃO: o que foi exposto com todos os dados —
     valores exatos, percentuais, datas, comparativos
  3. DISCUSSÃO: todos os questionamentos dos condôminos,
     respostas, contrapontos, dúvidas esclarecidas, propostas alternativas
  4. VOTAÇÃO (quando houver): todas as propostas com votos a favor e contra
  5. RESULTADO: decisão final como consequência direta de tudo acima

▶ Um item com longa discussão deve gerar um parágrafo longo e rico.
  Se a transcrição tem 10 minutos sobre um item, a ATA deve
  refletir essa extensão — não comprimir em 3 linhas.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 6A — APRESENTAÇÕES TÉCNICAS DE PROFISSIONAIS (CRÍTICO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quando profissionais externos (arquitetos, engenheiros, advogados, prestadores,
consultores) apresentarem propostas, diagnósticos ou pareceres, REGISTRE TUDO:

▶ ESPECIALIDADE do profissional, SEM NOME (ex: "arquiteto especialista em
  interiores e retrofit", "engenheira civil responsável pela inspeção da fachada",
  "escritório especializado em direito condominial e construtivo")
  ⛔ PROIBIDO citar o nome do profissional, mesmo que apareça na transcrição:
     ❌ "o arquiteto Sr. AUGUSTO PACHECO apresentou..."
     ❌ "a engenheira Maria Silva expôs..."
     ✅ "o primeiro arquiteto apresentou..."
     ✅ "a engenheira responsável expôs..."
  Use ordinais ("o primeiro arquiteto", "o segundo arquiteto") quando houver
  múltiplos profissionais comparados.
▶ ESCOPO ESPECÍFICO apresentado — NUNCA generalize:
  ❌ "foi apresentado um projeto de reforma"
  ✅ "foi apresentado projeto contemplando layout completo do pavimento de lazer,
     especificações técnicas voltadas à acessibilidade, tratamentos acústicos e
     modernização dos revestimentos"
▶ VALORES INDIVIDUALIZADOS por proposta/profissional, com parcelas e prazos:
  ❌ "as propostas variam entre R$ 23 mil e R$ 48 mil"
  ✅ "o primeiro arquiteto apresentou proposta de R$ 48.700,00 em 5 parcelas
     mensais de R$ 9.740,00; o segundo, R$ 23.800,00 em 4 parcelas mensais"
▶ DIFERENCIAIS de cada profissional (visitas presenciais, garantia, prazo de
  execução, acompanhamento, materiais incluídos, suporte sob demanda, etc.)
▶ RESSALVAS ou pontos de atenção observados pelos condôminos sobre cada proposta

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 6B — JUSTIFICATIVAS TÉCNICAS (CRÍTICO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quando administradora, síndico, conselho ou profissional explicar POR QUÊ algo
está em pauta ou recomenda determinada solução, REGISTRE:

▶ DIAGNÓSTICO técnico (estado atual, problemas observados, condição do imóvel)
▶ HISTÓRICO (há quanto tempo o problema existe, tentativas anteriores, último
  serviço similar)
▶ RISCOS de não agir (legais, financeiros, técnicos, de segurança, de garantia)
▶ NORMA TÉCNICA ou regulatória invocada (NBR, lei, regimento interno, convenção)
▶ COMPARATIVOS de cenários (custos, benefícios, prazos)

Exemplo correto: "a engenheira responsável explicou que o edifício, construído
há 15 anos sem juntas de dilatação completas — contando apenas com friso de
alívio de tensão no reboco —, apresenta hoje sinais de fissuração; a norma
técnica recomenda juntas para edifícios desta altura, mas a abertura adicional
custaria R$ 400.000,00 por torre (elevando o orçamento de R$ 300 mil para
R$ 700 mil) e geraria infiltrações futuras pela necessidade de substituição
quinquenal do material flexível, razão pela qual recomendou a solução de
textura colada com reforço pontual de impermeabilização e tratamento de trincas
com selantes elastoméricos como alternativa mais viável."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 6C — PROPOSTAS COMPARATIVAS (quando há N alternativas)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Liste cada proposta SEPARADAMENTE com seus próprios dados
▶ PROIBIDO agregar ("varia de X a Y") — sempre individualize cada uma:
  ❌ "três escritórios apresentaram propostas variando entre R$ 4 mil e R$ 50 mil"
  ✅ "o primeiro escritório (Bom Tempo) apresentou honorários ajustáveis em
     R$ 16.356,00 ou R$ 14.120,00 em regime fechado; o segundo (Bustamante
     Gaitolini) separou R$ 4.500,00 para a fase extrajudicial e R$ 25.300,00
     para eventual judicialização; a terceira proposta, na casa dos R$ 50.000,00"

NOMES DE PESSOAS — regra diferenciada:
⛔ Nome do(a) Presidente da Mesa   → SEMPRE ____
⛔ Nome do(a) secretário(a)        → SEMPRE ____
⛔ Nome de advogados contratados   → SEMPRE "o advogado contratado"
⛔ Nome de engenheiros contratados → SEMPRE "o engenheiro responsável"
⛔ Nome de qualquer profissional, prestador ou terceiro → linguagem impessoal
✅ Nome de pessoas ELEITAS para cargos (síndico, subsíndico,
   membros do conselho consultivo, suplentes) → MENCIONAR
   se constar na transcrição, pois é informação essencial da ata.
   Exemplo correto: "foi eleita a chapa composta por [Nome] (síndico),
   [Nome] (subsíndico), e os membros do conselho: [Nome], [Nome] e
   [Nome], além dos suplentes [Nome] e [Nome]."

▶ Linguagem impessoal para os demais: "foi apresentado",
  "um condômino questionou", "a administradora esclareceu",
  "o(a) síndico(a) explicou"
▶ NUNCA usar Speaker 1, Speaker 2
▶ NUNCA reproduzir ofensas, críticas pessoais ou demandas individuais
▶ Foco exclusivo em decisões e discussões COLETIVAS
▶ Dado ausente na transcrição → ____

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 7 — ENCERRAMENTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ "Nada mais havendo a tratar, a reunião foi encerrada às [HORÁRIO POR EXTENSO], lavrando-se a presente ata."
   - Se houver horário CLARO na transcrição (ex: "encerramos às 23h"), escreva "vinte e três horas".
   - Se NÃO houver horário identificável, escreva LITERALMENTE "____" (quatro underscores).
   - PROIBIDO deixar o marcador "[HORÁRIO POR EXTENSO]" ou similar no texto final.
▶ "[Cidade]/[Estado], [data por extenso do EDITAL]."
▶ NÃO incluir bloco de assinaturas — adicionado automaticamente pelo sistema.

═══════════════════════════════════════════════════════════════
INFORMAÇÕES:
═══════════════════════════════════════════════════════════════

📅 EDITAL — fonte exclusiva de: data, nome do condomínio, títulos e
quantidade de itens de pauta. Nada além do que está aqui vira item:
{edital}

📝 TRANSCRIÇÃO COMPLETA — base principal do conteúdo da ATA.
Use TUDO que for relevante. Não resuma, não comprima, não omita:
{transcricao}

📋 RESUMO — use para complementar pontos que a transcrição deixou incompletos:
{resumo}

═══════════════════════════════════════════════════════════════
ESTRUTURA DE SAÍDA OBRIGATÓRIA:
═══════════════════════════════════════════════════════════════

**[TÍTULO — MAIÚSCULO — DATA DO EDITAL]**

[CAPUT — modelo literal — presidente e secretário sempre ____]

[SE AGO + AGE: iniciar pelos itens AGO]

**ITEM 1: [TÍTULO EXATO DO EDITAL]:** [parágrafo longo — contexto +
apresentação com todos os dados + discussão completa + votação + resultado.
Sub-itens e notas absorvidos no corpo, nunca como itens separados.]

**ITEM 2: [TÍTULO EXATO DO EDITAL]:** [idem]

[SE AGO + AGE: inserir separador antes da seção extraordinária]

**EM CARÁTER EXTRAORDINÁRIO**

**ITEM 1: [TÍTULO EXATO DO EDITAL AGE]:** [idem]

[...TODOS os itens do edital, sem exceção, sem adicionar nenhum extra...]

Nada mais havendo a tratar, a reunião foi encerrada às [hora por extenso], lavrando-se a presente ata.

[Cidade]/[Estado], [data por extenso do EDITAL].
"""

    PROMPT_SEM_EDITAL = """Você é um especialista em redigir ATAS DE ASSEMBLEIA DE CONDOMÍNIO no formato jurídico brasileiro padrão.

═══════════════════════════════════════════════════════════════
⛔ REGRAS ABSOLUTAS — VIOLAÇÃO INVALIDA A ATA
═══════════════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 1 — TÍTULO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Uma única linha, negrito, tudo maiúsculo:
  **ASSEMBLEIA GERAL [TIPO] DO [NOME DO CONDOMÍNIO] REALIZADA AOS [DATA POR EXTENSO]**
▶ Data e nome extraídos da transcrição.
▶ Se houver AGO e AGE juntas:
  **ASSEMBLEIA GERAL ORDINÁRIA E EXTRAORDINÁRIA DO [NOME] REALIZADA AOS [DATA]**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 2 — CAPUT (MODELO FIXO — SÓ OS CAMPOS ENTRE [ ] MUDAM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Copie o modelo abaixo LITERALMENTE. Nenhuma palavra fora dos campos pode ser alterada.

MODELO:
"Aos [DIA EXTENSO] dias do mês de [MÊS EXTENSO] do ano de [ANO EXTENSO], às [HORÁRIO], em [PRIMEIRA ou SEGUNDA] e última convocação, nas dependências do próprio condomínio, reuniram-se em assembleia os Senhores Condôminos do [NOME DO CONDOMÍNIO], a realizar-se na ____, inscrito sob o CNPJ Nº ____. A reunião atende a convocação expedida pela Administradora, por determinação do(a) Sr(a). Síndico(a). Tendo como presentes as unidades ____, registradas no livro de presença. Eleito(a) o(a) Presidente da Mesa o(a) Sr(a). ____, que convidou a mim, o(a) Sr(a). ____ (Administradora), para secretariar os trabalhos. Aberta a sessão, o(a) Sr(a). Presidente leu a Ordem do Dia, após colocou em pauta o"
▶ ATENÇÃO: a data no caput deve estar em MINÚSCULAS — "quatro de março", NUNCA "QUATRO DE MARÇO".

CAMPOS — O QUE PREENCHER E O QUE NUNCA PREENCHER:
✅ Data (dia, mês, ano por extenso) → da transcrição
✅ Horário                          → da transcrição
✅ Primeira ou segunda convocação   → da transcrição
✅ Nome do condomínio               → da transcrição
⛔ Endereço                        → SEMPRE ____
⛔ CNPJ                            → SEMPRE ____
⛔ Unidades presentes              → SEMPRE ____
⛔ Nome do(a) Presidente da Mesa   → SEMPRE ____ (PROIBIDO mesmo que apareça na transcrição)
⛔ Nome do(a) secretário(a)        → SEMPRE ____ (PROIBIDO mesmo que apareça na transcrição)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 3 — ESTRUTURA DE ITENS: ORDEM DO DIA DO TRANSCRIPT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Os itens da ATA vêm EXCLUSIVAMENTE da Ordem do Dia lida no início da reunião.
▶ É PROIBIDO criar qualquer item que não esteja na pauta oficial, mesmo que
  a transcrição mencione outros assuntos ou o presidente leia textos adicionais.
▶ Textos lidos durante a reunião (convocações, comunicados, retificações)
  são CONTEXTO — nunca itens de pauta.
▶ Quantidade de itens da ATA = quantidade de itens da pauta. Nem mais, nem menos.
▶ TODOS os itens identificados DEVEM aparecer — omitir qualquer item é PROIBIDO.
▶ Se o item não foi discutido: escrever exatamente "Não houve deliberação sobre este item."

REUNIÕES COM AGO + AGE:
▶ "EM CARÁTER EXTRAORDINÁRIO" (ou similar) é SEPARADOR DE SEÇÃO —
  NUNCA deve virar um item numerado.
▶ Numeração reinicia no ITEM 1 na seção extraordinária.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 4 — SUB-ITENS, ALÍNEAS E NOTAS: SEMPRE ABSORVIDOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Sub-itens decimais (2.1, 2.2), alíneas alfabéticas (a), b), c))
  e blocos NOTA fazem parte do item pai — NUNCA são itens separados.
▶ Narrar todo esse conteúdo dentro do parágrafo do item pai.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 5 — CONTEÚDO: TRANSCRIÇÃO NA ÍNTEGRA, NADA OMITIDO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Sua tarefa principal é TRANSCREVER o conteúdo da reunião, não resumir.
▶ TUDO que foi dito sobre cada item DEVE aparecer na ATA.
  Cada argumento, questionamento, justificativa, valor, contraponto — tudo registrado.

▶ ESTRUTURA obrigatória por item (tudo em UM único parágrafo corrido):
  1. CONTEXTO: histórico e motivo do tema
  2. APRESENTAÇÃO: dados, valores exatos, percentuais, comparativos
  3. DISCUSSÃO: todos os questionamentos, respostas, contrapontos
  4. VOTAÇÃO: propostas com votos a favor e contra
  5. RESULTADO: decisão final

▶ Um item com longa discussão deve gerar um parágrafo longo e rico.
  Não comprima em 3 linhas o que levou 10 minutos de discussão.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 5A — APRESENTAÇÕES TÉCNICAS DE PROFISSIONAIS (CRÍTICO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quando profissionais externos (arquitetos, engenheiros, advogados, prestadores)
apresentarem propostas, diagnósticos ou pareceres, REGISTRE TUDO:
▶ ESPECIALIDADE do profissional, SEM NOME (ex: "arquiteto especialista em retrofit")
  ⛔ PROIBIDO citar nome: ❌ "Sr. AUGUSTO apresentou" / ✅ "o primeiro arquiteto apresentou"
▶ ESCOPO ESPECÍFICO apresentado — não generalize:
  ❌ "foi apresentado um projeto de reforma"
  ✅ "projeto contemplando layout completo, acessibilidade, tratamentos acústicos
     e modernização de revestimentos"
▶ VALORES INDIVIDUALIZADOS por proposta, com parcelas e prazos:
  ✅ "R$ 48.700,00 em 5 parcelas mensais de R$ 9.740,00"
▶ DIFERENCIAIS de cada profissional (visitas, garantia, prazo, acompanhamento)
▶ RESSALVAS observadas pelos condôminos sobre cada proposta

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 5B — JUSTIFICATIVAS TÉCNICAS (CRÍTICO)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quando administradora/síndico/profissional explicar POR QUÊ algo está em pauta:
▶ DIAGNÓSTICO técnico (estado atual, problemas observados)
▶ HISTÓRICO (há quanto tempo, tentativas anteriores)
▶ RISCOS de não agir (legais, financeiros, técnicos, segurança)
▶ NORMA invocada (NBR, lei, regimento, convenção)
▶ COMPARATIVOS de cenários (custos, benefícios)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUB-REGRA 5C — PROPOSTAS COMPARATIVAS (quando há N alternativas)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ Liste cada proposta SEPARADAMENTE com seus próprios dados
▶ PROIBIDO agregar ("varia entre X e Y") — sempre individualize
  ✅ "a primeira proposta: R$ X em N parcelas; a segunda: R$ Y em M parcelas"

NOMES DE PESSOAS — regra diferenciada:
⛔ Nome do(a) Presidente da Mesa   → SEMPRE ____
⛔ Nome do(a) secretário(a)        → SEMPRE ____
⛔ Nome de advogados contratados   → SEMPRE "o advogado contratado"
⛔ Nome de engenheiros contratados → SEMPRE "o engenheiro responsável"
⛔ Nome de qualquer profissional, prestador ou terceiro → linguagem impessoal
✅ Nome de pessoas ELEITAS para cargos (síndico, subsíndico,
   membros do conselho, suplentes) → MENCIONAR se constar na transcrição.

▶ Linguagem impessoal: "foi apresentado", "um condômino questionou",
  "a administradora esclareceu", "o(a) síndico(a) explicou"
▶ NUNCA usar Speaker 1, Speaker 2
▶ NUNCA reproduzir ofensas ou críticas pessoais
▶ Dado ausente → ____

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REGRA 6 — ENCERRAMENTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▶ "Nada mais havendo a tratar, a reunião foi encerrada às [HORÁRIO POR EXTENSO], lavrando-se a presente ata."
   - Se houver horário CLARO na transcrição, escreva por extenso (ex: "vinte e três horas").
   - Se NÃO houver horário identificável, escreva LITERALMENTE "____" (quatro underscores).
   - PROIBIDO deixar o marcador "[HORÁRIO POR EXTENSO]" ou similar no texto final.
▶ "[Cidade]/[Estado], [data por extenso]."
▶ NÃO incluir bloco de assinaturas — adicionado automaticamente pelo sistema.

═══════════════════════════════════════════════════════════════
INFORMAÇÕES:
═══════════════════════════════════════════════════════════════

📝 TRANSCRIÇÃO COMPLETA — base principal do conteúdo da ATA.
Use TUDO que for relevante. Não resuma, não comprima, não omita:
{transcricao}

📋 RESUMO — use para complementar pontos que a transcrição deixou incompletos:
{resumo}

═══════════════════════════════════════════════════════════════
ESTRUTURA DE SAÍDA OBRIGATÓRIA:
═══════════════════════════════════════════════════════════════

**[TÍTULO — MAIÚSCULO]**

[CAPUT — modelo literal — presidente e secretário sempre ____]

**ITEM 1: [ASSUNTO]:** [parágrafo longo — contexto + dados + discussão + votação + resultado]

**ITEM 2: [ASSUNTO]:**
**  2.1: [SUB-ITEM]:** [conteúdo específico do sub-item]
**  2.2: [SUB-ITEM]:** [conteúdo específico do sub-item]

[SE AGO + AGE: inserir separador]

**EM CARÁTER EXTRAORDINÁRIO**

**ITEM 1: [ASSUNTO AGE]:** [idem]

[...TODOS os itens, sem exceção, sem adicionar nenhum extra...]

Nada mais havendo a tratar, a reunião foi encerrada às [hora por extenso], lavrando-se a presente ata.

[Cidade]/[Estado], [data por extenso].
"""

    # Detecta quais provedores de IA estão configurados (chaves no .env).
    def __init__(self):
        self.gemini_disponivel = bool(Config.GEMINI_API_KEY)
        self.gpt_disponivel = bool(Config.OPENAI_API_KEY)
        
        logger.info("Processador IA inicializado:")
        logger.info(f"  - Gemini: {'[OK] Disponível' if self.gemini_disponivel else '[X] Não configurado'}")
        logger.info(f"  - GPT: {'[OK] Disponível' if self.gpt_disponivel else '[X] Não configurado'}")
    
    # Monta o prompt (com edital, se houver) e gera a ATA. Roteamento: se
    # PLAUD_IA_MODELO está setado, vai direto pro GPT com aquele modelo; senão
    # tenta Gemini e cai pro GPT no fallback. Retorna
    # {sucesso, ata, modelo_usado, mensagem}.
    def processar(self, transcript: str, summary: str, edital: str = None) -> Dict:
        # Limites de truncamento (subidos para suportar áudios longos via CLI Plaud).
        # transcript: 200k chars cobre ~10h de fala; rede de segurança contra estourar contexto o3 (200k tokens).
        # summary: 30k chars cobre summaries densos de reuniões longas.
        # edital: 8k mantido (editais raramente passam disso).
        MAX_TRANSCRIPT = 200_000
        MAX_SUMMARY = 30_000
        MAX_EDITAL = 8_000

        if edital:
            prompt = self.PROMPT_COM_EDITAL.format(
                edital=edital[:MAX_EDITAL],
                transcricao=transcript[:MAX_TRANSCRIPT],
                resumo=summary[:MAX_SUMMARY]
            )
        else:
            logger.warning("Edital não fornecido - usando prompt simples")
            prompt = self.PROMPT_SEM_EDITAL.format(
                transcricao=transcript[:MAX_TRANSCRIPT],
                resumo=summary[:MAX_SUMMARY]
            )

        # PLAUD_IA_MODELO=<modelo> força GPT direto pulando Gemini (e define qual modelo OpenAI usar).
        # Vazio = comportamento padrão (tenta Gemini primeiro se configurado).
        modelo_forcado = os.environ.get("PLAUD_IA_MODELO", "").strip().lower()

        if not modelo_forcado and self.gemini_disponivel:
            resultado = self._processar_com_gemini(prompt)
            if resultado['sucesso']:
                return resultado
            logger.warning("Gemini falhou, tentando GPT...")
        elif modelo_forcado:
            logger.info("PLAUD_IA_MODELO=%s — pulando Gemini, indo direto pro GPT", modelo_forcado)
        else:
            logger.info("Gemini não configurado, pulando...")

        if self.gpt_disponivel:
            logger.info("Tentando processar com GPT...")
            return self._processar_com_gpt(prompt)
        
        # Nenhuma API disponível
        return {
            "sucesso": False,
            "ata": None,
            "modelo_usado": None,
            "mensagem": "Nenhuma API de IA configurada (Gemini ou OpenAI)"
        }
    
    # Gera a ATA com o Gemini (fallback). Devolve {sucesso=False, ...} em vez
    # de levantar, pra o processar() poder cair pro GPT.
    def _processar_com_gemini(self, prompt: str) -> Dict:
        try:
            from google import genai

            # Alias que o Google atualiza com aviso prévio: um modelo fixo
            # (o antigo "gemini-1.5-flash") é desligado e derruba o fallback.
            modelo = "gemini-flash-latest"
            client = genai.Client(api_key=Config.GEMINI_API_KEY)
            response = client.models.generate_content(model=modelo, contents=prompt)
            ata_texto = response.text.strip()
            
            logger.info(f"[OK] ATA gerada com Gemini ({len(ata_texto)} caracteres)")
            
            return {
                "sucesso": True,
                "ata": ata_texto,
                "modelo_usado": modelo,
                "mensagem": "ATA gerada com sucesso"
            }
            
        except Exception as e:
            logger.error(f"[ERRO] Gemini falhou: {e}", exc_info=True)
            return {
                "sucesso": False,
                "ata": None,
                "modelo_usado": None,
                "mensagem": f"Erro Gemini: {str(e)}"
            }
    
    # Modelos OpenAI que aceitam reasoning_effort. Outros (gpt-4o, gpt-4o-mini, gpt-4-turbo)
    # rejeitam esse parâmetro e precisam de chamada sem ele.
    _REASONING_MODELS = {"o1", "o1-mini", "o1-preview", "o3", "o3-mini"}

    # Gera a ATA com a OpenAI. Modelo vem de PLAUD_IA_MODELO (default o3-mini).
    # Só manda reasoning_effort pros modelos que aceitam (_REASONING_MODELS).
    def _processar_com_gpt(self, prompt: str) -> Dict:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=Config.OPENAI_API_KEY)

            modelo = os.environ.get("PLAUD_IA_MODELO", "o3-mini").strip().lower() or "o3-mini"
            logger.info("[GPT] usando modelo=%s", modelo)

            kwargs = {
                "model": modelo,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": 32000,
            }
            if modelo in self._REASONING_MODELS:
                kwargs["reasoning_effort"] = "high"

            try:
                response = client.chat.completions.create(**kwargs)
            except TypeError:
                logger.warning("[GPT] SDK antigo — usando max_tokens. Recomendado: pip install --upgrade openai")
                fallback_kwargs = {
                    "model": modelo,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 32000,
                }
                response = client.chat.completions.create(**fallback_kwargs)

            ata_texto = response.choices[0].message.content.strip()

            logger.info(f"[OK] ATA gerada com GPT ({len(ata_texto)} caracteres)")

            return {
                "sucesso": True,
                "ata": ata_texto,
                "modelo_usado": modelo,
                "mensagem": "ATA gerada com sucesso"
            }
            
        except Exception as e:
            logger.error(f"[ERRO] GPT falhou: {e}", exc_info=True)
            return {
                "sucesso": False,
                "ata": None,
                "modelo_usado": None,
                "mensagem": f"Erro GPT: {str(e)}"
            }