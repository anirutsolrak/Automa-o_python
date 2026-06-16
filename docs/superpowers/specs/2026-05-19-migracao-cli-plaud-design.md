# Migração Plaud Selenium → CLI Oficial

**Data:** 2026-05-19
**Status:** Design aprovado, pendente de execução
**Autor:** Carlos Turina (com Claude)

## Contexto

O projeto ATA Automation hoje extrai dados do Plaud via scraping Selenium (login no site, navegação, leitura das abas Transcript/Summary, download de áudio). A Plaud lançou interfaces programáticas oficiais — CLI (`@plaud-ai/cli`) e servidor MCP — que entregam os mesmos dados via OAuth + comandos diretos.

A migração elimina o robô Selenium (fonte recorrente de falhas: mudanças no DOM, timeouts, login frágil) e simplifica o pipeline. Mantém intactos os componentes a montante (VPN, SMB, edital) e a jusante (IA, geração Word, e-mail).

## Decisão de interface

**CLI (`@plaud-ai/cli`)** escolhido sobre MCP HTTP direto e Embedded SDK / Transcription API. Razões:

- CLI é caminho oficial e documentado, com comandos diretos pros verbos que precisamos (`files`, `file`, `transcript`, `summary`, `me`).
- MCP HTTP é a mesma API por baixo, mas não é documentada como contrato estável — risco de quebra silenciosa.
- Transcription API / Embedded SDK serve a outro caso de uso (parceiros B2B que sobem áudio próprio); não acessa as gravações da conta da Administradora.

## Decisões de design já tomadas

| Tema | Decisão |
|---|---|
| Fonte de dados | CLI via `subprocess` do Python |
| Auth | OAuth interativo único (browser → `~/.plaud/tokens.json`); refresh provavelmente automático via `PLAUD_REFRESH_URL` (validar empiricamente) |
| Fonte da IA | `transcript + edital` (mantém atual) — summary do Plaud rejeitado como fonte primária por risco de omissão em documento jurídico |
| Truncamento de transcript | Subir de 20 000 chars para **200 000 chars** (suporta ~10h de áudio dentro do contexto do o3) |
| Modelo IA | Forçar **o3 com `reasoning_effort=high`** no POC; ordem em produção a decidir após POC |
| Matching áudio↔edital | Manter hierarquia atual de 4 níveis (título → transcript → eliminação → fallback); só troca fonte |
| Limpeza do Selenium | **Apenas após Fase 3** — Fase 2 mantém código antigo coexistindo |

## Escopo

### O que entra

- **`src/plaud_client.py`** — wrapper Python sobre o CLI Plaud
- **`src/ata_matcher.py`** — matching 4-níveis isolado, testável
- **`src/ata_verifier.py`** — addon de sanity check com summary do Plaud (Fase 4)
- **`poc_cli_local.py`** — script de validação local com edital em pasta do projeto
- Dependência externa: **Node.js 20+** e `@plaud-ai/cli` instalados na VPS de produção

### O que sai (após Fase 3)

- `src/webdriver_manager.py`
- `src/plaud_login.py`
- `src/plaud_extractor.py`
- `src/plaud_scraper.py`
- `main.py` (variante Selenium-only)
- `test_plaud_local.py`
- Dependências `selenium` e `webdriver-manager` do `requirements.txt`

### O que NÃO muda

- `src/vpn_manager.py` (VPNManager + SMBManager)
- `src/edital_reader.py`
- `src/ia_processor.py` (exceto o teto de truncamento)
- `src/email_sender.py`
- `src/config.py`
- `pipeline.py` orquestrador — mesma estrutura por etapas, apenas a Etapa 4 (Plaud) muda de fonte

## Arquitetura

```
pipeline.py (orquestrador)
    │
    ├─→ VPNManager           (sem mudança)
    ├─→ SMBManager           (sem mudança)
    ├─→ EditalReader         (sem mudança)
    │
    ├─→ PlaudClient          NOVO — substitui WebDriverManager + PlaudLogin
    │                              + PlaudExtractor + PlaudScraper
    │
    ├─→ AtaMatcher           NOVO — porta lógica do encontrar_audio_correspondente()
    │                              com fonte = PlaudClient
    │
    ├─→ IAProcessor          (truncamento aumentado para 200 000 chars)
    │
    ├─→ AtaVerifier          NOVO (Fase 4) — verifica omissões cruzando ATA vs summary
    │
    └─→ EmailSender          (anexa relatório de omissões se AtaVerifier reportar)
```

