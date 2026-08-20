"""
utils/matching.py
Motor de matching pergunta -> entrada do catalogo (bi_data.catalogo_queries).

Embeddings via OpenAI (text-embedding-3-small), busca por similaridade de
cosseno em numpy (catalogo pequeno, sem VECTOR_SEARCH/indice vetorial -- ver
ADR-011 em [BI] Dashboard_Agente_Informacao.md).

Representacao "max over examples" (ver grilling 2026-08-20, Dashboard_Agente_
Informacao.md): cada entrada do catalogo tem 1 embedding POR FRASE (titulo +
cada exemplo_pergunta, separados) em vez de 1 embedding borrado da
concatenacao de tudo. O score de uma entrada = a MAIOR similaridade entre a
pergunta e qualquer uma das suas frases. Substituiu a representacao anterior
(1 vetor medio por entrada) porque ela nunca chegava perto de scores altos
mesmo em match perfeito -- confirmado empiricamente antes da migracao.

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
EMBEDDINGS_TABLE = "business-intelligence-467516.bi_data.catalogo_queries_embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"

# Recalibrados em 2026-08-20 apos a migracao pra "max over examples" (scores
# subiram muito -- matches genuinos agora ficam 0.83-1.0, fora de escopo
# continua abaixo de 0.47). Ajustar conforme o log de uso real acumular volume.
LIMIAR_CONFIANTE = 0.80
LIMIAR_AMBIGUO = 0.55

# Piso dedicado pro candidato de fonte DIFERENTE contar como "leitura
# alternativa valida" (ver checagem de ambiguidade de fonte abaixo). Maior
# que LIMIAR_AMBIGUO de proposito: 0.55 so separa "sem relacao" de "vale
# considerar" -- e baixo demais pra decidir se uma alternativa de outra fonte
# e forte o bastante pra merecer confirmacao (testado 2026-08-20: com 0.55,
# "percentual por metodo de pagamento" disparava falso positivo contra "%
# pago por mes", que so compartilha vocabulario, nao e leitura alternativa
# real -- 0.60 separa esse caso do caso real de "igrejas com app ativo").
LIMIAR_AMBIGUIDADE_FONTE = 0.60


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
def carregar_catalogo() -> list[CatalogEntry]:
    """Carrega os metadados do catalogo materializado (sem embeddings)."""
    df = _bq_client().query(f"SELECT * FROM `{CATALOGO_TABLE}`").to_dataframe()
    return [
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


@st.cache_data(ttl=3600)
def carregar_embeddings_exemplos() -> tuple[list[str], np.ndarray]:
    """
    Carrega 1 embedding por frase (titulo + cada exemplo_pergunta) de cada
    entrada -- varias linhas por id. Retorna os ids paralelos a matriz (M,
    1536) pra reducao por maximo em buscar_match().
    """
    df = _bq_client().query(f"SELECT id, embedding FROM `{EMBEDDINGS_TABLE}`").to_dataframe()
    return df["id"].tolist(), np.array(df["embedding"].tolist())


def buscar_match(pergunta: str, top_k: int = 10) -> MatchResult:
    """
    Gera o embedding da pergunta e compara por cosseno contra cada frase
    (titulo/exemplo) do catalogo; o score de cada entrada e o MAXIMO entre
    suas frases ("max over examples", ver docstring do modulo). NAO chama
    nenhum LLM de chat -- só o modelo de embedding (barato, ver tabela de
    precos no Runbook). A decisao de chamar o LLM de extracao de parametro
    fica pro chamador, baseada no `status` retornado aqui.
    """
    entries = carregar_catalogo()
    ids_linhas, matriz = carregar_embeddings_exemplos()
    id_to_entry = {e.id: e for e in entries}

    resp = _openai_client().embeddings.create(model=EMBEDDING_MODEL, input=pergunta)
    q_emb = np.array(resp.data[0].embedding)

    norms = np.linalg.norm(matriz, axis=1)
    sims = matriz @ q_emb / (norms * np.linalg.norm(q_emb))

    melhor_por_entry: dict[str, float] = {}
    for eid, score in zip(ids_linhas, sims):
        if eid not in melhor_por_entry or score > melhor_por_entry[eid]:
            melhor_por_entry[eid] = float(score)

    ranked = sorted(melhor_por_entry.items(), key=lambda x: -x[1])[:top_k]
    candidatos = [(id_to_entry[eid], score) for eid, score in ranked if eid in id_to_entry]

    top_score = candidatos[0][1]
    if top_score >= LIMIAR_CONFIANTE:
        status = "confiante"
    elif top_score >= LIMIAR_AMBIGUO:
        status = "ambiguo"
    else:
        status = "sem_match"

    # ambiguidade de fonte (2026-08-19, recalibrado 2026-08-20): mesmo
    # "confiante", se existir ENTRE OS CANDIDATOS QUALQUER um de fonte
    # DIFERENTE do top-1 (Superlogica vs Backend) que ainda passe do limiar de
    # ambiguidade, a pergunta pode ter duas leituras validas (contratado x
    # realmente ativo) -- vira ambiguo pra sempre perguntar, nunca escolher
    # calado. Ate 2026-08-19 isso era um gap de score entre top-1 e o 1o
    # candidato de fonte diferente; depois da migracao pra "max over
    # examples" um match exato (ex: pergunta identica a um exemplo_pergunta)
    # pode bater ~1.0 e empurrar a alternativa de outra fonte pra bem longe
    # em distancia absoluta mesmo sendo a mesma ambiguidade de sempre -- por
    # isso virou presenca (existe candidato valido de outra fonte?), nao gap.
    if status == "confiante" and len(candidatos) > 1:
        fonte_top1 = _classificar_fonte(candidatos[0][0].tabelas)
        if fonte_top1 != "ambos":
            for entry2, score2 in candidatos[1:]:
                fonte2 = _classificar_fonte(entry2.tabelas)
                if fonte2 == "ambos" or fonte2 == fonte_top1:
                    continue  # nao e "a outra leitura" -- pula, continua procurando
                if score2 >= LIMIAR_AMBIGUIDADE_FONTE:
                    status = "ambiguo"
                break  # achou o 1o candidato de fonte diferente -- decide com base nele e para

    return MatchResult(
        status=status,
        candidatos=candidatos,
        tokens_embedding=resp.usage.total_tokens,
    )
