"""
utils/data.py
Execucao de SQL do catalogo (bi_data.catalogo_queries.sql_template) contra o
BigQuery. Modo catalogo NUNCA gera SQL novo (ADR-001) -- so roda o template
ja pre-aprovado, com valores de parametro substituidos via query parameters
nativos do BQ (@nome), nunca concatenacao de string.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery

from utils.matching import CatalogEntry


@dataclass
class ResultadoQuery:
    df: pd.DataFrame
    bytes_processed: int
    tempo_resposta_ms: int


@st.cache_resource
def _bq_client() -> bigquery.Client:
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


_BQ_TYPE_MAP = {
    "int": "INT64",
    "string": "STRING",
    "date": "DATE",
    "float": "FLOAT64",
    "bool": "BOOL",
}


def executar_query_catalogo(entry: CatalogEntry, parametros: dict) -> ResultadoQuery:
    """
    Roda entry.sql_template no BQ. `parametros` deve ter uma chave por
    parametro obrigatorio de entry.parametros (nomes e tipos batendo com o
    catalogo). Sem sql_template ainda cadastrado -> erro explicito, nunca
    tenta gerar SQL na hora (violaria ADR-001).
    """
    if not entry.sql_template:
        raise ValueError(
            f"Entrada '{entry.id}' ainda nao tem sql_template cadastrado em "
            f"bi_data.catalogo_queries. Ver fonte: {entry.fonte}"
        )

    query_params = []
    for nome, spec in entry.parametros.items():
        if nome not in parametros:
            if spec.get("obrigatorio", True):
                raise ValueError(f"Parametro obrigatorio ausente: {nome}")
            continue
        bq_type = _BQ_TYPE_MAP.get(str(spec.get("tipo", "string")).lower(), "STRING")
        query_params.append(bigquery.ScalarQueryParameter(nome, bq_type, parametros[nome]))

    job_config = bigquery.QueryJobConfig(query_parameters=query_params) if query_params else None

    inicio = time.monotonic()
    job = _bq_client().query(entry.sql_template, job_config=job_config)
    df = job.to_dataframe()
    tempo_ms = int((time.monotonic() - inicio) * 1000)

    return ResultadoQuery(
        df=df,
        bytes_processed=job.total_bytes_processed or 0,
        tempo_resposta_ms=tempo_ms,
    )