## Componente: `PlaudClient`

Wrapper Python que encapsula chamadas `subprocess` ao CLI. Toda comunicação com o Plaud passa por esta classe.

### Interface pública

```python
class PlaudClient:
    def __init__(self, cli_path: str = 'plaud'): ...

    def verify_auth(self) -> bool:
        """Retorna True se `plaud me` retornar exit 0."""

    def list_recent(self, days: int = 7, page_size: int = 50) -> list[dict]:
        """`plaud recent --days N --page-size M`."""

    def list_by_date_range(self, date_from: str, date_to: str) -> list[dict]:
        """`plaud files --from YYYY-MM-DD --to YYYY-MM-DD --page-size 100`."""

    def get_file_meta(self, file_id: str) -> dict:
        """`plaud file <id>` → dict com flags transcript/summary disponíveis."""

    def get_transcript(self, file_id: str) -> str:
        """`plaud transcript <id>` → texto bruto."""

    def get_summary(self, file_id: str) -> str:
        """`plaud summary <id>` → markdown bruto."""
```

### Parsing dos outputs

Não há flag `--json` no CLI. Os formatos confirmados empiricamente em 2026-05-19 são:

**`plaud files` (tabela alinhada):**
```
  ID                                  NAME                              DATE          DURATION
  ───────────────────────────────────────────────────────────────────────────────────────────
  00000000000000000000000000000000    13.05.2026 Alfa                2026-05-14    3h08m
```

Parser usa split por `\s{2,}` em linhas que casam regex `^[a-f0-9]{32}\s`. Footer `Page N` ignorado. `DURATION` parseado para segundos (`(\d+)h(\d+)m`, `(\d+)m(\d+)s`, `(\d+)s`).

**`plaud file <id>` (key:value):**
```
File Details:

  id:           00000000000000000000000000000000
  name:         05.05.2026 Beta
  created_at:   2026-05-06T13:49:48
  start_at:     2026-05-05T22:04:02
  duration:     8m51s
  serial_number: 888316753912013887
  audio:        available
  transcript:   available
  summary:      available
```

Parser regex `^\s+(\w+):\s+(.+)$`. Os campos `transcript: available` e `summary: available` são usados pelo pipeline para decidir se a gravação está pronta — se algum estiver `processing`, o pipeline pula a gravação e tenta de novo no próximo cron.

**`plaud transcript <id>`:** texto puro com cabeçalho `Transcript: <título>` e linhas `[MM:SS - MM:SS] Speaker N: texto`. Retorna o texto completo sem manipulação.

**`plaud summary <id>`:** markdown puro com cabeçalho `Summary: <título>`. Retorna sem manipulação.

### Tratamento de erro

`subprocess.run` com `check=False, text=True, encoding='utf-8', errors='replace'`. Códigos de saída do CLI documentados: 0=ok, 1=erro, 2=auth falhou, 3=rede, 4=timeout.

`verify_auth()` retorna `False` em qualquer exit não-zero. Os outros métodos levantam `PlaudCLIError(returncode, stderr)` em exit não-zero, exceto quando o pipeline pode tolerar (ex: `get_transcript` em arquivo ainda processando devolve `None`).

### Encoding no Windows

PowerShell pode usar CP1252 por padrão. Forçar UTF-8 no subprocess (`encoding='utf-8'`) e setar `$env:PYTHONIOENCODING='utf-8'` no script POC se houver garbled chars em logs.

## Componente: `AtaMatcher`

Porta a lógica de [`encontrar_audio_correspondente`](src/plaud_extractor.py) (4 níveis), com fonte = `PlaudClient` em vez do DOM Selenium.

### Interface

```python
class AtaMatcher:
    def __init__(self, plaud_client: PlaudClient):
        self.plaud = plaud_client
        self._transcript_cache: dict[str, str] = {}

    def match(
        self,
        edital_filename: str,
        edital_date: str,            # 'YYYY-MM-DD'
        candidatos: list[dict],      # gravações do dia, vindas do PlaudClient
    ) -> dict | None:
        """Retorna a gravação que melhor casa com o edital, ou None se não houver."""
```

### Hierarquia de 4 níveis (preservada)

