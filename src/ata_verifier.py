"""Verificador de omissões em ATAs geradas.

Após a IA gerar a ATA, compara contra o transcript original com um modelo
barato (gpt-4o-mini) e reporta valores monetários, prazos, percentuais,
votos e deliberações que estão na transcrição mas NÃO aparecem na ATA.

O verificador NUNCA bloqueia a entrega da ATA — apenas anexa um relatório
de omissões pra revisão humana no e-mail e no log.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from src.config import Config

logger = logging.getLogger(__name__)


PROMPT_VERIFICACAO = """Você é um auditor de ATAs de assembleia de condomínio. Sua tarefa é detectar OMISSÕES.

Receberá: (1) a TRANSCRIÇÃO completa da reunião e (2) a ATA gerada a partir dela.

Liste APENAS itens que CLARAMENTE aparecem na TRANSCRIÇÃO mas NÃO foram registrados na ATA:
- Valores em R$ (montantes, descontos, parcelas)
- Prazos em dias/meses (vencimentos, prazos de execução, garantias)
- Percentuais (reajustes, multas, descontos)
- Votos (números a favor/contra, unanimidade ou maioria)
- Decisões/deliberações específicas (sorteios, aprovações, contratações, recusas)
- Nomes de profissionais OU especialidades apresentadas (arquiteto X, engenheiro Y)
- Propostas individualizadas (escopo, condições)

Para cada omissão, cite em até 1 linha o trecho da TRANSCRIÇÃO que prova a omissão.

Se nada relevante foi omitido, responda EXATAMENTE: NENHUMA OMISSAO

REGRA: não invente — só liste o que realmente está na transcrição e não está na ATA.

TRANSCRIÇÃO (recortada se necessário):
{transcript}

ATA GERADA:
{ata}
"""


# Auditor opcional de omissões. Roda DEPOIS da ATA pronta, com um modelo
# barato, e só reporta — nunca bloqueia a entrega (ver topo do módulo).
class AtaVerifier:

    DEFAULT_MODEL = "gpt-4o-mini"
    MAX_TRANSCRIPT_CHARS = 80_000  # cabe folgado no contexto do 4o-mini
    MAX_ATA_CHARS = 30_000

    # Modelo vem do .env (PLAUD_VERIFIER_MODELO) ou cai no default. Sem
    # OPENAI_API_KEY, marca como indisponível e vira no-op.
    def __init__(self, model: Optional[str] = None):
        self.model = model or os.environ.get("PLAUD_VERIFIER_MODELO", self.DEFAULT_MODEL).strip().lower()
        self.disponivel = bool(Config.OPENAI_API_KEY)
        if not self.disponivel:
            logger.warning("[VERIFIER] OPENAI_API_KEY ausente — verificador desabilitado.")

    # Compara a ATA contra o transcript e devolve
    # {tem_omissoes, relatorio, modelo}. Em qualquer falha (sem API, sem SDK,
    # erro de rede) devolve tem_omissoes=False com explicação — não bloqueia.
    def verificar(self, ata: str, transcript: str) -> dict:
        if not self.disponivel:
            return {"tem_omissoes": False, "relatorio": "Verificador desabilitado (sem OPENAI_API_KEY).", "modelo": None}

        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("[VERIFIER] openai SDK não instalado.")
            return {"tem_omissoes": False, "relatorio": "Verificador desabilitado (openai SDK ausente).", "modelo": None}

        prompt = PROMPT_VERIFICACAO.format(
            transcript=transcript[: self.MAX_TRANSCRIPT_CHARS],
            ata=ata[: self.MAX_ATA_CHARS],
        )

        try:
            client = OpenAI(api_key=Config.OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=2000,
                temperature=0.0,
            )
            texto = (resp.choices[0].message.content or "").strip()
            tem_omissoes = "NENHUMA OMISSAO" not in texto.upper()
            logger.info("[VERIFIER] modelo=%s | tem_omissoes=%s | tam_relatorio=%d chars",
                        self.model, tem_omissoes, len(texto))
            return {"tem_omissoes": tem_omissoes, "relatorio": texto, "modelo": self.model}
        except Exception as e:
            logger.warning("[VERIFIER] falhou (não bloqueia): %s", e)
            return {"tem_omissoes": False, "relatorio": f"Verificador falhou: {e}", "modelo": self.model}
