"""
utils/data.py
Helpers de dados, cache, paleta de cores e layout de gráficos.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import date
from dateutil.relativedelta import relativedelta
from google.oauth2 import service_account
from google.cloud import bigquery

# ─────────────────────────────────────────────
# PALETA & TEMPLATE
# ─────────────────────────────────────────────
PALETTE = [
    "#6eda2c",  # 0 — verde primário
    "#ffffff",  # 1 — branco
    "#57d124",  # 2 — verde secundário
    "#a0a0a0",  # 3 — cinza médio
    "#4c4c4c",  # 4 — cinza escuro
    "#292929",  # 5 — borda
    "#8ae650",  # 6 — verde claro
    "#3ba811",  # 7 — verde profundo
    "#cccccc",  # 8 — cinza claro
    "#111111",  # 9 — quase preto
]
CHART_TEMPLATE = "plotly_dark"

MODULE_LABELS = {
    "kids":             "Kids",
    "jornada":          "Jornada",
    "loja_inteligente": "Loja Inteligente",
}

MODULE_COLORS = {
    "kids":             "#6eda2c",
    "jornada":          "#ffffff",
    "loja_inteligente": "#a0a0a0",
    "base":             "#4c4c4c",
}

# Métodos de pagamento excluídos dos gráficos de transação
METHODS_EXCLUDED = ('free', 'external', 'debit')


# ─────────────────────────────────────────────
# LAYOUT PADRÃO DE GRÁFICOS
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
        xaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title="", type="category"),
        yaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title=""),
        hoverlabel=dict(
            bgcolor="#141414", bordercolor="#292929",
            font_size=13, font_family="Outfit, sans-serif", font_color="#ffffff",
        ),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    """
    Adiciona coluna mes_fmt (MMM/YY) e retorna o df + lista ordenada cronologicamente.
    Usar como categoryorder no eixo X para garantir ordem correta.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.lower().str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


# ─────────────────────────────────────────────
# SELETORES DE PERÍODO
# ─────────────────────────────────────────────
def period_selector() -> int:
    with st.sidebar:
        st.markdown("### 🗓️ Período")
        n = st.selectbox(
            "Últimos N meses",
            options=[3, 6, 12, 15, 0],
            index=3,
            format_func=lambda x: "Todos" if x == 0 else f"Últimos {x} meses",
            key=f"period_{st.session_state.get('_page_key', 'default')}",
        )
    return n


def filter_months(df: pd.DataFrame, n_months: int, date_col: str = "mes") -> pd.DataFrame:
    if df.empty or n_months == 0:
        return df
    cutoff = date.today() - relativedelta(months=n_months)
    cutoff_ts = pd.Timestamp(cutoff)
    col = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(col):
        col = pd.to_datetime(col, errors="coerce")
    return df[col >= cutoff_ts].copy()


# ─────────────────────────────────────────────
# HELPERS DE KPI
# ─────────────────────────────────────────────
def last_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-1] if len(ordered) >= 1 else None


def prev_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-2] if len(ordered) >= 2 else None


def delta_str(curr, prev, fmt: str = "+,.0f", suffix: str = "") -> str | None:
    if curr is None or prev is None:
        return None
    diff = curr - prev
    try:
        return f"{diff:{fmt}}{suffix}"
    except Exception:
        return f"{diff:+.2f}{suffix}"


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CONEXÃO BIGQUERY — cliente nativo
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    project = cfg["project"]
    creds_raw = cfg["credentials"]
    if isinstance(creds_raw, str):
        creds_dict = json.loads(creds_raw)
    else:
        creds_dict = dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return bigquery.Client(project=project, credentials=credentials)


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
# ── PÁGINA 1: COBRANÇA / MÓDULOS ─────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_contratos_mensais() -> pd.DataFrame:
    """Clientes únicos com boleto emitido por mês + receita total."""
    query = """
    WITH dedup AS (
      SELECT
        st_sincro_sac,
        DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
        id_recebimento_recb,
        vl_total_recb,
        fl_status_recb,
        ROW_NUMBER() OVER (
          PARTITION BY id_recebimento_recb
          ORDER BY dt_vencimento_recb
        ) AS rn
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
    )
    SELECT
      mes,
      COUNT(DISTINCT st_sincro_sac)  AS clientes_com_boleto,
      COUNT(id_recebimento_recb)     AS total_boletos,
      SUM(vl_total_recb)             AS receita_total,
      SUM(CASE WHEN fl_status_recb = '1' THEN vl_total_recb ELSE 0 END) AS receita_liquidada
    FROM dedup
    WHERE rn = 1
    GROUP BY mes
    ORDER BY mes
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
    return df


@st.cache_data(ttl=3600)
def load_modulos_mensais() -> pd.DataFrame:
    """
    Clientes com módulo ativo (identificado via st_descricao_prd no MRR)
    que tiveram boleto emitido no mês.
    Módulos: [KIDS], [JORNADA], [LOJAINTELIGENTE] ou [LOJAINTELIGENTE_INC].
    """
    # Boletos por cliente/mês — bigquery_bi
    query_boletos = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      st_sincro_sac
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
    GROUP BY 1, 2
    """

    # Módulo ativo por cliente via MRR — bigquery_bi
    query_mrr = """
    SELECT DISTINCT
      st_sincro_sac,
      CASE
        WHEN st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo
    FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
    WHERE
      CAST(dt_inicio_mens AS DATE) <= CURRENT_DATE()
      AND (dt_fim_mens IS NULL OR CAST(dt_fim_mens AS DATE) > CURRENT_DATE())
      AND (
        st_descricao_prd LIKE '%[KIDS]%'
        OR st_descricao_prd LIKE '%[JORNADA]%'
        OR st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
    """

    df_boletos = _bq_query(query_boletos, "bigquery_bi")
    df_mrr     = _bq_query(query_mrr,     "bigquery_bi")

    if df_boletos.empty or df_mrr.empty:
        return pd.DataFrame(columns=["mes", "modulo", "clientes"])

    df_boletos["mes"]          = pd.to_datetime(df_boletos["mes"])
    df_boletos["st_sincro_sac"] = df_boletos["st_sincro_sac"].astype(str)
    df_mrr["st_sincro_sac"]    = df_mrr["st_sincro_sac"].astype(str)
    df_mrr = df_mrr[df_mrr["modulo"].notna()]

    merged = df_boletos.merge(df_mrr, on="st_sincro_sac", how="inner")
    result = (
        merged.groupby(["mes", "modulo"], as_index=False)
        ["st_sincro_sac"].nunique()
        .rename(columns={"st_sincro_sac": "clientes"})
    )
    return result