1. **Nome do condomínio no TÍTULO do áudio** (via `normalizar_para_busca` — remove acentos, pontuação, caixa)
2. **Nome do condomínio no CONTEÚDO DO TRANSCRIPT** (primeiros 5000 chars; transcript baixado sob demanda e cacheado em `self._transcript_cache`)
3. **Eliminação** — único candidato restante após filtros
4. **Fallback** — primeiro candidato do dia, com log de aviso

### Mudanças vs implementação atual

- Cache de transcript vive no `AtaMatcher`, não em campo `_transcript_cache` dentro do dict do áudio. Mais limpo, e o cache morre com a instância.
- Funções `normalizar_para_busca` e `extrair_nome_condominio_do_edital` são portadas sem mudança de comportamento.
- Matcher é função pura testável: dado um conjunto fixo de `candidatos` e um `PlaudClient` mockado, o resultado é determinístico.

## Componente: `AtaVerifier` (Fase 4 — addon opcional)

Executado depois do `IAProcessor.processar`. Faz uma chamada extra à IA cruzando a ATA gerada com o summary do Plaud para detectar omissões.

### Prompt

```
Você recebe uma ATA gerada e o resumo da reunião correspondente.
Liste APENAS decisões, eleições e votações que aparecem no resumo
mas NÃO aparecem na ATA. Para cada item omitido, cite o trecho do resumo.

Se nada foi omitido, responda exatamente: NENHUMA OMISSAO

RESUMO:
{summary}

ATA GERADA:
{ata}
```

### Comportamento

- Modelo: Gemini-1.5-flash ou o3-mini (barato; ~US$ 0,005 por chamada).
- Saída esperada: `NENHUMA OMISSAO` ou lista markdown de omissões com citação.
- Retorno do `verificar()`: `{'tem_omissoes': bool, 'relatorio': str}`.
- **Não bloqueia** a entrega da ATA. Apenas anexa o relatório no log e no corpo do e-mail (bloco `⚠️ Possíveis omissões detectadas`).

## Plano em fases

| Fase | Escopo | Critério de saída |
|---|---|---|
| **1 — POC local** | `PlaudClient` + `poc_cli_local.py` + ajuste de truncamento no IAProcessor. Rodar contra áudio Alfa 3h e edital local. | ATA do Alfa aprovada manualmente pelo Carlos (7 regras do prompt atendidas) |
| **2 — Migração produção** | Substituir Etapa 4 do `pipeline.py` (PlaudExtractor/Login/Driver) por `PlaudClient` + `AtaMatcher`. VPN/SMB/EditalReader/Email intactos. Instalar Node.js 20+ e `@plaud-ai/cli` na VPS. | 1 semana de cron 2x/dia sem incidente, comparando ATAs geradas com produção pré-migração |
| **3 — Limpeza** | Apagar `webdriver_manager.py`, `plaud_login.py`, `plaud_extractor.py`, `plaud_scraper.py`, `main.py`, `test_plaud_local.py`. Remover `selenium`, `webdriver-manager` do `requirements.txt`. | `pipeline.py --test` passa; cron continua estável |
| **4 — `AtaVerifier`** | Addon de sanity check. Plugado no fim do pipeline; e-mail enriquecido com relatório de omissões. | Verificação roda em todas as execuções; falsos positivos < 20% após 1 semana |

## Plano detalhado do POC (Fase 1)

**Branch:** `poc/migracao-cli` (a partir de `main`)

**Pré-requisitos locais (já satisfeitos):**
- Node.js instalado, `@plaud-ai/cli` global, `plaud login` feito
- Edital salvo em `editais_local/Edital_Alfa.docx`
- `OPENAI_API_KEY` configurada no `.env` local

**Arquivos novos:**
- `src/plaud_client.py` — wrapper conforme Seção `Componente: PlaudClient`
- `poc_cli_local.py` (raiz) — script de teste:
  1. Lê `editais_local/Edital_Alfa.docx` via `EditalReader`
  2. Chama `PlaudClient.get_file_meta('00000000000000000000000000000000')` para confirmar disponibilidade
  3. Chama `PlaudClient.get_transcript(...)` e `get_summary(...)`
  4. Chama `IAProcessor.processar(transcript, summary, edital)` com Gemini desabilitado (força o3)
  5. Salva ATA em `output/Alfa_<timestamp>.docx`
  6. Imprime métricas: chars de transcript/summary/edital, tokens estimados, tempo total, modelo usado

