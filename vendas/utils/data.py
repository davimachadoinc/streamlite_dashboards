"""
utils/data.py
Helpers de dados para o dashboard de Fechamento de Vendas.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from google.oauth2 import service_account
from google.cloud import bigquery


PALETTE = [
    "#6eda2c",  # 0 — verde primário
    "#ffffff",  # 1 — branco
    "#57d124",  # 2 — verde secundário
    "#a0a0a0",  # 3 — cinza médio
    "#4c4c4c",  # 4 — cinza escuro
    "#292929",  # 5 — borda
    "#8ae650",  # 6 — verde claro
    "#3ba811",  # 7 — verde profundo
]
CHART_TEMPLATE = "plotly_dark"

_DATASET = "business-intelligence-467516.Fechamento_vendas"


# ─────────────────────────────────────────────
# CONEXÃO BIGQUERY
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    project = cfg["project"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=project, credentials=credentials)


@st.cache_resource
def _bq_client_bi() -> bigquery.Client:
    return _get_bq_client("bigquery_bi")


def _bq_query(query: str) -> pd.DataFrame:
    try:
        return _bq_client_bi().query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# HELPERS DE FORMATAÇÃO
# ─────────────────────────────────────────────
def fmt_brl(value, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ─────────────────────────────────────────────
# HELPERS DE GRÁFICOS
# ─────────────────────────────────────────────
def chart_layout(fig: go.Figure, height: int = 380, legend_bottom: bool = False) -> go.Figure:
    legend_cfg = dict(
        bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit", size=12, color="#a0a0a0"),
    )
    if legend_bottom:
        legend_cfg.update(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5)

    fig.update_layout(
        height=height,
        template=CHART_TEMPLATE,
        margin=dict(l=4, r=4, t=32, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        legend=legend_cfg,
        xaxis=dict(
            showgrid=True, gridcolor="#292929", gridwidth=1,
            zeroline=False, title="", type="category",
        ),
        yaxis=dict(
            showgrid=True, gridcolor="#292929", gridwidth=1,
            zeroline=False, title="",
        ),
        hoverlabel=dict(
            bgcolor="#141414", bordercolor="#292929",
            font_size=13, font_family="Outfit, sans-serif", font_color="#ffffff",
        ),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


def period_selector(default_idx: int = 2) -> int:
    n = st.selectbox(
        "Período",
        options=[3, 6, 12, 24, 0],
        index=default_idx,
        format_func=lambda x: "Todos" if x == 0 else f"Últimos {x} meses",
        key=f"period_{st.session_state.get('_page_key', 'default')}",
    )
    return n


def filter_months(df: pd.DataFrame, n_months: int, date_col: str = "mes") -> pd.DataFrame:
    if df.empty or n_months == 0:
        return df
    cutoff = pd.Timestamp.today() - pd.DateOffset(months=n_months)
    col = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(col):
        col = pd.to_datetime(col, errors="coerce")
    return df[col >= cutoff].copy()


# ─────────────────────────────────────────────
# QUERIES — FECHAMENTOS
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_fechamentos() -> pd.DataFrame:
    query = f"""
        SELECT
            first_payment,
            company_name,
            CAST(tertiarygroup_id AS STRING)  AS tertiarygroup_id,
            CAST(superlogica_id   AS STRING)  AS superlogica_id,
            sales_owner,
            sdr_owner,
            channel,
            plan,
            products,
            CAST(value  AS FLOAT64) AS value,
            CAST(setup  AS FLOAT64) AS setup,
            CAST(FYV    AS FLOAT64) AS FYV,
            CAST(hubspot_deal AS STRING)       AS hubspot_deal,
            upsell,
            new_deal,
            observacao,
            member_range,
            members
        FROM `{_DATASET}.Fechamentos_com_ajustes`
        ORDER BY first_payment DESC
    """
    df = _bq_query(query)
    if df.empty:
        return df
    df["first_payment"] = pd.to_datetime(df["first_payment"], errors="coerce")
    df["_mes_ord"] = df["first_payment"].dt.to_period("M")
    df["_mes_fmt"] = df["first_payment"].dt.strftime("%b/%y").str.capitalize()
    df["FYV"] = df["FYV"].where(
        df["FYV"].notna() & (df["FYV"] != 0),
        df["value"].fillna(0) * 12 + df["setup"].fillna(0),
    )
    return df


# ─────────────────────────────────────────────
# QUERIES — CONFERÊNCIAS
# ─────────────────────────────────────────────

# Cada entrada: (table, id_col, status_col, ok_value, label)
_VALIDATION_TABLES: list[tuple[str, str, str, str, str]] = [
    ("validacao_backend_fechamentos", "Tertiarygroup_id", "backend_str",      "ok", "Backend Fechamento"),
    ("splgc_validacao_setup",         "Tertiarygroup_id", "ok",               "ok", "Setup Superlógica"),
    ("splgc_validacao_produtos",      "Tertiarygroup_id", "ok",               "ok", "Produtos Superlógica"),
    ("hubspot_validacao",             "tertiarygroup_id", "hubspot_status",   "ok", "HubSpot"),
    ("fechamentos_validacao_produtos","Tertiarygroup_id", "validacao_produto","ok", "Produto Fechamento"),
    ("fechamentos_validacao_modulos", "Tertiarygroup_id", "validacao_modulo", "ok", "Módulo Fechamento"),
    ("fechamentos_validacao_setup",   "Tertiarygroup_id", "validacao_setup",  "ok", "Setup Fechamento"),
    ("upsell_validacao_produtos",     "tertiarygroup_id", "validacao_preco",  "ok", "Preço Upsell"),
    ("upsell_validacao_modulos",      "tertiarygroup_id", "validacao_modulo", "ok", "Módulo Upsell"),
    ("upsell_validacao_setup",        "Tertiarygroup_id", "validacao_setup",  "ok", "Setup Upsell"),
]


def _query_validation_table(table: str, id_col: str, status_col: str, label: str) -> pd.DataFrame:
    """Query a single validation table; returns empty DataFrame if table doesn't exist."""
    query = f"""
    SELECT
        CAST({id_col} AS STRING)      AS tertiarygroup_id,
        '{label}'                     AS tipo,
        CAST({status_col} AS STRING)  AS detalhe
    FROM `{_DATASET}.{table}`
    WHERE LOWER(COALESCE(CAST({status_col} AS STRING), '')) != 'ok'
    """
    try:
        return _bq_client_bi().query(query).to_dataframe()
    except Exception:
        return pd.DataFrame(columns=["tertiarygroup_id", "tipo", "detalhe"])


@st.cache_data(ttl=3600)
def load_ids_com_problema() -> set[str]:
    """Returns set of tertiarygroup_ids (STRING) that have any validation issue."""
    frames = [
        _query_validation_table(t, id_col, status_col, label)
        for t, id_col, status_col, _, label in _VALIDATION_TABLES
    ]
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame()
    if df.empty:
        return set()
    return set(df["tertiarygroup_id"].dropna().astype(str).tolist())


@st.cache_data(ttl=3600)
def load_conferencias_detalhado() -> pd.DataFrame:
    """Returns all validation issues (tipo, tertiarygroup_id, detalhe).
    Queries each table individually — missing tables are silently skipped."""
    frames = [
        _query_validation_table(t, id_col, status_col, label)
        for t, id_col, status_col, _, label in _VALIDATION_TABLES
    ]
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame(columns=["tertiarygroup_id", "tipo", "detalhe"])
    return pd.concat(non_empty, ignore_index=True)
