"""
utils/data.py
Helpers de dados e query BigQuery para o dashboard Visão de Clientes.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
from google.oauth2 import service_account
from google.cloud import bigquery

PLAN_LABELS = {
    "pro":     "PRO",
    "lite":    "LITE",
    "starter": "STARTER",
    "basic":   "BASIC",
    "filha":   "FILHA",
    "squad":   "Squad as a Service",
    "outros":  "Outros",
}

# Planos exibidos por padrão no filtro (conforme solicitado)
DEFAULT_PLAN_FILTER = ["lite", "pro", "basic", "starter"]

# Exclusão de linhas de módulo — usado para isolar a mensalidade base ao classificar o plano
_EXCL_MODULOS = """
    st_descricao_prd NOT LIKE '%[KIDS]%'
    AND st_descricao_prd NOT LIKE '%[JORNADA]%'
    AND st_descricao_prd NOT LIKE '%[LOJAINTELIGENTE]%'
    AND st_descricao_prd NOT LIKE '%[LOJAINTELIGENTE_INC]%'
    AND st_descricao_prd NOT LIKE '%[TOTEM]%'
    AND st_descricao_prd NOT LIKE '%[V_DEOS]%'
    AND NOT (st_descricao_prd LIKE '%[STARTER]%' AND st_descricao_prd LIKE '%Módulo%')
"""

_PLAN_CASE = """
    CASE
      WHEN st_descricao_prd LIKE '%[PRO]%'              THEN 'pro'
      WHEN st_descricao_prd LIKE '%[LITE]%'             THEN 'lite'
      WHEN st_descricao_prd LIKE '%[STARTER]%'          THEN 'starter'
      WHEN st_descricao_prd LIKE '%[FILHA]%'            THEN 'filha'
      WHEN st_descricao_prd LIKE '%[BASIC]%'            THEN 'basic'
      WHEN st_descricao_prd LIKE '%0 - 9 Igrejas%'      THEN 'pro'
      WHEN st_descricao_prd LIKE '%10+ Igrejas%'        THEN 'pro'
      WHEN st_descricao_prd LIKE '%App Lite%'           THEN 'lite'
      WHEN st_descricao_prd LIKE '%App da Igreja%'      THEN 'starter'
      WHEN st_descricao_prd LIKE '%Squad as a Service%' THEN 'squad'
      ELSE 'outros'
    END
