"""
utils/llm.py
Chamadas de LLM (OpenAI) do Workflow 1: extracao de parametro e formatacao
de resposta em linguagem natural. Geracao de SQL Livre entra aqui depois
(ver Dashboard_Agente_Informacao.md, ADR-012).

Preco de referencia (checado 2026-08-18, ver Runbook no doc de arquitetura):
  gpt-5.6-luna:  $0.20 input / $1.20 output / $0.02 input-cached por 1M tokens
  gpt-5.6-terra: $2.00 input / $12.00 output / $0.20 input-cached por 1M tokens (so SQL Livre)

Cache de prompt da OpenAI e automatico (zero config) quando o prefixo do
request repete entre chamadas -- e exatamente o caso do grounding do SQL
Livre (os 2 documentos fonte, sempre o mesmo texto). Confirmado 2026-08-18:
2a chamada em diante reaproveita ~99.9% do prompt do cache (90% de desconto
no input cacheado) -- por isso custo_usd() sempre recebe tokens_cached
quando disponivel, senao super-estima o custo real em ~10x nesse caminho.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st
from openai import OpenAI

MODELO_WORKFLOW1 = "gpt-5.6-luna"
MODELO_SQL_LIVRE = "gpt-5.6-terra"

PRECO_POR_1M = {
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20, "cached_input": 0.02},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00, "cached_input": 0.20},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0, "cached_input": 0.02},
}


@dataclass
class RespostaLLM:
    texto: str
    modelo: str
    tokens_input: int
    tokens_output: int
    custo_usd: float


@st.cache_resource
def _openai_client() -> OpenAI:
    return OpenAI(api_key=st.secrets["openai"]["api_key"])


def custo_usd(modelo: str, tokens_input: int, tokens_output: int, tokens_cached: int = 0) -> float:
    preco = PRECO_POR_1M.get(modelo, {"input": 0.0, "output": 0.0, "cached_input": 0.0})
    tokens_input_normais = max(tokens_input - tokens_cached, 0)
    return (
        tokens_input_normais / 1_000_000 * preco["input"]
        + tokens_cached / 1_000_000 * preco.get("cached_input", preco["input"])
        + tokens_output / 1_000_000 * preco["output"]
    )


_TIPO_JSON = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "string": "string",
    "date": "string",
}


@dataclass
class ExtracaoParametros:
    valores: dict           # nome -> valor (None se nao encontrado na pergunta)
    faltando_obrigatorio: list[str] = field(default_factory=list)
    modelo: str = ""
    tokens_input: int = 0
    tokens_output: int = 0
    custo_usd: float = 0.0


def extrair_parametros(pergunta: str, parametros_spec: dict) -> ExtracaoParametros:
    """
    Extrai valores de parametro da pergunta em linguagem natural, via saida
    JSON estruturada (nao texto livre -- evita ter que parsear resposta
    ambigua do LLM). Se a entrada nao tem nenhum parametro, retorna sem
    chamar o LLM (mesmo espirito do ADR-013: nao gastar token a toa).
    """
    if not parametros_spec:
        return ExtracaoParametros(valores={})

    properties = {}
    required = []
    for nome, spec in parametros_spec.items():
        tipo = _TIPO_JSON.get(str(spec.get("tipo", "string")).lower(), "string")
        properties[nome] = {
            "type": [tipo, "null"],
            "description": spec.get("descricao", ""),
        }
        if spec.get("tipo") == "date":
            properties[nome]["description"] += " (formato YYYY-MM-DD, primeiro dia do mes se for so mes/ano)"
        required.append(nome)  # todos required no schema; null = "nao encontrado"
        if spec.get("obrigatorio", True):
            pass  # tratado depois de extrair, checando quais vieram null

    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }

    resp = _openai_client().chat.completions.create(
        model=MODELO_WORKFLOW1,
        messages=[
            {
                "role": "system",
                "content": (
                    "Extraia os parametros pedidos a partir da pergunta do usuario. "
                    "Se um parametro nao aparecer na pergunta, use null -- nunca invente "
                    "um valor. Nomes de igreja/cliente por extenso NAO sao um codigo "
                    "numerico valido -- se so o nome foi dado, deixe o campo numerico null."
                ),
            },
            {"role": "user", "content": pergunta},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "parametros", "schema": schema, "strict": True},
        },
    )

    valores = json.loads(resp.choices[0].message.content)
    faltando = [
        nome for nome, spec in parametros_spec.items()
        if spec.get("obrigatorio", True) and valores.get(nome) is None
    ]
    tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
    return ExtracaoParametros(
        valores=valores,
        faltando_obrigatorio=faltando,
        modelo=MODELO_WORKFLOW1,
        tokens_input=tin,
        tokens_output=tout,
        custo_usd=custo_usd(MODELO_WORKFLOW1, tin, tout),
    )


def formatar_resposta(pergunta: str, titulo_entrada: str, limitacoes: list[str], df: pd.DataFrame) -> RespostaLLM:
    """
    Turna o resultado bruto da query (DataFrame) em resposta em linguagem
    natural, curta e direta. Nao interpreta nem recalcula nada -- so
    verbaliza os numeros que a query (pre-aprovada) ja trouxe.

    Sempre esclarece qual definicao/classificacao foi usada quando o termo da
    pergunta pode ser ambiguo (ex: "clientes" pode ser cadastro no Superlogica
    OU igreja ativa no backend -- termos que colaboradores confundem, ver
    Dashboard_Agente_Informacao.md). O esclarecimento vem do titulo da
    entrada do catalogo e das `limitacoes` documentadas -- nunca inventado.
    """
    amostra = df.head(20).to_dict(orient="records")
    resp = _openai_client().chat.completions.create(
        model=MODELO_WORKFLOW1,
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce e o assistente de dados da InChurch. Responda em portugues, "
                    "direto, 1-3 frases. Use apenas os numeros fornecidos no resultado -- "
                    "nunca invente ou arredonde de forma enganosa. Formate valores em "
                    "reais como R$ X.XXX,XX quando fizer sentido.\n\n"
                    "IMPORTANTE: colaboradores da InChurch confundem termos parecidos "
                    "('clientes' vs 'igrejas ativas' vs 'igrejas na base', por exemplo) que "
                    "na verdade vem de classificacoes/fontes diferentes. Sempre que a "
                    "pergunta usar um termo desses, adicione uma frase curta entre parenteses "
                    "esclarecendo exatamente o que foi contado, baseada no titulo da consulta "
                    "e nas limitacoes fornecidas -- nunca invente a definicao, use so o que "
                    "foi passado no contexto. Exemplo do formato esperado: "
                    "'Temos 1.334 clientes (cadastro ativo no Superlogica, nao garante MRR "
                    "pagando hoje).'"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pergunta original: {pergunta}\n"
                    f"Consulta usada: {titulo_entrada}\n"
                    f"Limitacoes/definicao documentada desta consulta: {'; '.join(limitacoes) if limitacoes else '(nenhuma)'}\n"
                    f"Total de linhas no resultado completo: {len(df)}\n"
                    f"Amostra (ate 20 primeiras linhas -- se a pergunta for sobre quantidade/total, "
                    f"use o 'Total de linhas' acima, nao conte a amostra): {amostra}"
                ),
            },
        ],
    )
    texto = resp.choices[0].message.content
    tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
    return RespostaLLM(
        texto=texto,
        modelo=MODELO_WORKFLOW1,
        tokens_input=tin,
        tokens_output=tout,
        custo_usd=custo_usd(MODELO_WORKFLOW1, tin, tout),
    )
