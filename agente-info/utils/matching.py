"""
utils/matching.py
Motor de matching pergunta -> entrada do catalogo (bi_data.catalogo_queries).

Embeddings via OpenAI (text-embedding-3-small), busca por similaridade de
cosseno em numpy (catalogo pequeno, sem VECTOR_SEARCH/indice vetorial -- ver
ADR-011 em [BI] Dashboard_Agente_Informacao.md).

Trava de 2 patamares antes de qualquer chamada ao LLM de chat (ver ADR-013):
  score >= LIMIAR_CONFIANTE  -> match direto, segue pra extracao de parametro
  LIMIAR_AMBIGUO <= score < LIMIAR_CONFIANTE -> mostra sugestoes, espera confirmacao
  score < LIMIAR_AMBIGUO     -> sem match, nenhuma chamada de LLM
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import numpy as np
import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery
from openai import OpenAI

CATALOGO_TABLE = "business-intelligence-467516.bi_data.catalogo_queries"
EMBEDDING_MODEL = "text-embedding-3-small"

# Calibrados em 2026-08-18 com 8 perguntas de teste (ver ADR-013) -- ajustar
# conforme o log de uso real acumular volume.
LIMIAR_CONFIANTE = 0.65
LIMIAR_AMBIGUO = 0.55

# Calibrado em 2026-08-19 com 7 perguntas de teste (1 caso alvo + 6 controles,
# ver Dashboard_Agente_Informacao.md): quando os 2 melhores candidatos vem de
# fontes de dado DIFERENTES (Superlogica vs Backend) com score proximo, a
# pergunta pode ter duas leituras validas (ex: "contratado" vs "realmente
# ativo") -- sempre pergunta em vez de escolher calado, mesmo que o top-1
# sozinho já fosse "confiante".
GAP_AMBIGUIDADE_FONTE = 0.10


def _classificar_fonte(tabelas: list[str]) -> str:
    tem_backend = any("backend_data" in t for t in tabelas)
    tem_superlogica = any("backend_data" not in t for t in tabelas)
    if tem_backend and tem_superlogica:
        return "ambos"
    return "backend" if tem_backend else "superlogica"


@dataclass
class CatalogEntry:
    id: str
    secao: str
    titulo: str
    tipo: str
    tabelas: list[str]
    grao: str
    parametros: dict
    saida: list[str]
    exemplos_pergunta: list[str]
    limitacoes: list[str]
    componentes: list[str]
    validado_bq: bool
    fonte: str
    sql_template: str | None
    serie_historica_id: str | None


@dataclass
class MatchResult:
    status: Literal["confiante", "ambiguo", "sem_match"]
    candidatos: list[tuple[CatalogEntry, float]]  # ordenados por score desc
    tokens_embedding: int


@st.cache_resource
def _openai_client() -> OpenAI:
    return OpenAI(api_key=st.secrets["openai"]["api_key"])


@st.cache_resource
def _bq_client() -> bigquery.Client:
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


@st.cache_data(ttl=3600)
def carregar_catalogo() -> tuple[list[CatalogEntry], np.ndarray]:
    """Carrega o catalogo materializado + matriz de embeddings (N, 1536)."""
    df = _bq_client().query(f"SELECT * FROM `{CATALOGO_TABLE}`").to_dataframe()
    entries = [
        CatalogEntry(
            id=row["id"],
            secao=row["secao"],
            titulo=row["titulo"],
            tipo=row["tipo"],
            tabelas=list(row["tabelas"]),
            grao=row["grao"],
            parametros=json.loads(row["parametros_json"]) if row["parametros_json"] else {},
            saida=list(row["saida"]),
            exemplos_pergunta=list(row["exemplos_pergunta"]),
            limitacoes=list(row["limitacoes"]),
            componentes=list(row["componentes"]) if row["componentes"] is not None else [],
            validado_bq=bool(row["validado_bq"]),
            fonte=row["fonte"],
            sql_template=row["sql_template"] if row["sql_template"] else None,
            serie_historica_id=row["serie_historica_id"] if row["serie_historica_id"] else None,
        )
        for _, row in df.iterrows()
    ]
    embeddings = np.array(df["embedding"].tolist())
    return entries, embeddings


def buscar_match(pergunta: str, top_k: int = 3) -> MatchResult:
    """
    Gera o embedding da pergunta e compara por cosseno contra o catalogo.
    NAO chama nenhum LLM de chat -- só o modelo de embedding (barato, ver
    tabela de precos no Runbook). A decisao de chamar o LLM de extracao de
    parametro fica pro chamador, baseada no `status` retornado aqui.
    """
    entries, catalog_embeddings = carregar_catalogo()

    resp = _openai_client().embeddings.create(model=EMBEDDING_MODEL, input=pergunta)
    q_emb = np.array(resp.data[0].embedding)

    norms = np.linalg.norm(catalog_embeddings, axis=1)
    sims = catalog_embeddings @ q_emb / (norms * np.linalg.norm(q_emb))

    top_idx = np.argsort(-sims)[:top_k]
    candidatos = [(entries[i], float(sims[i])) for i in top_idx]

    top_score = candidatos[0][1]
    if top_score >= LIMIAR_CONFIANTE:
        status = "confiante"
    elif top_score >= LIMIAR_AMBIGUO:
        status = "ambiguo"
    else:
        status = "sem_match"

    # ambiguidade de fonte (2026-08-19): mesmo "confiante", se existir entre os
    # candidatos um de fonte DIFERENTE do top-1 (Superlogica vs Backend) com
    # score proximo, a pergunta pode ter duas leituras validas (contratado x
    # realmente ativo) -- vira ambiguo pra sempre perguntar, nunca escolher
    # calado. Escaneia os candidatos em ordem ate achar o 1o de fonte
    # diferente (pode nao ser o 2o colocado -- ver caso real testado no doc).
    if status == "confiante" and len(candidatos) > 1:
        fonte_top1 = _classificar_fonte(candidatos[0][0].tabelas)
        if fonte_top1 != "ambos":
            for entry2, score2 in candidatos[1:]:
                fonte2 = _classificar_fonte(entry2.tabelas)
                if fonte2 == "ambos" or fonte2 == fonte_top1:
                    continue  # nao e "a outra leitura" -- pula, continua procurando
                if (top_score - score2) <= GAP_AMBIGUIDADE_FONTE and score2 >= LIMIAR_AMBIGUO:
                    status = "ambiguo"
                break  # achou o 1o candidato de fonte diferente -- decide com base nele e para

    return MatchResult(
        status=status,
        candidatos=candidatos,
        tokens_embedding=resp.usage.total_tokens,
    )