@st.cache_data(ttl=3600)
def load_receita_modulos_mensais() -> pd.DataFrame:
    """
    Receita por módulo por mês usando comp_valor (não vl_total_recb).
    Filtra comp_st_conta_cont = '1.2.2' (Mensalidade) para isolar receita de módulo.
    Identifica módulo via MRR (st_descricao_prd).
    """
    # comp_valor de mensalidade por cliente/mês
    query_receita = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      st_sincro_sac,
      SUM(comp_valor)                                      AS receita_emitida,
      SUM(CASE WHEN fl_status_recb = '1' THEN comp_valor ELSE 0 END) AS receita_liquidada
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
      AND comp_st_conta_cont = '1.2.2'
    GROUP BY 1, 2
    """

    # Módulo ativo por cliente via MRR
    query_mrr = """
    SELECT DISTINCT
      st_sincro_sac,
      CASE
        WHEN st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo
    FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
    WHERE
      CAST(dt_inicio_mens AS DATE) <= CURRENT_DATE()
      AND (dt_fim_mens IS NULL OR CAST(dt_fim_mens AS DATE) > CURRENT_DATE())
      AND (
        st_descricao_prd LIKE '%[KIDS]%'
        OR st_descricao_prd LIKE '%[JORNADA]%'
        OR st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
    """

    df_receita = _bq_query(query_receita, "bigquery_bi")
    df_mrr     = _bq_query(query_mrr,     "bigquery_bi")

    if df_receita.empty or df_mrr.empty:
        return pd.DataFrame(columns=["mes", "modulo", "receita_emitida", "receita_liquidada"])

    df_receita["mes"]          = pd.to_datetime(df_receita["mes"])
    df_receita["st_sincro_sac"] = df_receita["st_sincro_sac"].astype(str)
    df_mrr["st_sincro_sac"]    = df_mrr["st_sincro_sac"].astype(str)
    df_mrr = df_mrr[df_mrr["modulo"].notna()]

    merged = df_receita.merge(df_mrr, on="st_sincro_sac", how="inner")
    result = (
        merged.groupby(["mes", "modulo"], as_index=False)
        .agg(receita_emitida=("receita_emitida", "sum"),
             receita_liquidada=("receita_liquidada", "sum"))
    )
    return result


# ─────────────────────────────────────────────
# ── PÁGINA 2: TRANSAÇÕES ─────────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_transactions_por_metodo() -> pd.DataFrame:
    """
    Soma de value por método de pagamento e mês (últimos 15 meses).
    Filtra status IN ('active', 'payed').
    Exclui métodos: free, external, debit.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(datetime AS DATE), MONTH) AS mes,
      method                                    AS payment_method,
      payment_channel,
      SUM(value)                                AS total_value,
      COUNT(*)                                  AS qtd_transacoes
    FROM `inchurch-gcp.backend_bi.view_transaction`
    WHERE
      status IN ('active', 'payed')
      AND method NOT IN ('free', 'external', 'debit')
      AND CAST(datetime AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(datetime AS DATE) <= LAST_DAY(CURRENT_DATE())
    GROUP BY 1, 2, 3
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["mes"]             = pd.to_datetime(df["mes"])
        df["payment_method"]  = df["payment_method"].fillna("Não informado")
        df["payment_channel"] = df["payment_channel"].fillna("Não informado")
    return df