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
@st.cache_data(ttl=3600)
def load_ids_com_problema() -> set[str]:
    """Returns set of tertiarygroup_ids (STRING) that have any validation issue."""
    query = f"""
    SELECT DISTINCT CAST(Tertiarygroup_id AS STRING) AS tid
    FROM `{_DATASET}.validacao_backend_fechamentos`
    WHERE LOWER(COALESCE(CAST(backend_str AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(Tertiarygroup_id AS STRING)
    FROM `{_DATASET}.splgc_validacao_setup`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(Tertiarygroup_id AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(tertiarygroup_id AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos2`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(tertiarygroup_id AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos3`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(tertiarygroup_id AS STRING)
    FROM `{_DATASET}.hubspot_validacao`
    WHERE LOWER(COALESCE(CAST(hubspot_status AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(Tertiarygroup_id AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(validacao_produto AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(Tertiarygroup_id AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_modulos`
    WHERE LOWER(COALESCE(CAST(validacao_modulo AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(Tertiarygroup_id AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_setup`
    WHERE LOWER(COALESCE(CAST(validacao_setup AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(tertiarygroup_id AS STRING)
    FROM `{_DATASET}.upsell_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(validacao_preco AS STRING), '')) != 'ok'
    UNION DISTINCT
    SELECT CAST(tertiarygroup_id AS STRING)
    FROM `{_DATASET}.upsell_validacao_modulos`
    WHERE LOWER(COALESCE(CAST(validacao_modulo AS STRING), '')) != 'ok'
    """
    df = _bq_query(query)
    if df.empty:
        return set()
    return set(df["tid"].dropna().astype(str).tolist())


@st.cache_data(ttl=3600)
def load_conferencias_detalhado() -> pd.DataFrame:
    """Returns all validation issues (tipo, tertiarygroup_id, detalhe)."""
    query = f"""
    SELECT CAST(Tertiarygroup_id AS STRING) AS tertiarygroup_id,
           'Backend Fechamento'             AS tipo,
           CAST(backend_str AS STRING)      AS detalhe
    FROM `{_DATASET}.validacao_backend_fechamentos`
    WHERE LOWER(COALESCE(CAST(backend_str AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(Tertiarygroup_id AS STRING), 'Setup Superlógica', CAST(ok AS STRING)
    FROM `{_DATASET}.splgc_validacao_setup`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(Tertiarygroup_id AS STRING), 'Produtos Superlógica', CAST(ok AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(tertiarygroup_id AS STRING), 'Produtos Superlógica 2', CAST(ok AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos2`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(tertiarygroup_id AS STRING), 'Produtos Superlógica 3', CAST(ok AS STRING)
    FROM `{_DATASET}.splgc_validacao_produtos3`
    WHERE LOWER(COALESCE(CAST(ok AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(tertiarygroup_id AS STRING), 'HubSpot', CAST(hubspot_status AS STRING)
    FROM `{_DATASET}.hubspot_validacao`
    WHERE LOWER(COALESCE(CAST(hubspot_status AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(Tertiarygroup_id AS STRING), 'Produto Fechamento', CAST(validacao_produto AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(validacao_produto AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(Tertiarygroup_id AS STRING), 'Módulo Fechamento', CAST(validacao_modulo AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_modulos`
    WHERE LOWER(COALESCE(CAST(validacao_modulo AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(Tertiarygroup_id AS STRING), 'Setup Fechamento', CAST(validacao_setup AS STRING)
    FROM `{_DATASET}.fechamentos_validacao_setup`
    WHERE LOWER(COALESCE(CAST(validacao_setup AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(tertiarygroup_id AS STRING), 'Preço Upsell', CAST(validacao_preco AS STRING)
    FROM `{_DATASET}.upsell_validacao_produtos`
    WHERE LOWER(COALESCE(CAST(validacao_preco AS STRING), '')) != 'ok'

    UNION ALL

    SELECT CAST(tertiarygroup_id AS STRING), 'Módulo Upsell', CAST(validacao_modulo AS STRING)
    FROM `{_DATASET}.upsell_validacao_modulos`
    WHERE LOWER(COALESCE(CAST(validacao_modulo AS STRING), '')) != 'ok'
    """
    return _bq_query(query)
