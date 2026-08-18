"""
utils/sql_livre.py
Modo SQL Livre (Workflow 2, fallback do fluxo sem-match) -- ADR-004/006 em
[BI] Dashboard_Agente_Informacao.md. Só roda depois de confirmacao explicita
do colaborador sobre o risco de dado nao validado (nunca automatico).

6 guardrails obrigatorios (fonte: [ALL] Queries_Gerais_BigQuery.md, secao 8):
  1. Somente leitura (SELECT/WITH)
  2. Uma tabela/projeto por vez (sem join cross-project)
  3. LIMIT obrigatorio na pre-visualizacao
  4. Dry-run de custo antes de rodar (teto de bytes)
  5. SQL gerado sempre visivel
  6. Documento fonte inteiro como grounding obrigatorio
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery
from openai import OpenAI

from utils.llm import custo_usd

MODELO_SQL_LIVRE = "gpt-5.6-terra"
TETO_BYTES_PADRAO = 2**30  # 1 GiB -- guardrail 4
LIMIT_PREVIA = 100  # guardrail 3

GROUNDING_TABLE = "business-intelligence-467516.dashboard_agente_info.grounding_docs"

_PALAVRAS_PROIBIDAS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|MERGE|TRUNCATE|GRANT|REVOKE|CALL|EXPORT|LOAD)\b",
    re.IGNORECASE,
)
_TABELA_QUALIFICADA = re.compile(r"`([a-zA-Z0-9_-]+)\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_`.-]+`")


@st.cache_resource
def _openai_client() -> OpenAI:
    return OpenAI(api_key=st.secrets["openai"]["api_key"])


@st.cache_resource
def _bq_client() -> bigquery.Client:
    import json
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


@st.cache_data(ttl=3600)
def _carregar_grounding() -> str:
    """
    Guardrail 6 -- os documentos fonte inteiros, nao so o schema cru.
    Le de `dashboard_agente_info.grounding_docs` (nao do disco local) para
    funcionar tanto localmente quanto no Streamlit Cloud -- ver ADR-014.
    Recarregar essa tabela sempre que os .md fonte no Obsidian mudarem
    (script: scratchpad/load_grounding_docs.py no Runbook).
    """
    df = _bq_client().query(
        f"SELECT nome_arquivo, conteudo FROM `{GROUNDING_TABLE}` ORDER BY nome_arquivo"
    ).to_dataframe()
    partes = [f"=== {row['nome_arquivo']} ===\n{row['conteudo']}" for _, row in df.iterrows()]
    return "\n\n".join(partes)


@dataclass
class ValidacaoGuardrails:
    ok: bool
    motivo: str | None = None


def validar_guardrails(sql: str) -> ValidacaoGuardrails:
    """Guardrails 1 e 2 -- checados antes de qualquer dry-run ou execucao."""
    sql_upper = sql.upper().strip()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        return ValidacaoGuardrails(False, "SQL gerado não começa com SELECT/WITH — bloqueado (somente leitura).")
    if _PALAVRAS_PROIBIDAS.search(sql):
        achou = _PALAVRAS_PROIBIDAS.search(sql).group(0)
        return ValidacaoGuardrails(False, f"SQL contém comando não permitido ({achou}) — bloqueado (somente leitura).")

    projetos = set(_TABELA_QUALIFICADA.findall(sql))
    if len(projetos) > 1:
        return ValidacaoGuardrails(
            False,
            f"Query tenta juntar mais de um projeto GCP numa query só ({', '.join(projetos)}) — "
            "não funciona no BigQuery. Tente perguntar em duas partes separadas.",
        )
    return ValidacaoGuardrails(True)


@dataclass
class SQLLivreGerado:
    sql: str
    tokens_input: int
    tokens_output: int
    custo_usd: float


def gerar_sql(pergunta: str) -> SQLLivreGerado:
    """Guardrail 6: documento fonte inteiro como grounding obrigatorio."""
    grounding = _carregar_grounding()
    resp = _openai_client().chat.completions.create(
        model=MODELO_SQL_LIVRE,
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce gera SQL para o BigQuery com base EXCLUSIVAMENTE na documentacao fornecida "
                    "abaixo -- essa documentacao contem armadilhas reais ja corrigidas (deduplicacao "
                    "de boletos, chave de join correta, filtros obrigatorios) que voce DEVE respeitar. "
                    "Nunca junte tabelas de projetos GCP diferentes (inchurch-gcp vs "
                    "business-intelligence-467516) numa unica query -- nao funciona no BigQuery. "
                    "Gere APENAS a query SQL final, sem explicacao, sem markdown, sem ```sql. "
                    "Somente SELECT/WITH -- nunca INSERT/UPDATE/DELETE/DDL.\n\n"
                    f"DOCUMENTACAO FONTE (grounding obrigatorio):\n{grounding}"
                ),
            },
            {"role": "user", "content": pergunta},
        ],
    )
    sql = resp.choices[0].message.content.strip()
    sql = re.sub(r"^```sql\n?|```$", "", sql, flags=re.MULTILINE).strip()
    tin, tout = resp.usage.prompt_tokens, resp.usage.completion_tokens
    # cache de prompt automatico da OpenAI (grounding e sempre o mesmo texto,
    # confirmado 2026-08-18: 2a chamada em diante reaproveita ~99% do prompt)
    tcached = getattr(resp.usage.prompt_tokens_details, "cached_tokens", 0) or 0
    return SQLLivreGerado(
        sql=sql, tokens_input=tin, tokens_output=tout,
        custo_usd=custo_usd(MODELO_SQL_LIVRE, tin, tout, tokens_cached=tcached),
    )


@dataclass
class ResultadoSQLLivre:
    status: str  # "ok" | "bloqueado_guardrail" | "custo_excedido" | "erro"
    sql: str = ""
    motivo: str | None = None
    df: pd.DataFrame | None = None
    bytes_estimados: int = 0
    bytes_processed: int = 0
    tempo_resposta_ms: int = 0


def executar_sql_livre(sql: str, teto_bytes: int = TETO_BYTES_PADRAO) -> ResultadoSQLLivre:
    """Guardrails 1-4, nessa ordem: valida -> dry-run -> checa teto -> executa com LIMIT."""
    validacao = validar_guardrails(sql)
    if not validacao.ok:
        return ResultadoSQLLivre(status="bloqueado_guardrail", sql=sql, motivo=validacao.motivo)

    client = _bq_client()

    try:
        dry_run_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        dry_job = client.query(sql, job_config=dry_run_config)
        bytes_estimados = dry_job.total_bytes_processed
    except Exception as e:
        return ResultadoSQLLivre(status="erro", sql=sql, motivo=f"Erro no dry-run: {e}")

    if bytes_estimados > teto_bytes:
        return ResultadoSQLLivre(
            status="custo_excedido", sql=sql, bytes_estimados=bytes_estimados,
            motivo=(
                f"Essa query escanearia ~{bytes_estimados / 2**30:.2f} GiB — acima do teto de "
                f"{teto_bytes / 2**30:.0f} GiB. Tente adicionar um filtro de período pra reduzir o volume."
            ),
        )

    sql_com_limit = sql if re.search(r"\bLIMIT\s+\d+", sql, re.IGNORECASE) else f"{sql.rstrip(';')}\nLIMIT {LIMIT_PREVIA}"

    try:
        inicio = time.monotonic()
        job = client.query(sql_com_limit)
        df = job.to_dataframe()
        tempo_ms = int((time.monotonic() - inicio) * 1000)
    except Exception as e:
        return ResultadoSQLLivre(status="erro", sql=sql, bytes_estimados=bytes_estimados, motivo=str(e))

    return ResultadoSQLLivre(
        status="ok", sql=sql, df=df, bytes_estimados=bytes_estimados,
        bytes_processed=job.total_bytes_processed or 0, tempo_resposta_ms=tempo_ms,
    )
