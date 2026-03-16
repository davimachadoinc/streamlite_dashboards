"""
utils/data.py
Helpers de dados, cache, paleta de cores e layout de gráficos.
"""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import numpy as np
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

PLAN_LABELS = {
    "pro":     "PRO",
    "lite":    "LITE",
    "starter": "STARTER",
    "basic":   "BASIC",
    "filha":   "FILHA",
    "squad":   "Squad as a Service",
    "outros":  "Outros",
}

PLAN_COLORS = {
    "pro":     "#6eda2c",
    "lite":    "#ffffff",
    "starter": "#a0a0a0",
    "basic":   "#8ae650",
    "filha":   "#4c4c4c",
    "squad":   "#f0a500",
    "outros":  "#292929",
}

# Filtro SQL para excluir linhas de módulos (KIDS, JORNADA, LOJA, TOTEM, VÍDEOS, módulos STARTER)
# Usar substituindo {col} pelo nome da coluna adequado na query
_EXCL_MODULOS = """
    {col} NOT LIKE '%[KIDS]%'
    AND {col} NOT LIKE '%[JORNADA]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE_INC]%'
    AND {col} NOT LIKE '%[TOTEM]%'
    AND {col} NOT LIKE '%[V_DEOS]%'
    AND NOT ({col} LIKE '%[STARTER]%' AND {col} LIKE '%Módulo%')
"""

# CASE SQL para classificar plano base (usar substituindo {col})
_PLAN_CASE = """
    CASE
      WHEN {col} LIKE '%[PRO]%'          THEN 'pro'
      WHEN {col} LIKE '%[LITE]%'         THEN 'lite'
      WHEN {col} LIKE '%[STARTER]%'      THEN 'starter'
      WHEN {col} LIKE '%[FILHA]%'        THEN 'filha'
      WHEN {col} LIKE '%[BASIC]%'        THEN 'basic'
      WHEN {col} LIKE '%0 - 9 Igrejas%'  THEN 'pro'
      WHEN {col} LIKE '%10+ Igrejas%'    THEN 'pro'
      WHEN {col} LIKE '%App Lite%'        THEN 'lite'
      WHEN {col} LIKE '%App da Igreja%'   THEN 'starter'
      WHEN {col} LIKE '%Squad as a Service%' THEN 'squad'
      ELSE 'outros'
    END
"""


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
    """
    Adiciona coluna mes_fmt (Mmm/YY) e retorna df ordenado + lista cronológica.
    Usar categoryarray no Plotly para garantir ordem correta no eixo X.
    """
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
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


