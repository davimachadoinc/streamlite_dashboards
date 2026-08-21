"""
utils/esclarecimento.py
Mecanismo de esclarecimento por perguntas (ADR-015, Dashboard_Agente_
Informacao.md) -- quando o matching cai em "ambiguo", em vez de ir direto
pra tela de botoes, faz ate MAX_RODADAS perguntas de esclarecimento em
linguagem de negocio (LLM barato), re-embedando a pergunta enriquecida com
as respostas do usuario a cada rodada. Se nao resolver em MAX_RODADAS, cai
na tela de botoes (fallback existente).

Criterio de resolucao -- ESTABILIDADE, nao score absoluto (testado
2026-08-20): a primeira versao exigia score >= 0.90 pra parar, mas um teste
de ponta a ponta com respostas realistas mostrou que texto de conversa
(pergunta + historico de P&R) nunca chega perto de 0.90 contra uma frase
curta de catalogo, mesmo quando a classificacao ja convergiu pro candidato
certo. Trocado pra: resolve quando o candidato do topo se repete em 2
rodadas seguidas (nao muda mais com mais uma resposta) -- sinal de
convergencia, nao de "score alto o bastante".

Pedido explicito do usuario 2026-08-20: reverte o principio original do
ADR-013 de "nunca chamar LLM antes do usuario confirmar" -- aqui SIM se
chama LLM (ate 5x) antes de qualquer confirmacao, na faixa ambigua. Trade-off
consciente: mais chance de resolver sem a tela de botoes, ao custo de
algumas chamadas de LLM barato por pergunta ambigua.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import streamlit as st
from openai import OpenAI

from utils.matching import CatalogEntry, buscar_match, LIMIAR_AMBIGUO
from utils.llm import MODELO_WORKFLOW1, custo_usd

MAX_RODADAS_ESCLARECIMENTO = 5


@st.cache_resource
def _openai_client() -> OpenAI:
    return OpenAI(api_key=st.secrets["openai"]["api_key"])


@dataclass
class ParEsclarecimento:
    pergunta: str
    resposta: str


@dataclass
class PerguntaGerada:
    texto: str
    opcoes: list[str] = field(default_factory=list)
    tokens_input: int = 0
    tokens_output: int = 0
    custo_usd: float = 0.0


@dataclass
class ReavaliacaoEsclarecimento:
    candidatos: list[tuple[CatalogEntry, float]]  # ordenados por score desc, so acima de LIMIAR_AMBIGUO
    tokens_embedding: int
    custo_embedding_usd: float

    @property
    def top(self) -> tuple[CatalogEntry, float] | None:
        return self.candidatos[0] if self.candidatos else None


def montar_pergunta_enriquecida(pergunta_original: str, historico: list[ParEsclarecimento]) -> str:
    partes = [pergunta_original]
    for par in historico:
        partes.append(f"Esclarecimento -- pergunta: {par.pergunta} | resposta do usuario: {par.resposta}")
    return "\n".join(partes)


def reavaliar(pergunta_original: str, historico: list[ParEsclarecimento]) -> ReavaliacaoEsclarecimento:
    """Re-embeda a pergunta enriquecida com o historico de esclarecimento ate agora."""
    enriquecida = montar_pergunta_enriquecida(pergunta_original, historico)
    match = buscar_match(enriquecida)
    custo_embedding = custo_usd("text-embedding-3-small", match.tokens_embedding, 0)
    candidatos_acima_limiar = [
        (entry, score) for entry, score in match.candidatos if score >= LIMIAR_AMBIGUO
    ]
    return ReavaliacaoEsclarecimento(
        candidatos=candidatos_acima_limiar,
        tokens_embedding=match.tokens_embedding,
        custo_embedding_usd=custo_embedding,
    )


def gerar_pergunta_esclarecimento(
    pergunta_original: str,
    historico: list[ParEsclarecimento],
    candidatos: list[tuple[CatalogEntry, float]],
) -> PerguntaGerada:
    """
    Gera 1 pergunta curta, em linguagem de negocio (nao tecnica), mais de 2 a
    4 opcoes de resposta curtas e clicaveis (pedido do usuario 2026-08-21:
    botao em vez de texto livre sempre que der pra oferecer opcoes concretas
    -- o campo de digitar fica so pra quem clicar em "descrever com minhas
    proprias palavras", ver pages/1_Assistente.py). Nunca repete uma
    pergunta ja feita no historico.
    """
    candidatos_texto = "\n".join(
        f"- [{entry.id}] {entry.titulo} (fonte: {entry.fonte}) -- exemplos: "
        f"{'; '.join(entry.exemplos_pergunta[:3])}"
        for entry, _ in candidatos[:8]
    )
    historico_texto = (
        "\n".join(f"P: {p.pergunta}\nR: {p.resposta}" for p in historico)
        if historico else "(nenhuma pergunta feita ainda)"
    )

    schema = {
        "type": "object",
        "properties": {
            "pergunta": {
                "type": "string",
                "description": (
                    "Pergunta curta e objetiva, em portugues, em LINGUAGEM DE NEGOCIO "
                    "(nunca cite nomes tecnicos de tabela, campo, ID de consulta ou "
                    "jargao de banco de dados)."
                ),
            },
            "opcoes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Entre 2 e 4 respostas curtas e concretas (poucas palavras cada), "
                    "prontas pra virar botao clicavel, cobrindo as leituras mais "
                    "plausiveis entre os candidatos. Nunca inclua uma opcao de "
                    "'descrever com minhas palavras' aqui -- essa ja existe fixa na "
                    "interface."
                ),
            },
        },
        "required": ["pergunta", "opcoes"],
        "additionalProperties": False,
    }

    resp = _openai_client().chat.completions.create(
        model=MODELO_WORKFLOW1,
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce ajuda a desambiguar uma pergunta de BI da InChurch antes de "
                    "responde-la. Existem varias consultas candidatas no catalogo que "
                    "poderiam responder a pergunta do usuario, e voce precisa descobrir "
                    "qual delas e a certa. Gere uma pergunta curta e objetiva, em "
                    "LINGUAGEM DE NEGOCIO, mais de 2 a 4 opcoes de resposta curtas e "
                    "clicaveis que ajudem a diferenciar entre os candidatos abaixo. "
                    "Nunca repita uma pergunta que ja foi feita no historico."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pergunta original do usuario: {pergunta_original}\n\n"
                    f"Historico de esclarecimento ate agora:\n{historico_texto}\n\n"
                    f"Consultas candidatas que ainda podem ser a resposta certa:\n{candidatos_texto}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "esclarecimento", "schema": schema, "strict": True},
        },
    )
    dados = json.loads(resp.choices[0].message.content)
    tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
    return PerguntaGerada(
        texto=dados["pergunta"].strip(),
        opcoes=[o.strip() for o in dados.get("opcoes", []) if o and o.strip()],
        tokens_input=tin,
        tokens_output=tout,
        custo_usd=custo_usd(MODELO_WORKFLOW1, tin, tout),
    )
