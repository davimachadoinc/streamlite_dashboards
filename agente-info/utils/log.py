"""
utils/log.py
Grava cada pergunta na tabela de log de uso (Workflow 4).
dashboard_agente_info.log_uso -- so INSERT, nunca UPDATE/DELETE, entao
streaming insert (insert_rows_json) e seguro aqui (ver bigquery-conexoes.md
sobre a limitacao do streaming buffer pra UPDATE/DELETE).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery

from utils.workflow1 import RespostaWorkflow1
from utils.sql_livre import MODELO_SQL_LIVRE, ResultadoSQLLivre

TABLE_ID = "business-intelligence-467516.dashboard_agente_info.log_uso"


@st.cache_resource
def _bq_client() -> bigquery.Client:
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


def _inserir_linha(row: dict) -> None:
    """Best-effort: falha ao logar nunca deve quebrar a resposta pro usuario."""
    try:
        errors = _bq_client().insert_rows_json(TABLE_ID, [row])
        if errors:
            st.warning(f"Log de uso não gravado: {errors}")
    except Exception as e:
        st.warning(f"Log de uso não gravado: {e}")


_MODO_POR_STATUS = {
    "respondida": "catalogo",
    "sem_match": "sem_match",
    "ambiguo": "sem_match",
    "faltando_parametro": "catalogo",
    "cliente_nao_encontrado": "catalogo",
    "sem_sql_template": "sem_match",
    "erro": "catalogo",
}


def registrar_uso(
    pergunta_raw: str, colaborador: str, r: RespostaWorkflow1,
    qtd_perguntas_esclarecimento: int = 0,
) -> None:
    """
    Workflow 1 (modo catalogo). qtd_perguntas_esclarecimento: quantas
    perguntas o mecanismo de esclarecimento (ADR-015) fez antes de chegar
    nesse resultado -- 0 quando nem entrou nesse fluxo. O custo dessas
    perguntas ja deve estar somado em r.custo_embedding_usd/custo_llm_usd
    pelo chamador antes de logar (nao rateado, atribuido todo a pergunta
    inicial, pedido explicito do usuario).
    """
    _inserir_linha({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "colaborador": colaborador,
        "modo": _MODO_POR_STATUS.get(r.status, r.status),
        "query_id": r.entry.id if r.entry else None,
        "pergunta_raw": pergunta_raw,
        "parametros_usados": None,
        "teve_match": r.status not in ("sem_match",),
        "solicitou_bi": False,
        "tentou_busca_livre": False,
        "sql_gerado": None,
        "bytes_processed": r.bytes_processed,
        "linhas_retornadas": len(r.df) if r.df is not None else None,
        "tempo_resposta_ms": r.tempo_resposta_ms,
        "tokens_embedding": r.tokens_embedding,
        "custo_embedding_usd": r.custo_embedding_usd,
        "modelo_llm": "gpt-5.6-luna" if (r.tokens_llm_input or r.tokens_llm_output) else None,
        "tokens_llm_input": r.tokens_llm_input,
        "tokens_llm_output": r.tokens_llm_output,
        "custo_llm_usd": r.custo_llm_usd,
        "custo_bq_usd": r.custo_bq_usd,
        "custo_total_estimado_usd": r.custo_total_usd,
        "qtd_perguntas_esclarecimento": qtd_perguntas_esclarecimento,
    })


def registrar_solicitacao_bi(pergunta_raw: str, colaborador: str) -> None:
    """Workflow 2 -- clique isolado em "Solicitar ao BI", sem tentar busca livre."""
    _inserir_linha({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "colaborador": colaborador,
        "modo": "sem_match",
        "query_id": None,
        "pergunta_raw": pergunta_raw,
        "parametros_usados": None,
        "teve_match": False,
        "solicitou_bi": True,
        "tentou_busca_livre": False,
        "sql_gerado": None,
        "bytes_processed": None,
        "linhas_retornadas": None,
        "tempo_resposta_ms": None,
        "tokens_embedding": 0,
        "custo_embedding_usd": 0.0,
        "modelo_llm": None,
        "tokens_llm_input": 0,
        "tokens_llm_output": 0,
        "custo_llm_usd": 0.0,
        "custo_bq_usd": 0.0,
        "custo_total_estimado_usd": 0.0,
    })


def registrar_sql_livre(
    pergunta_raw: str, colaborador: str, resultado: ResultadoSQLLivre,
    tokens_geracao_input: int, tokens_geracao_output: int, custo_geracao_usd: float,
) -> None:
    """
    Workflow 2 -- Modo SQL Livre executado (ADR-006: notificacao ao BI ja
    disparada automaticamente pelo chamador antes desta funcao, entao
    solicitou_bi=True sempre aqui, forcado, nao opcional).
    """
    custo_bq = resultado.bytes_processed / (2**40) * 6.25 if resultado.bytes_processed else 0.0
    _inserir_linha({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "colaborador": colaborador,
        "modo": "livre",
        "query_id": None,
        "pergunta_raw": pergunta_raw,
        "parametros_usados": None,
        "teve_match": False,
        "solicitou_bi": True,
        "tentou_busca_livre": True,
        "sql_gerado": resultado.sql,
        "bytes_processed": resultado.bytes_processed,
        "linhas_retornadas": len(resultado.df) if resultado.df is not None else None,
        "tempo_resposta_ms": resultado.tempo_resposta_ms,
        "tokens_embedding": 0,
        "custo_embedding_usd": 0.0,
        "modelo_llm": MODELO_SQL_LIVRE,
        "tokens_llm_input": tokens_geracao_input,
        "tokens_llm_output": tokens_geracao_output,
        "custo_llm_usd": custo_geracao_usd,
        "custo_bq_usd": custo_bq,
        "custo_total_estimado_usd": custo_geracao_usd + custo_bq,
    })
