# Configuração da Cron e Como Usar os Testes

Guia operacional da automação na VPS: como **agendar** a execução automática
(e alterar o agendamento) e como **validar** o sistema com os modos de teste.

> Estrutura na VPS: o projeto fica em `/opt/plaud/`, com o virtualenv em
> `/opt/plaud/venv` e o ponto de entrada em `plaud_vps_producao.py`.
> O `run_automation.sh` é um wrapper que ativa o venv e chama o script principal.

---

## PARTE 1 — AGENDAMENTO VIA CRON

### Como funciona

A cron não chama o Python direto: ela chama o wrapper `run_automation.sh`, que
ativa o virtualenv, executa `plaud_vps_producao.py` e propaga o código de saída.
Isso garante que o cron rode no mesmo ambiente que uma execução manual.

```bash
# Conferir que o wrapper está executável
chmod +x /opt/plaud/run_automation.sh

# Rodar uma vez na mão, do mesmo jeito que a cron faria
bash /opt/plaud/run_automation.sh
echo "Exit code: $?"
```

### Configurar o agendamento

```bash
crontab -e          # abre o editor (escolha nano se perguntar)
```

Adicione a linha de agendamento no final do arquivo:

```cron
# Automação Plaud — todos os dias às 04:00
0 4 * * * /bin/bash /opt/plaud/run_automation.sh >> /opt/plaud/logs_producao/cron.log 2>&1
```

Sintaxe dos cinco campos:

```
┌─────────── minuto (0-59)
│ ┌───────── hora (0-23)
│ │ ┌─────── dia do mês (1-31)
│ │ │ ┌───── mês (1-12)
│ │ │ │ ┌─── dia da semana (0-7, 0 e 7 = domingo)
│ │ │ │ │
0 4 * * *  /bin/bash /opt/plaud/run_automation.sh >> /opt/plaud/logs_producao/cron.log 2>&1
```

- `>> .../cron.log` redireciona a saída para um log acumulado
- `2>&1` captura também os erros (stderr) no mesmo arquivo

Salve (`Ctrl+O` → Enter → `Ctrl+X`) e confirme:

```bash
crontab -l                  # deve listar a linha que você acabou de salvar
systemctl status cron       # o serviço precisa estar 'active (running)'
```

### Alterar o agendamento

**Vários horários por dia** — uma linha por horário:

```cron
0 4  * * * /bin/bash /opt/plaud/run_automation.sh >> /opt/plaud/logs_producao/cron.log 2>&1
0 14 * * * /bin/bash /opt/plaud/run_automation.sh >> /opt/plaud/logs_producao/cron.log 2>&1
```

**Apenas dias úteis** (segunda a sexta) — use `1-5` no campo de dia da semana:

```cron
0 4 * * 1-5 /bin/bash /opt/plaud/run_automation.sh >> /opt/plaud/logs_producao/cron.log 2>&1
```

> ⚠️ **Fuso:** a VPS roda em **UTC**. Brasília = UTC−3. Para rodar 01:00 BRT,
> agende `0 4 * * *` (04:00 UTC). Sempre confira com `date` antes de agendar.

**Testar com horário próximo:** agende 2-3 minutos à frente, salve, e acompanhe:

```bash
date                                          # ver a hora atual da VPS (UTC)
crontab -e                                    # ex.: se são 15:30, agende '32 15 * * *'
tail -f /opt/plaud/logs_producao/cron.log     # acompanha em tempo real
```

Depois de confirmar, volte para o horário definitivo.

### Monitorar execuções

```bash
tail -50 /opt/plaud/logs_producao/cron.log          # saída do wrapper/cron
ls -lt /opt/plaud/logs_producao/producao*.log | head # logs detalhados recentes
grep CRON /var/log/syslog | tail -20                # o cron disparou?
```

### Troubleshooting

