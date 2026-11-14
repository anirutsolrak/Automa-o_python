# Atas de assembleia com IA

Automação em produção que gera a **ata de assembleia de condomínio** a partir da gravação da reunião. Roda sozinha numa VPS Linux, todo dia de madrugada, e entrega a ata pronta em Word, com horas de trabalho manual reduzidas a minutos.

> Versão sanitizada para portfólio: nomes de condomínios, pessoas, servidores e credenciais foram trocados ou removidos.

## O que acontece em cada execução

1. **VPN e servidor de arquivos.** Sobe a VPN da administradora (`openfortivpn`) e lista os editais novos na pasta compartilhada via `smbclient`.
2. **Leitura do edital.** Extrai a ordem do dia do `.docx` respeitando a hierarquia (itens, sub-itens 2.1/2.2, alíneas) e a divisão AGO/AGE. Usa os metadados do Word (nível de lista, recuo, negrito), não só o texto, porque cada administradora formata de um jeito.
3. **Áudio certo.** Encontra a gravação da reunião no Plaud em três níveis: data, nome do condomínio no título do áudio e nome do condomínio no começo da transcrição.
4. **Redação.** Manda edital e transcrição para a IA com um prompt de ata jurídica. Com `PLAUD_IA_MODELO` definido vai direto para a OpenAI naquele modelo; sem ele, tenta o Gemini e cai para a OpenAI. Um segundo modelo confere a ata contra a transcrição e aponta o que ficou de fora.
5. **Entrega.** Gera o `.docx` formatado, envia por e-mail e sobe para a pasta de atas concluídas. Cada edital é registrado por hash do conteúdo, então o mesmo edital nunca vira duas atas.

Um validador sinaliza no e-mail os editais fora do padrão (sem o marcador de início da pauta, ou com itens demais) para revisão humana. Ele não bloqueia a entrega.

## Estrutura

```
plaud_vps_producao.py   pipeline completo (o cron chama via run_automation.sh)
src/
  edital_reader.py      ordem do dia a partir do .docx + validador
  edital_scanner.py     editais pendentes na pasta SMB
  ata_matcher.py        casa edital e gravação
  plaud_client.py       CLI do Plaud (transcrições)
  ia_processor.py       prompt e chamada OpenAI / Gemini
  ata_verifier.py       confere a ata contra a transcrição (omissões)
  smb_client.py         smbclient (listar, baixar, subir)
  processados_tracker.py  editais já processados (JSON com escrita atômica)
tests/                  pytest; fixtures/editais/ tem editais fictícios em 6 formatos reais
diagnostico_*.py        checagens rápidas de SMB e e-mail na VPS
poc_*.py                provas de conceito usadas na migração para o CLI do Plaud
docs/                   specs e planos da migração, relatório entregue ao cliente
```

## Rodando

```bash
pip install -r requirements.txt
cp env_exemplo .env        # preencher credenciais
python plaud_vps_producao.py --test       # smoke test, sem IA
python plaud_vps_producao.py --no-email   # gera as atas sem enviar
```

Agendamento e testes na VPS: `CONFIGURACAO_CRON_E_TESTES.md`.

## Testes

```bash
python -m pytest -q
```

Os editais de teste são fictícios e gerados por `tests/fixtures/gerar_editais.py`. Cada um reproduz um formato que já apareceu em produção: retificação com itens numerados, retificação com sub-itens e alíneas, lista do Word com níveis, itens em negrito, AGO+AGE e AGE+AGO.

## Stack

Python 3, python-docx, OpenAI, Gemini (`google-genai`), smbclient, openfortivpn, cron em VPS Linux.