def fmt_brl(value, decimals: int = 2) -> str:
    """Formata número no padrão brasileiro: 1.000,00"""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


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
    """
    Clientes únicos com boleto emitido por mês + totais de receita.
    Deduplicação por id_recebimento_recb via ROW_NUMBER.
    """
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
      COUNT(DISTINCT st_sincro_sac)                                          AS clientes_com_boleto,
      COUNT(id_recebimento_recb)                                             AS total_boletos,
      SUM(vl_total_recb)                                                     AS receita_total,
      SUM(CASE WHEN fl_status_recb = '1' THEN vl_total_recb ELSE 0 END)     AS receita_liquidada
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
    Clientes únicos com cobrança emitida por módulo por mês.
    Identifica módulo via comp_st_descricao_prd diretamente na tabela de cobranças
    (mesmo padrão [KIDS], [JORNADA], [LOJAINTELIGENTE], [LOJAINTELIGENTE_INC]).
    Conta st_sincro_sac distintos que tiveram ao menos 1 linha do módulo no mês.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      CASE
        WHEN comp_st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN comp_st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo,
      COUNT(DISTINCT st_sincro_sac) AS clientes
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.2'
      AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
      AND (
        comp_st_descricao_prd LIKE '%[KIDS]%'
        OR comp_st_descricao_prd LIKE '%[JORNADA]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_receita_modulos_mensais() -> pd.DataFrame:
    """
    Receita por módulo por mês usando comp_valor diretamente na tabela de cobranças.
    Filtra comp_st_conta_cont = '1.2.2' e identifica módulo via comp_st_descricao_prd.
    Isso garante que somente o valor do item Kids/Jornada/Loja entra na soma,
    sem contaminar com plano base, PRO, FILHA ou outros módulos do mesmo boleto.
    """
    query = """
    SELECT
      DATE_TRUNC(CAST(dt_vencimento_recb AS DATE), MONTH) AS mes,
      CASE
        WHEN comp_st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN comp_st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
      END AS modulo,
      SUM(comp_valor)                                                    AS receita_emitida,
      SUM(CASE WHEN fl_status_recb = '1' THEN comp_valor ELSE 0 END)    AS receita_liquidada
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
    WHERE comp_st_conta_cont = '1.2.2'
      AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
      AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
      AND (
        comp_st_descricao_prd LIKE '%[KIDS]%'
        OR comp_st_descricao_prd LIKE '%[JORNADA]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
        OR comp_st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
      )
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
    Status: active ou payed.
    Métodos excluídos: free (valor zero), external (valor zero), debit (volume residual).
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


# ─────────────────────────────────────────────
# ── PÁGINA 3: DESATIVAÇÕES ───────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_desativacoes_mensais() -> pd.DataFrame:
    """
    MRR perdido e clientes desativados por módulo por mês (últimos 15 meses).
    Critério de desativação: dt_fim_mens IS NOT NULL.
    Exclusão de renovações: se dt_fim_mens cai no último dia do mês X e o mesmo
    (st_sincro_sac, st_descricao_prd) tem dt_inicio_mens no mês X+1, não é perda real.
    Módulos identificados via st_descricao_prd; demais itens classificados como 'base'.
    """
    query = """
    WITH desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        CAST(dt_fim_mens AS DATE)                                    AS dt_fim,
        DATE_TRUNC(CAST(dt_fim_mens AS DATE), MONTH)                 AS mes,
        valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND CAST(dt_fim_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_fim_mens AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    renovacoes AS (
      -- (cliente, produto) com dt_fim_mens no último dia do mês
      -- e um novo dt_inicio_mens no mês seguinte → renovação, não desativação
      SELECT DISTINCT
        d.st_sincro_sac,
        d.st_descricao_prd,
        d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac    = r.st_sincro_sac
        AND d.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
    )
    SELECT
      d.mes,
      CASE
        WHEN d.st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN d.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        ELSE                                                         'base'
      END                                                       AS modulo,
      COUNT(DISTINCT d.st_sincro_sac)                           AS clientes_desativados,
      SUM(d.valor_total)                                        AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    WHERE rv.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]    = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_receita_planos_mensais() -> pd.DataFrame:
    """
    Receita emitida e liquidada por PLANO BASE por mês (últimos 15 meses).
    Exclui linhas de módulos (KIDS, JORNADA, LOJA, TOTEM, VÍDEOS, módulos STARTER).
    Classifica plano via comp_st_descricao_prd usando o DE-PARA validado.
    """
    query = f"""
    WITH boleto_plano AS (
      -- Para cada boleto, identifica o plano base a partir das linhas que não são Reajuste Anual
      SELECT
        id_recebimento_recb,
        MAX(CASE
          WHEN comp_st_descricao_prd LIKE '%[PRO]%'         THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%[LITE]%'        THEN 'lite'
          WHEN comp_st_descricao_prd LIKE '%[STARTER]%'     THEN 'starter'
          WHEN comp_st_descricao_prd LIKE '%[FILHA]%'       THEN 'filha'
          WHEN comp_st_descricao_prd LIKE '%[BASIC]%'       THEN 'basic'
          WHEN comp_st_descricao_prd LIKE '%0 - 9 Igrejas%' THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%10+ Igrejas%'   THEN 'pro'
          WHEN comp_st_descricao_prd LIKE '%App Lite%'      THEN 'lite'
          WHEN comp_st_descricao_prd LIKE '%App da Igreja%' THEN 'starter'
          ELSE NULL
        END) AS plano_boleto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE comp_st_conta_cont = '1.2.2'
        AND comp_st_descricao_prd != 'Reajuste Anual'
        AND {_EXCL_MODULOS.format(col="comp_st_descricao_prd")}
      GROUP BY 1
    ),
    linhas AS (
      SELECT
        st_sincro_sac,
        dt_vencimento_recb,
        id_recebimento_recb,
        comp_valor,
        fl_status_recb,
        comp_st_descricao_prd,
        {_PLAN_CASE.format(col="comp_st_descricao_prd")} AS plano_direto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE comp_st_conta_cont = '1.2.2'
        AND CAST(dt_vencimento_recb AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_vencimento_recb AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND {_EXCL_MODULOS.format(col="comp_st_descricao_prd")}
    )
    SELECT
      DATE_TRUNC(CAST(l.dt_vencimento_recb AS DATE), MONTH)            AS mes,
      CASE
        WHEN l.comp_st_descricao_prd = 'Reajuste Anual'
          THEN COALESCE(bp.plano_boleto, 'outros')
        ELSE l.plano_direto
      END                                                               AS plano,
      COUNT(DISTINCT l.st_sincro_sac)                                   AS clientes,
      SUM(l.comp_valor)                                                 AS receita_emitida,
      SUM(CASE WHEN l.fl_status_recb = '1' THEN l.comp_valor ELSE 0 END) AS receita_liquidada
    FROM linhas l
    LEFT JOIN boleto_plano bp
      ON l.id_recebimento_recb = bp.id_recebimento_recb
      AND l.comp_st_descricao_prd = 'Reajuste Anual'
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_desativacoes_por_plano() -> pd.DataFrame:
    """
    Desativações de PLANO BASE por mês (exclui módulos).
    Aplica a mesma lógica de exclusão de renovações de load_desativacoes_mensais:
    dt_fim_mens no último dia do mês + dt_inicio_mens no mês seguinte = renovação, não churn.
    """
    query = f"""
    WITH desativados AS (
      SELECT
        st_sincro_sac,
        st_descricao_prd,
        CAST(dt_fim_mens AS DATE)                                    AS dt_fim,
        DATE_TRUNC(CAST(dt_fim_mens AS DATE), MONTH)                 AS mes,
        valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND CAST(dt_fim_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(dt_fim_mens AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_MODULOS.format(col="st_descricao_prd")}
    ),
    renovacoes AS (
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac    = r.st_sincro_sac
        AND d.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
    )
    SELECT
      d.mes,
      {_PLAN_CASE.format(col="d.st_descricao_prd")}                  AS plano,
      COUNT(DISTINCT d.st_sincro_sac)                                 AS clientes_desativados,
      SUM(d.valor_total)                                              AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    WHERE rv.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_desativacoes_detalhado() -> pd.DataFrame:
    """
    Desativações no nível de cliente — mês, módulo, plano, nome e MRR perdido.
    Aplica a mesma lógica de exclusão de renovações.
    Join com splgc-clientes-inchurch para obter o nome do cliente.
    """
    query = f"""
    WITH desativados AS (
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(m.dt_fim_mens AS DATE)                              AS dt_fim,
        DATE_TRUNC(CAST(m.dt_fim_mens AS DATE), MONTH)           AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      WHERE m.dt_fim_mens IS NOT NULL
        AND CAST(m.dt_fim_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH)
        AND CAST(m.dt_fim_mens AS DATE) <= LAST_DAY(CURRENT_DATE())
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    renovacoes AS (
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON  d.st_sincro_sac    = r.st_sincro_sac
        AND d.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim)
        AND r.dt_inicio_mens IS NOT NULL
    )
    SELECT
      d.mes,
      CASE
        WHEN d.st_descricao_prd LIKE '%[KIDS]%'                THEN 'Kids'
        WHEN d.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'Jornada'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'Loja Inteligente'
        WHEN d.st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'Loja Inteligente'
        ELSE                                                        'Base'
      END                                                       AS modulo,
      {_PLAN_CASE.format(col="d.st_descricao_prd")}            AS plano,
      d.st_sincro_sac,
      COALESCE(c.st_nome_sac, d.st_sincro_sac)                 AS nome_cliente,
      d.st_descricao_prd                                        AS produto,
      d.valor_total                                             AS mrr_perdido
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON  d.st_sincro_sac    = rv.st_sincro_sac
      AND d.st_descricao_prd = rv.st_descricao_prd
      AND d.mes              = rv.mes
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON d.st_sincro_sac = c.st_sincro_sac
    WHERE rv.st_sincro_sac IS NULL
    ORDER BY d.mes DESC, d.valor_total DESC
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.upper()
    return df


# ─────────────────────────────────────────────
# ── PÁGINA 4: INADIMPLÊNCIA ───────────────────
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_inadimplencia_serie() -> pd.DataFrame:
    """
    Série histórica de inadimplência — snapshot por dia útil (últimos 6 meses).

    Janela ROLANTE: para cada data de observação D, olha os N dias anteriores de vencimento.
      30d: boletos com vencimento em [D-30, D] — emitido no último mês
      90d: boletos com vencimento em [D-90, D] — emitido nos últimos 3 meses
      Em ambos: aberto = boletos ainda não pagos EM D (dia_pago IS NULL OR dia_pago > D)
      % = aberto / emitido × 100

    Exemplo: em 12/02, 30d olha [13/01–12/02]. Se em 13/02 um boleto vencido em 05/02
    for pago, ele sai do numerador do dia 13/02 em diante.
    """
    # --- 1. Carrega boletos brutos do BigQuery ---
    query = """
    SELECT
      CAST(b.dt_vencimento_recb  AS DATE) AS dia_venc,
      CAST(b.dt_liquidacao_recb  AS DATE) AS dia_pago,
      b.comp_valor
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON b.st_sincro_sac = c.st_sincro_sac
    WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
      AND CAST(b.dt_vencimento_recb AS DATE)
            >= DATE_SUB(CURRENT_DATE(), INTERVAL 18 MONTH)
      AND CAST(b.dt_vencimento_recb AS DATE) < CURRENT_DATE()
      AND (c.dt_desativacao_sac IS NULL
           OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
    """
    df_b = _bq_query(query, "bigquery_bi")
    if df_b.empty:
        return pd.DataFrame()

    df_b["dia_venc"]   = pd.to_datetime(df_b["dia_venc"])
    df_b["dia_pago"]   = pd.to_datetime(df_b["dia_pago"])
    df_b["comp_valor"] = pd.to_numeric(df_b["comp_valor"], errors="coerce").fillna(0)

    # Arrays numpy para operações vetorizadas dentro do loop
    v      = df_b["dia_venc"].values    # datetime64[ns]
    p      = df_b["dia_pago"].values    # datetime64[ns] — NaT se não pago
    c_vals = df_b["comp_valor"].values

    # --- 2. Datas de observação: dias úteis últimos 6 meses até 2 dias úteis atrás ---
    today_ts  = pd.Timestamp.today().normalize()
    end_obs   = today_ts - pd.tseries.offsets.BDay(2)
    start_obs = today_ts - pd.DateOffset(months=6)
    obs_dates = pd.bdate_range(start=start_obs, end=end_obs)

    # --- 3. Snapshot para cada data de observação ---
    rows = []
    for D in obs_dates:
        D_np      = np.datetime64(D)
        D_30_ini  = np.datetime64(D - pd.Timedelta(days=30))   # início janela 30d
        D_90_ini  = np.datetime64(D - pd.Timedelta(days=90))   # início janela 90d

        # Boleto aberto EM D: não pago ou pago depois de D
        is_open = np.isnat(p) | (p > D_np)

        # 30d: vencimento em [D-30, D]  ← janela rolante de 30 dias
        m_30        = (v >= D_30_ini) & (v <= D_np)
        emitido_30d = float(c_vals[m_30].sum())
        aberto_30d  = float(c_vals[m_30 & is_open].sum())

        # 90d: vencimento em [D-90, D]  ← janela rolante de 90 dias
        m_90        = (v >= D_90_ini) & (v <= D_np)
        emitido_90d = float(c_vals[m_90].sum())
        aberto_90d  = float(c_vals[m_90 & is_open].sum())

        # emitido/aberto geral (alias de 90d, mantido para compatibilidade com KPIs)
        emitido = emitido_90d
        aberto  = aberto_90d

        rows.append({
            "dia":         D,
            "emitido":     emitido,
            "aberto":      aberto,
            "emitido_30d": emitido_30d,
            "aberto_30d":  aberto_30d,
            "emitido_90d": emitido_90d,
            "aberto_90d":  aberto_90d,
        })

    result = pd.DataFrame(rows)
    result["dia"] = pd.to_datetime(result["dia"])
    result["pct_inadimp"]     = (result["aberto"]     / result["emitido"].where(result["emitido"] > 0)         * 100).round(2)
    result["pct_inadimp_30d"] = (result["aberto_30d"] / result["emitido_30d"].where(result["emitido_30d"] > 0) * 100).round(2)
    result["pct_inadimp_90d"] = (result["aberto_90d"] / result["emitido_90d"].where(result["emitido_90d"] > 0) * 100).round(2)
    return result


@st.cache_data(ttl=3600)
def load_inadimplencia_por_plano() -> pd.DataFrame:
    """
    Inadimplência 30d atual agregada por plano base.
    Retorna clientes únicos inadimplentes e valor em aberto por plano.
    """
    query = f"""
    SELECT
      {_PLAN_CASE.format(col="b.comp_st_descricao_prd")}              AS plano,
      COUNT(DISTINCT b.st_sincro_sac)                                  AS clientes_inadimplentes,
      SUM(b.comp_valor)                                                AS valor_aberto
    FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON b.st_sincro_sac = c.st_sincro_sac
    WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
      AND b.fl_status_recb = '0'
      AND b.comp_valor > 1
      AND CAST(b.dt_vencimento_recb AS DATE)
            BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
      AND (c.dt_desativacao_sac IS NULL
           OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
      AND {_EXCL_MODULOS.format(col="b.comp_st_descricao_prd")}
      AND EXISTS (
        SELECT 1
        FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
        WHERE pago.st_sincro_sac = b.st_sincro_sac
          AND pago.fl_status_recb = '1'
      )
    GROUP BY 1
    ORDER BY valor_aberto DESC
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_inadimplencia_por_frequencia() -> pd.DataFrame:
    """
    Distribuição de clientes inadimplentes (30d) por quantidade de boletos em aberto.
    Buckets: 1, 2-4, 5-9, 10-14, 15-19, 20+
    """
    query = """
    WITH inadimplentes AS (
      SELECT
        b.st_sincro_sac,
        COUNT(DISTINCT b.id_recebimento_recb) AS boletos_abertos,
        SUM(b.comp_valor)                      AS valor_aberto
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
      LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON b.st_sincro_sac = c.st_sincro_sac
      WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
        AND b.fl_status_recb = '0'
        AND CAST(b.dt_vencimento_recb AS DATE)
              BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY) AND CURRENT_DATE()
        AND (c.dt_desativacao_sac IS NULL
             OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
      GROUP BY 1
    )
    SELECT
      CASE
        WHEN boletos_abertos = 1          THEN '1 boleto'
        WHEN boletos_abertos BETWEEN 2 AND 4   THEN '2 – 4 boletos'
        WHEN boletos_abertos BETWEEN 5 AND 9   THEN '5 – 9 boletos'
        WHEN boletos_abertos BETWEEN 10 AND 14 THEN '10 – 14 boletos'
        WHEN boletos_abertos BETWEEN 15 AND 19 THEN '15 – 19 boletos'
        ELSE '20+ boletos'
      END                              AS faixa,
      COUNT(*)                         AS clientes,
      SUM(valor_aberto)                AS valor_aberto
    FROM inadimplentes
    GROUP BY 1
    ORDER BY MIN(boletos_abertos)
    """
    df = _bq_query(query, "bigquery_bi")
    return df


@st.cache_data(ttl=3600)
def load_inadimplencia_top_clientes(dias: int = 30) -> pd.DataFrame:
    """
    Top 30 clientes com maior valor em aberto na janela rolante de N dias.
    Só conta clientes com comp_valor > 1 e que já pagaram pelo menos um boleto.
    """
    query = f"""
    WITH inad AS (
      SELECT
        b.st_sincro_sac,
        COUNT(DISTINCT b.id_recebimento_recb)                          AS boletos_abertos,
        SUM(b.comp_valor)                                              AS valor_aberto,
        MAX(DATE_DIFF(CURRENT_DATE(), CAST(b.dt_vencimento_recb AS DATE), DAY)) AS max_dias_atraso,
        {_PLAN_CASE.format(col="MAX(b.comp_st_descricao_prd)")}        AS plano
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` b
      LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON b.st_sincro_sac = c.st_sincro_sac
      WHERE b.comp_st_conta_cont IN ('1.2.1', '1.2.2')
        AND b.fl_status_recb = '0'
        AND b.comp_valor > 1
        AND CAST(b.dt_vencimento_recb AS DATE)
              BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL {dias} DAY) AND CURRENT_DATE()
        AND (c.dt_desativacao_sac IS NULL
             OR c.dt_desativacao_sac > CAST(b.dt_vencimento_recb AS DATE))
        AND {_EXCL_MODULOS.format(col="b.comp_st_descricao_prd")}
        AND EXISTS (
          SELECT 1
          FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all` pago
          WHERE pago.st_sincro_sac = b.st_sincro_sac
            AND pago.fl_status_recb = '1'
        )
      GROUP BY 1
    )
    SELECT
      i.st_sincro_sac                  AS id_cliente,
      c.st_nome_sac                    AS nome_cliente,
      i.plano,
      ROUND(i.valor_aberto, 2)         AS valor_aberto,
      i.boletos_abertos,
      i.max_dias_atraso
    FROM inad i
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON i.st_sincro_sac = c.st_sincro_sac
    ORDER BY i.valor_aberto DESC
    LIMIT 30
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["plano"] = df["plano"].str.lower()
    return df


@st.cache_data(ttl=3600)
def load_base_ativa_por_plano() -> pd.DataFrame:
    """
    Clientes ativos por PLANO BASE no início de cada mês (últimos 15 meses).
    Usado como denominador para cálculo de churn: item ativo se
    dt_inicio_mens <= primeiro dia do mês E (dt_fim_mens IS NULL OR dt_fim_mens > primeiro dia do mês).
    Exclui módulos para contar apenas o plano base de cada cliente.
    """
    query = f"""
    SELECT
      cal.mes,
      {_PLAN_CASE.format(col="mrr.st_descricao_prd")}                AS plano,
      COUNT(DISTINCT mrr.st_sincro_sac)                               AS clientes_ativos
    FROM (
      SELECT mes
      FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 15 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ) cal
    CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
    WHERE CAST(mrr.dt_inicio_mens AS DATE) <= cal.mes
      AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) > cal.mes)
      AND {_EXCL_MODULOS.format(col="mrr.st_descricao_prd")}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _bq_query(query, "bigquery_bi")
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df