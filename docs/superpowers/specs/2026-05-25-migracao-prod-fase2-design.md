# Fase 2 — Migração Plaud CLI para Produção

**Data:** 2026-05-25
**Status:** Design aprovado, pendente de implementação
**Autor:** Carlos Turina (com Claude)
**Branch:** `poc/migracao-cli` (será o branch a ser deployado)

## Contexto

O POC validou tecnicamente a migração de Selenium → CLI oficial do Plaud, e o Cliente (Administradora Exemplo) aprovou as ATAs geradas. Esta fase faz a virada para produção: o pipeline na VPS (`/opt/plaud/`, cron 2x/dia) passa a usar `@plaud-ai/cli` em vez de Selenium, mantendo VPN/SMB/IA/e-mail intactos.

A diferença operacional crítica: **a Fase 2 processa todos os editais pendentes da pasta SMB por execução** (não mais um único "mais recente"), com matching robusto de 4 níveis para associar áudio ↔ edital. Isso resolve o caso real do "Iota" não ter processado por causa do "Kappa" no mesmo dia.

## Decisões já tomadas

| Tema | Decisão |
|---|---|
| Estratégia de virada | Substituição direta com rollback rápido (`pipeline_legacy.py` no disco). Cliente recebe a nova ATA desde dia 1. |
| OAuth na VPS | SSH manual: `plaud login` → URL impressa → autoriza no Windows. |
| Matching áudio↔edital | Portar hierarquia de 4 níveis (data → título → transcript → eliminação → fallback). |
| Multi-edital por execução | Processa TODOS os pendentes da pasta `Editais/`, com limite máximo configurável (default 10). |
| Tracking de processados | JSON local em `/opt/plaud/processados.json` (sem mexer no SMB do cliente). |
| Monitoramento inicial | `EMAIL_DESTINATARIO` já é o Carlos — auto-monitorado. Trocará para o cliente final só na entrega oficial. |
| Quando rolar Fase 3 (limpeza Selenium) | Depois de 1-2 semanas estável em produção. Não nesta fase. |

## Escopo

### Arquivos a criar (3 novos)

- `src/ata_matcher.py` — Matching de 4 níveis
- `src/edital_scanner.py` — Lista editais pendentes na pasta SMB
- `src/processados_tracker.py` — Persistência JSON dos editais já processados

### Arquivos a substituir (versões atualizadas do POC)

- `pipeline.py` — Orquestrador novo (backup obrigatório como `pipeline_legacy_<data>.py`)
- `src/plaud_client.py` — Wrapper do CLI Plaud (do POC)
- `src/ata_verifier.py` — Verificador de omissões (do POC)
- `src/edital_reader.py` — Suporta retificação + AGO+AGE
- `src/ia_processor.py` — Truncamento 200k + modelo via env var + Regra 4 atualizada
- `src/email_sender.py` — Aceita `corpo_extra` HTML para alertas

### Arquivos intocados

- `src/vpn_manager.py`, `src/config.py` — sem mudança

### Arquivos a NÃO apagar nesta fase (rollback rápido)

- `src/webdriver_manager.py`, `src/plaud_login.py`
- `src/plaud_extractor.py`, `src/plaud_scraper.py`
- `pipeline_legacy_<data>.py` (cópia do pipeline.py antigo)

## Arquitetura

```
pipeline.py (NOVO)
    │
    ├─ ETAPA 0: Config + PlaudClient.verify_auth() (`plaud me`)
    │           → se falhar: e-mail [REAUTH NECESSÁRIO] + exit 2
    │
    ├─ ETAPA 1: VPNManager.conectar()           (sem mudança)
    ├─ ETAPA 2: SMBManager.montar()             (sem mudança)
    │
    ├─ ETAPA 3: EditalScanner.listar_pendentes()
    │           Walk recursivo em /mnt/cliente/.../Editais/
    │           Filtra os já registrados em processados.json
    │           Ordena por mtime (mais antigo primeiro)
    │           Limita a MAX_EDITAIS_POR_RUN (default 10)
    │
    ├─ ETAPA 4: PlaudClient.list_by_date_range(-7 a +1 dia)
    │           Pega lista de áudios candidatos
    │
    ├─ ETAPA 5: Para CADA edital pendente:
    │           ├─ AtaMatcher.match(edital, candidatos)
    │           ├─ EditalReader.carregar() + validar_extracao()
    │           ├─ PlaudClient.get_transcript() + get_summary()
    │           ├─ IAProcessor.processar() → ATA
    │           ├─ AtaVerifier.verificar() → omissões
    │           ├─ EmailSender.enviar(corpo_extra=alertas)
    │           └─ ProcessadosTracker.marcar_processado() ✓
    │
    └─ ETAPA 6: Cleanup (umount SMB, disconnect VPN)
                + relatório consolidado no log + e-mail-resumo se houver falhas
```

## Componentes novos

### `src/processados_tracker.py`

Persistência JSON com hash SHA256 do `.docx` como chave de unicidade.