"""


def fmt_brl(value, decimals: int = 2) -> str:
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CONEXÕES BIGQUERY
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=cfg["project"], credentials=credentials)


@st.cache_resource
def _bq_client_tech() -> bigquery.Client:
    return _get_bq_client("bigquery_tech")


@st.cache_resource
def _bq_client_bi() -> bigquery.Client:
    return _get_bq_client("bigquery_bi")


def _bq_query(query: str, project_key: str = "bigquery_tech") -> pd.DataFrame:
    try:
        client = _bq_client_tech() if project_key == "bigquery_tech" else _bq_client_bi()
        return client.query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery ({project_key}): {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# QUERIES
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_mrr_ativo_por_igreja() -> pd.DataFrame:
    """
    MRR ativo atual por igreja (todas as linhas de mensalidade vigentes, exceto
    Setup e PRO-RATA — mesmo padrão de load_fechamentos_vs_mrr_atual do Unit Economics).
    Plano é classificado a partir da linha de mensalidade base (módulos excluídos);
    se houver mais de uma linha base num mesmo cliente, prevalece a de maior valor.
    Retorna: st_sincro_sac, nome_splgc, mrr_ativo, plano.
    """
    query = f"""
    WITH mrr_lines AS (
      SELECT st_sincro_sac, st_nome_sac, valor_total, st_descricao_prd
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NULL
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    mrr_total AS (
      SELECT
        st_sincro_sac,
        ANY_VALUE(st_nome_sac) AS nome_splgc,
        SUM(valor_total)       AS mrr_ativo
      FROM mrr_lines
      GROUP BY 1
    ),
    plano_base AS (
      SELECT
        st_sincro_sac,
        {_PLAN_CASE} AS plano,
        valor_total
      FROM mrr_lines
      WHERE {_EXCL_MODULOS}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY st_sincro_sac ORDER BY valor_total DESC) = 1
    )
    SELECT
      t.st_sincro_sac,
      t.nome_splgc,
      t.mrr_ativo,
      COALESCE(p.plano, 'outros') AS plano
    FROM mrr_total t
    LEFT JOIN plano_base p ON t.st_sincro_sac = p.st_sincro_sac
    """
    return _bq_query(query, "bigquery_bi")


@st.cache_data(ttl=3600)
def load_transacionado_e_empresas() -> pd.DataFrame:
    """
    TPV transacionado nos últimos 6 meses (view_transaction) por igreja, com
    nome vigente da igreja (view_company_list). status active/payed, excluindo
    métodos free/external/debit (ver bigquery-regras.md).
    Retorna: tertiarygroup_id, tertiarygroup_name, transacionado_6m.
    """
    query = """
    WITH tpv AS (
      SELECT
        tertiarygroup_id,
        SUM(value) AS transacionado_6m
      FROM `inchurch-gcp.backend_bi.view_transaction`
      WHERE status IN ('active', 'payed')
        AND method NOT IN ('free', 'external', 'debit')
        AND DATE(datetime) >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
      GROUP BY 1
    )
    SELECT
      c.tertiarygroup_id,
      c.tertiarygroup_name,
      COALESCE(t.transacionado_6m, 0) AS transacionado_6m
    FROM `inchurch-gcp.backend_bi.view_company_list` c
    LEFT JOIN tpv t ON c.tertiarygroup_id = t.tertiarygroup_id
    """
    return _bq_query(query, "bigquery_tech")


@st.cache_data(ttl=3600)
def load_visao_clientes() -> pd.DataFrame:
    """
    Junta MRR ativo (BQ_BI) com transacionado 6m e nome oficial da igreja (BQ_TECH).
    Escopo: apenas igrejas com MRR ativo hoje (join cross-project feito em pandas,
    convertendo tertiarygroup_id para string — ver bigquery-conexoes.md).
    Retorna: tertiarygroup_id, tertiarygroup_name, plano, mrr_ativo, transacionado_6m.
    """
    df_mrr = load_mrr_ativo_por_igreja()
    if df_mrr.empty:
        return pd.DataFrame()

    df_emp = load_transacionado_e_empresas()

    df_mrr = df_mrr.copy()
    df_mrr["st_sincro_sac"] = df_mrr["st_sincro_sac"].astype(str)

    if not df_emp.empty:
        df_emp = df_emp.copy()
        df_emp["tertiarygroup_id"] = df_emp["tertiarygroup_id"].astype("Int64")
        df_emp["_id_str"] = df_emp["tertiarygroup_id"].astype(str)
    else:
        df_emp = pd.DataFrame(columns=["tertiarygroup_id", "tertiarygroup_name", "transacionado_6m", "_id_str"])

    df = df_mrr.merge(
        df_emp, left_on="st_sincro_sac", right_on="_id_str", how="left"
    )

    # tertiarygroup_id: usa o do BQ_TECH quando existe; senão, deriva do próprio st_sincro_sac
    id_from_bi = pd.to_numeric(df["st_sincro_sac"], errors="coerce")
    df["tertiarygroup_id"] = df["tertiarygroup_id"].fillna(id_from_bi).astype("Int64")

    # nome: prioriza o nome oficial (view_company_list); cai para o nome do Superlógica
    df["tertiarygroup_name"] = df["tertiarygroup_name"].fillna("").replace("", None)
    df["tertiarygroup_name"] = df["tertiarygroup_name"].fillna(df["nome_splgc"])
    df["tertiarygroup_name"] = df["tertiarygroup_name"].fillna(df["st_sincro_sac"])

    df["transacionado_6m"] = df["transacionado_6m"].fillna(0.0)

    return (
        df[["tertiarygroup_id", "tertiarygroup_name", "plano", "mrr_ativo", "transacionado_6m"]]
        .sort_values("mrr_ativo", ascending=False)
        .reset_index(drop=True)
    )