| Sintoma | Verificação |
|---|---|
| Cron não dispara | `systemctl status cron`; se parado: `sudo systemctl enable --now cron` |
| Wrapper sem permissão | `ls -l /opt/plaud/run_automation.sh` → precisa do `x`; `chmod +x` |
| Roda mas falha | ver o último `producao*.log` para a etapa que quebrou |
| VPN não conecta no cron | o cron tem PATH mínimo; adicione `PATH=...` no topo do crontab e confirme `which openfortivpn` |

---

## PARTE 2 — COMO USAR OS TESTES

Antes de confiar no agendamento, dá pra validar cada parte do pipeline de forma
isolada. Todos os comandos abaixo rodam dentro do venv (`source venv/bin/activate`).

### 1. Smoke test do pipeline — `--test`

Valida o essencial **sem rodar o fluxo completo**: confere as credenciais
(`Config.validar_credenciais()`) e a autenticação do Plaud CLI
(`plaud me` via `verify_auth()`), e sai. **Não** conecta VPN/SMB nem chama a IA —
ou seja, não consome créditos nem gera ATA.

```bash
python3 plaud_vps_producao.py --test
```

Use sempre que mexer no `.env` ou desconfiar que o token do Plaud expirou.
É o primeiro teste a rodar depois de qualquer mudança de configuração.

### 2. Flags de execução parcial

O mesmo script aceita flags que permitem rodar só um pedaço do fluxo:

| Flag | Efeito |
|---|---|
| `--no-vpn` | Pula a etapa de VPN (útil quando você já está na rede ou testando local) |
| `--no-email` | Roda tudo, gera a ATA, mas **não envia e-mail** (dry-run de geração) |
| `--max N` | Processa no máximo `N` editais por execução (limita custo/tempo no teste) |
| `--test` | Smoke test descrito acima (ignora as demais flags) |

Exemplo — gerar a ATA de um único edital sem disparar e-mail:

```bash
python3 plaud_vps_producao.py --no-email --max 1
```

**Códigos de saída** (úteis para ler no `cron.log` ou em scripts):

| Código | Significado |
|---|---|
| `0` | Sucesso (ou smoke test passou) |
| `2` | Plaud CLI sem auth válida → rodar `plaud login` na VPS |
| `3` | Falha ao conectar a VPN |
| `4` | Falha ao conectar/listar o SMB |

### 3. Teste de e-mail — `diagnostico_email.py`

Envia um e-mail de teste isolado para confirmar que a configuração SMTP do `.env`
está correta (remetente, senha de app, destinatário). Não toca em Plaud, SMB nem IA.

```bash
python3 diagnostico_email.py                       # envia para EMAIL_DESTINATARIO do .env
python3 diagnostico_email.py --para outro@dominio.com   # envia para um endereço específico
```

Se a autenticação SMTP falhar, o script avisa exatamente qual variável conferir.

### 4. Diagnóstico de SMB — `diagnostico_smb.py`

Testa o acesso à pasta compartilhada via VPN + smbclient de forma isolada
(conectividade, listagem do share, leitura das pastas de editais/atas). Use quando
o pipeline retornar código `4` ou quando a infra do cliente mexer na rede.

```bash
python3 diagnostico_smb.py
```

### 5. Testes automatizados (unitários) — `pytest`

A lógica de negócio (matching edital↔áudio, parse de edital, tracker de
processados, cliente Plaud, etc.) tem cobertura de testes que roda offline,
sem depender de VPN, SMB ou rede:

```bash
python3 -m pytest tests/ -q
```

Rode antes de subir qualquer alteração de código para a VPS — é a rede de
segurança que garante que o comportamento do pipeline não regrediu.

---

### Ordem recomendada ao validar a VPS do zero

1. `python3 -m pytest tests/ -q` — a lógica está sã?
2. `python3 plaud_vps_producao.py --test` — credenciais e auth do Plaud ok?
3. `python3 diagnostico_email.py` — SMTP entrega?
4. `python3 diagnostico_smb.py` — enxerga a pasta do cliente?
5. `python3 plaud_vps_producao.py --no-email --max 1` — gera uma ATA de verdade?
6. Só então agendar/confiar na **cron** (Parte 1).