```python
class ProcessadosTracker:
    def __init__(self, caminho: str = "/opt/plaud/processados.json"): ...
    def ja_processado(self, edital_path: str) -> bool: ...
    def marcar_processado(self, edital_path: str, audio_file_id: str, ata_path: str) -> None:
        """Adiciona entrada e salva atomicamente (write tmp + rename)."""
```

**Estrutura de cada entrada:**
```json
{
  "edital_hash": "<sha256>",
  "edital_nome": "13.05.2026 Alfa.docx",
  "data_processamento": "2026-05-25T14:30:00",
  "audio_file_id": "00000000000000000000000000000000",
  "ata_path": "/opt/plaud/saida/ATA_Alfa_20260525_143000.docx"
}
```

**Por que SHA256 do conteúdo?** Se o cliente reenviar o mesmo edital com nome diferente, não reprocessa. Se editar o edital (correção), o hash muda e reprocessa naturalmente.

### `src/edital_scanner.py`

Lista editais pendentes na pasta SMB.

```python
class EditalScanner:
    def __init__(self, pasta_raiz: str, tracker: ProcessadosTracker):
        self.pasta_raiz = pasta_raiz
        self.tracker = tracker

    def listar_pendentes(self, max_depth: int = 3, limite: int | None = None) -> list[str]:
        """Caminhos absolutos de .docx pendentes, ordenados por mtime (asc)."""
```

Reusa a lógica de walk recursivo do `encontrar_pasta_editais` do `pipeline.py` atual.

### `src/ata_matcher.py`

Matching áudio ↔ edital com 4 níveis de fallback.

```python
class AtaMatcher:
    def __init__(self, plaud_client: PlaudClient):
        self.plaud = plaud_client
        self._transcript_cache: dict[str, str] = {}
        self._pares_usados: set[str] = set()  # file_ids já casados nesta rodada

    def match(self, edital_path: str, candidatos: list[dict]) -> dict | None: ...
```

**Hierarquia:**

1. **Filtro por data** — extrai data do nome do edital (regex `\d{2}[\.\-]\d{2}[\.\-]\d{4}`), filtra candidatos pela mesma data (±1 dia de tolerância).
2. **Único candidato restante** após filtro de data? Retorna.
3. **Nível 2: nome do condomínio no TÍTULO do áudio**, usando `normalizar_para_busca` (lower + sem acento + sem pontuação).
4. **Nível 3: nome do condomínio no CONTEÚDO DO TRANSCRIPT** (primeiros 5000 chars). Download sob demanda, cacheado.
5. **Nível 4: eliminação por outros pares já casados** nesta rodada (não pode 2 editais → mesmo áudio).
6. **Fallback** com `log.warning`: primeiro candidato restante, ou `None` se nada sobrou.

**Funções utilitárias:**

- `extrair_nome_condominio_do_edital(filename)` — regex `^(\d{2}\.\d{2}\.\d{4})\s+(.+)\.docx$` e variantes.
- `normalizar_para_busca(texto)` — `unicodedata.normalize('NFKD').encode('ASCII','ignore').lower()` + remove pontuação.

## Tratamento de erros

| Falha | Ação |
|---|---|
| Plaud auth inválida | Aborta. E-mail `[REAUTH NECESSÁRIO] Plaud CLI`. exit 2. |
| VPN não conecta | Aborta. exit 3. |
| SMB não monta | Aborta. exit 4. |
| Pasta `Editais/` não encontrada | Aborta. exit 5. |
| `AtaMatcher.match()` retorna `None` | Loga warning, pula este edital, **NÃO marca como processado**. Próximo cron tenta de novo (talvez o áudio ainda esteja em processamento no Plaud). |
| `get_file_meta` retorna `transcript: processing` | Idem — pula, não marca. |
| IA falha (rate limit, timeout) | Loga error, pula, **NÃO marca**. |
| `EmailSender.enviar` falha | Loga warning, mas **MARCA como processado** (ATA já existe em disco; reenvio manual depois). |
| Exceção genérica em um edital | Captura, registra em `relatorio["falhas"]`, continua com o próximo edital. |

**Princípio:** uma falha em um edital nunca interrompe o processamento dos outros. O cron sempre tenta limpar todos os pendentes.

## Deploy na VPS (via Termius)

### A) Arquivos a copiar via SFTP do Termius

```
Local (Windows)                            → VPS (/opt/plaud/)
─────────────────────────────────────────    ─────────────────────────────
pipeline.py                                → pipeline.py
src/plaud_client.py                        → src/plaud_client.py
src/ata_verifier.py                        → src/ata_verifier.py
src/ata_matcher.py             (NOVO)      → src/ata_matcher.py
src/edital_scanner.py          (NOVO)      → src/edital_scanner.py
src/processados_tracker.py     (NOVO)      → src/processados_tracker.py
src/edital_reader.py           (atual.)    → src/edital_reader.py
src/ia_processor.py            (atual.)    → src/ia_processor.py
src/email_sender.py            (atual.)    → src/email_sender.py
requirements.txt               (atual.)    → requirements.txt
```

### B) Comandos no SSH (ordem)

**Antes de sobrescrever** — backups:

```bash
cd /opt/plaud
cp pipeline.py pipeline_legacy_$(date +%Y%m%d).py
cp src/edital_reader.py src/edital_reader.legacy.py
cp src/ia_processor.py src/ia_processor.legacy.py
cp src/email_sender.py src/email_sender.legacy.py
ls -la *legacy*
```

(Copiar arquivos novos via SFTP do Termius aqui.)

**Node.js 20 + Plaud CLI:**

```bash
node --version 2>/dev/null || echo "Node não instalado"

# Se não tiver Node 20+:
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

npm install -g @plaud-ai/cli
plaud --version
```

**OAuth do Plaud (interativo, 1x):**

```bash
plaud login
# CLI imprime URL → copia → abre no Windows → autoriza
plaud me   # deve retornar dados da conta da Administradora
```

**Setup Python + tracker:**

```bash
cd /opt/plaud
pip install -r requirements.txt
echo '[]' > /opt/plaud/processados.json
chmod 644 /opt/plaud/processados.json
mkdir -p /opt/plaud/logs
```

**Smoke test:**

```bash
python3 pipeline.py --test
# Esperado: valida credenciais, sai sem erro
```

**Primeira execução real (manual, antes do cron):**

```bash
python3 pipeline.py
# Em outra janela do Termius:
tail -f /opt/plaud/logs/pipeline_$(date +%Y%m%d)*.log
```

**Verificação do cron:**

```bash
crontab -l
# Confirma que aponta para /opt/plaud/pipeline.py
# (sem mudança esperada — só se hoje chama main.py, ajustar com `crontab -e`)
```

### C) Rollback (se algo der errado)

```bash
cd /opt/plaud
cp pipeline_legacy_<DATA>.py pipeline.py
cp src/edital_reader.legacy.py src/edital_reader.py
cp src/ia_processor.legacy.py src/ia_processor.py
cp src/email_sender.legacy.py src/email_sender.py
# Cron volta a usar Selenium imediatamente.
```

### D) Monitoramento dos próximos dias

```bash
# Logs do dia atual
tail -n 100 /opt/plaud/logs/pipeline_$(date +%Y%m%d)*.log

# Quais editais já foram processados
cat /opt/plaud/processados.json | python3 -m json.tool

# Token Plaud ainda válido?
plaud me

# Re-autenticar se necessário
plaud login
```

### E) Saneamento manual de problema pontual

**Se uma ATA sair errada para um edital específico:**

```bash
# 1. Edita processados.json e remove a entrada do edital problemático
nano /opt/plaud/processados.json

# 2. Próximo cron reprocessa esse edital automaticamente
```

## Configuração `.env` na VPS

**Novas variáveis** (todas opcionais com defaults sensatos):

```
PROCESSADOS_JSON_PATH=/opt/plaud/processados.json
MAX_EDITAIS_POR_RUN=10
PLAUD_IA_MODELO=o3-mini
```

**Variáveis a remover depois (Fase 3):**

- `PLAUD_EMAIL`, `PLAUD_SENHA` (Selenium não usa mais)

## Critérios de sucesso

- `python3 pipeline.py --test` passa na VPS após deploy
- Primeira execução manual processa N editais pendentes em <10 min, sem exceção fatal
- 1-2 semanas de cron 2x/dia sem alertas de erro
- Carlos valida amostralmente 5+ ATAs geradas e aprova qualidade equivalente ao POC

## Out of scope

- Notificação Slack/Telegram
- Dashboard web de monitoramento
- Reprocessamento automático em caso de falha (só via tracker manual)
- Suporte a outros condomínios além da Administradora
- Limpeza de arquivos Selenium — fica para Fase 3, após 1-2 semanas estáveis

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Token Plaud expira no meio da noite | `verify_auth` no início do cron + e-mail `[REAUTH]` → próximo cron pula até reauth manual. |
| Edital com formato totalmente novo (não-padrão, não-retificação, não-AGO+AGE) | Validador detecta (`marcador_inicio_encontrado=False` + alertas), e-mail destaca em amarelo. Carlos vê e decide se ajusta. |
| Múltiplos editais no mesmo dia + nomes similares (caso Kappa/Iota) | `AtaMatcher` níveis 1-4 + cache de pares já casados. Em último caso, fallback com log warning. |
| Cron rodando antes do Plaud ter publicado transcript | `get_file_meta` retorna `transcript: processing` → pula sem marcar → próximo cron tenta. |
| Edital duplicado por engano | SHA256 hash garante idempotência. |
| `processados.json` corrompido | Próximo `marcar_processado` recria estrutura (carrega vazia em falha de parse, loga warning). |
| Latência alta da OpenAI em horário de pico | Timeout no `_processar_com_gpt` + retry de até 2 vezes (SDK built-in) + skip se persistir. |

## Referências

- POC: spec [`docs/superpowers/specs/2026-05-19-migracao-cli-plaud-design.md`](docs/superpowers/specs/2026-05-19-migracao-cli-plaud-design.md)
- Plano POC: [`docs/superpowers/plans/2026-05-19-poc-cli-plaud.md`](docs/superpowers/plans/2026-05-19-poc-cli-plaud.md)
- Pipeline legacy (referência): `pipeline.py` na branch `claude/friendly-cori-7b6105` antes do refator

