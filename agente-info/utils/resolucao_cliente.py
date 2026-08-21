"""
utils/resolucao_cliente.py
Resolve um NOME de cliente/igreja (em vez de codigo) mencionado numa
pergunta -- usado quando uma entrada grao=cliente precisa de id_cliente/
codigo_igreja mas o usuario so deu o nome (ex: "Sara Nossa Terra", que bate
em varias igrejas filhas de uma denominacao). Pedido do usuario 2026-08-21.

Busca no Superlogica (mesma logica de LIKE da entrada 1.4 do catalogo, ver
[ALL] Queries_Gerais_BigQuery.md secao 1) -- e onde vive a informacao de
mensalidade/cadastro, e o cliente pagante tem nome mais reconhecivel que o
lado backend (igreja individual).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery

# Acima disso, rodar a query pra cada candidato fica caro/lento demais e a
# resposta vira ruido -- melhor pedir pro usuario refinar o nome.
MAX_RESULTADOS = 15

TABELA_CLIENTES = "business-intelligence-467516.superlogica_data.vw-splgc-clientes_unificada"


@dataclass
class ClienteEncontrado:
    id_sacado_sac: str
    codigo_igreja_local: str | None
    nome_igreja: str


@st.cache_resource
def _bq_client() -> bigquery.Client:
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


def buscar_por_nome(nome: str, apenas_ativos: bool = True) -> list[ClienteEncontrado]:
    """
    Busca clientes cujo nome bate (LIKE, case-insensitive) com `nome`.
    Limitado a MAX_RESULTADOS + 1 linhas -- o chamador decide o que fazer
    quando estoura o limite (pedir pra refinar em vez de rodar N queries).
    """
    filtro_ativo = "AND dt_desativacao_sac IS NULL" if apenas_ativos else ""
    sql = f"""
        SELECT
          id_sacado_sac,
          st_sincro_sac AS codigo_igreja_local,
          st_nome_sac   AS nome_igreja
        FROM `{TABELA_CLIENTES}`
        WHERE LOWER(st_nome_sac) LIKE CONCAT('%', LOWER(@nome), '%')
          {filtro_ativo}
        ORDER BY st_nome_sac
        LIMIT {MAX_RESULTADOS + 1}
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("nome", "STRING", nome)]
    )
    df = _bq_client().query(sql, job_config=job_config).to_dataframe()
    return [
        ClienteEncontrado(
            id_sacado_sac=row["id_sacado_sac"],
            codigo_igreja_local=row["codigo_igreja_local"] or None,
            nome_igreja=row["nome_igreja"],
        )
        for _, row in df.iterrows()
    ]
