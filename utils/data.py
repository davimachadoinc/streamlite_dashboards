"""
utils/data.py
Helpers de dados, cache, paleta de cores e layout de gráficos.
Todas as queries BigQuery e funções de transformação ficam aqui.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from datetime import date
from dateutil.relativedelta import relativedelta

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

# Mapeamento de módulos para nomes amigáveis
MODULE_LABELS = {
    "kids":            "Kids",
    "jornada":         "Jornada",
    "loja_inteligente": "Loja Inteligente",
}

# Cores dedicadas por módulo (para consistência entre gráficos)
MODULE_COLORS = {
    "kids":            "#6eda2c",
    "jornada":         "#ffffff",
    "loja_inteligente": "#a0a0a0",
    "base":            "#4c4c4c",
}


# ─────────────────────────────────────────────
# LAYOUT PADRÃO DE GRÁFICOS
# ─────────────────────────────────────────────
def chart_layout(fig: go.Figure, height: int = 380, legend_bottom: bool = False) -> go.Figure:
    """Aplicar estilo padrão InChurch em todos os gráficos Plotly."""
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
            zeroline=False, title="",
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


# ─────────────────────────────────────────────
# SELETORES DE PERÍODO
# ─────────────────────────────────────────────
def period_selector() -> int:
    """
    Renderiza seletor de número de meses (sidebar).
    Retorna n_months (int). 0 = todos os dados.
    """
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
    """
    Filtra o DataFrame para os últimos n_months meses a partir de hoje.
    n_months=0 retorna tudo.
    """
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
    """Último valor de uma série ordenada por data."""
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-1] if len(ordered) >= 1 else None


def prev_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    """Penúltimo valor (para cálculo de delta)."""
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    return ordered[col].iloc[-2] if len(ordered) >= 2 else None


def delta_str(curr, prev, fmt: str = "+,.0f", suffix: str = "") -> str | None:
    """Formata delta como string. Retorna None se dados insuficientes."""
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
# CONEXÃO BIGQUERY
# ─────────────────────────────────────────────
def _bq_query(query: str, project_key: str = "bigquery_tech") -> pd.DataFrame:
    """Executa query no BigQuery usando st.connection."""
    try:
        conn = st.connection(project_key, type="sql")
        return conn.query(query, ttl=3600)
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery ({project_key}): {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# ── PÁGINA 1: COBRANÇA / MÓDULOS ─────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_contratos_mensais() -> pd.DataFrame:
    """
    Clientes únicos com boleto emitido por mês (últimos 15 meses).
    Deduplicação por id_recebimento_recb via ROW_NUMBER.
    """
    query = """
    WITH dedup AS (
      SELECT
        st_sincro_sac,
        DATE_TRUNC(dt_vencimento_recb, MONTH) AS mes,
        id_recebimento_recb,
        vl_total_recb,
        fl_status_recb,
        dt_liquidacao_recb,
        ROW_NUMBER() OVER (
          PARTITION BY id_recebimento_recb
          ORDER BY dt_vencimento_recb
        ) AS rn
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE dt_vencimento_recb >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 15 MONTH), MONTH)
    )
    SELECT
      mes,
      COUNT(DISTINCT st_sincro_sac) AS clientes_com_boleto,
      COUNT(id_recebimento_recb)    AS total_boletos,
      SUM(vl_total_recb)            AS receita_total,
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
    Contagem de clientes ativos com boleto emitido + módulo contratado,
    por mês (kids, jornada, loja_inteligente).
    """
    query = """
    WITH periodos AS (
      SELECT
        DATE_TRUNC(dt_vencimento_recb, MONTH) AS mes,
        st_sincro_sac
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE dt_vencimento_recb >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 15 MONTH), MONTH)
      GROUP BY 1, 2
    ),
    features AS (
      SELECT
        CAST(tertiarygroup_id AS STRING) AS st_sincro_sac,
        feature_alias
      FROM `inchurch-gcp.backend_bi.view_feature_subscription`
      WHERE LOWER(feature_alias) IN ('kids', 'jornada', 'loja_inteligente')
    )
    SELECT
      p.mes,
      f.feature_alias                     AS modulo,
      COUNT(DISTINCT p.st_sincro_sac)     AS clientes
    FROM periodos p
    JOIN features f ON p.st_sincro_sac = f.st_sincro_sac
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_receita_modulos_mensais() -> pd.DataFrame:
    """
    Soma de receita por módulo (kids, jornada, loja_inteligente) por mês,
    com flag de liquidação. Usa st_descricao_prd para identificar o módulo
    no MRR, cruzado com clientes que têm boleto emitido no mês.
    """
    query = """
    WITH boletos AS (
      SELECT
        DATE_TRUNC(dt_vencimento_recb, MONTH) AS mes,
        st_sincro_sac,
        SUM(vl_total_recb)                    AS receita_emitida,
        SUM(CASE WHEN fl_status_recb = '1' THEN vl_total_recb ELSE 0 END) AS receita_liquidada
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE dt_vencimento_recb >= DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 15 MONTH), MONTH)
      GROUP BY 1, 2
    ),
    mrr AS (
      SELECT
        st_sincro_sac,
        CASE
          WHEN LOWER(st_descricao_prd) LIKE '%[kids]%'             THEN 'kids'
          WHEN LOWER(st_descricao_prd) LIKE '%[jornada]%'          THEN 'jornada'
          WHEN LOWER(st_descricao_prd) LIKE '%[loja_inteligente]%' THEN 'loja_inteligente'
          ELSE NULL
        END AS modulo
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE
        dt_inicio_mens <= CURRENT_TIMESTAMP()
        AND (dt_fim_mens IS NULL OR dt_fim_mens > CURRENT_TIMESTAMP())
    )
    SELECT
      b.mes,
      m.modulo,
      SUM(b.receita_emitida)    AS receita_emitida,
      SUM(b.receita_liquidada)  AS receita_liquidada
    FROM boletos b
    JOIN mrr m ON b.st_sincro_sac = m.st_sincro_sac
    WHERE m.modulo IS NOT NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


# ─────────────────────────────────────────────
# ── PÁGINA 2: TRANSAÇÕES ─────────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_transactions_por_metodo() -> pd.DataFrame:
    """
    Soma de value por método de pagamento e mês (últimos 15 meses).
    Filtra status IN ('active', 'payed').
    Inclui payment_channel para filtro no frontend.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(datetime AS DATE), MONTH)  AS mes,
      payment_method,
      payment_channel,
      SUM(value)                                  AS total_value,
      COUNT(*)                                    AS qtd_transacoes
    FROM `inchurch-gcp.backend_bi.view_transaction`
    WHERE
      status IN ('active', 'payed')
      AND datetime >= TIMESTAMP(DATE_TRUNC(DATE_SUB(CURRENT_DATE(), INTERVAL 15 MONTH), MONTH))
    GROUP BY 1, 2, 3
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_tech")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        # Tratar nulos
        df["payment_method"]  = df["payment_method"].fillna("Não informado")
        df["payment_channel"] = df["payment_channel"].fillna("Não informado")
    return df