**Ajustes mínimos em código existente:**
- `src/ia_processor.py`: trocar `transcript[:20000]` por `transcript[:200000]` e `summary[:8000]` por `summary[:30000]`. Comentário curto explicando o porquê.
- `src/ia_processor.py`: adicionar suporte a forçar modelo via env var `PLAUD_IA_MODELO=o3` (POC seta para `o3`, produção decide depois).

**Fora do escopo POC:**
- VPN/SMB (edital em pasta local)
- AtaMatcher (file_id hardcoded no script POC)
- AtaVerifier (Fase 4)
- E-mail (POC salva ATA em disco)
- Apagar arquivos Selenium (deixar parados no branch)

## Token lifecycle

- **Detecção:** `pipeline.py` chama `PlaudClient.verify_auth()` no início da Etapa 4. Se `False` → log com `[CRÍTICO] Plaud CLI sem auth válida`, envia e-mail com assunto `[REAUTH NECESSÁRIO] Plaud CLI` e finaliza com `sys.exit(2)`.
- **Re-auth:** manual via SSH na VPS: `plaud login`, copiar URL impressa, abrir em browser local, autorizar. Token persiste em `~/.plaud/tokens.json` do usuário que rodar o cron.
- **Refresh automático:** `PLAUD_REFRESH_URL` está documentada nas env vars do CLI, sugerindo refresh interno. Validar empiricamente — se passar 30 dias rodando sem re-auth, considerar resolvido.

## Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Token expira no meio da noite | Média | E-mail dispara em `verify_auth() == False`; próximo cron pula até reauth manual |
| Update do `@plaud-ai/cli` quebra formato | Baixa | Pin versão no comando de instalação (`npm install -g @plaud-ai/cli@<v>`); revisar antes de subir versão |
| Transcript de 6h+ estoura contexto o3 (200k tokens) | Baixa | Truncamento em 200 000 chars como rede de segurança; log alerta quando aproxima do limite |
| Plaud ainda não publicou transcript quando cron roda | Média | `get_file_meta` retorna flag `transcript: processing`; pipeline pula a gravação e tenta no próximo cron |
| OAuth interativo difícil de fazer na VPS headless | Baixa | CLI suporta copiar URL do terminal; reauth é raro (provavelmente mensal+) |
| Gemini-1.5-flash não atende as 7 regras do prompt | Média | POC força o3; decisão de produção depende do resultado |

## Critérios de sucesso

### POC (Fase 1)
- Script `poc_cli_local.py` executa sem erro até o fim
- ATA gerada em `output/` é um `.docx` válido
- Revisão manual confirma:
  - Data do edital (13/05/2026) prevalece sobre qualquer data falada no áudio
  - Todos os 4 itens do edital aparecem na ATA, na ordem do edital
  - Item 4 (alteração do Regimento) referencia 7.13.30 e 7.13.32 corretamente
  - Sub-itens absorvidos em parágrafo do item pai (não viram itens separados)
  - Nenhum nome de Presidente/Secretário aparece no caput (sempre `____`)
  - Texto longo e fiel à reunião — não comprimido em 3 linhas

### Migração produção (Fase 2)
- 1 semana de cron 2x/dia sem alertas de erro
- Comparação amostral de 5 ATAs geradas pré e pós-migração: equivalentes em qualidade

## Out of scope explícito

- Migração para MCP HTTP direto (decidido contra; CLI é mais estável)
- Reformular `IAProcessor` além do truncamento (escopo separado se necessário)
- Reformular `EditalReader` ou estrutura de pastas SMB
- Multi-tenant / múltiplos clientes (Administradora é o único cliente atual)
- Substituir o3 ou Gemini por outro provedor

## Referências

- Doc CLI Plaud: https://docs.plaud.ai/documentation/plaud_app/cli
- Doc MCP Plaud: https://docs.plaud.ai/documentation/plaud_app/mcp
- Lógica de matching a portar: [src/plaud_extractor.py](src/plaud_extractor.py) — função `encontrar_audio_correspondente`
- Prompt da IA (intacto, exceto truncamento): [src/ia_processor.py](src/ia_processor.py)
- Áudio de validação do POC: `13.05.2026 Alfa` — Plaud file_id `00000000000000000000000000000000`, duração 3h08m
- Edital de validação do POC: [editais_local/Edital_Alfa.docx](editais_local/Edital_Alfa.docx) — AGE 13/05/2026, 4 itens

