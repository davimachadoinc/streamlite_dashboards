"""
utils/data.py
Camada de dados — Unit Economics InChurch.
Fontes: BigQuery BI (BQ_BI), BigQuery Tech (BQ_TECH), Google Drive (despesas).
"""
from __future__ import annotations

import io
import re
import json
import csv as _csv
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date
from dateutil.relativedelta import relativedelta
from google.oauth2 import service_account
from google.cloud import bigquery

# ─────────────────────────────────────────────
# PALETA & CONSTANTES VISUAIS
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
    "#e74c3c",  # 9 — vermelho (churn)
]

PLAN_LABELS = {
    "pro":     "PRO",
    "lite":    "LITE",
    "starter": "STARTER",
    "basic":   "BASIC",
    "filha":   "FILHA",
    "squad":   "Squad",
    "outros":  "Outros",
}
PLAN_COLORS = {
    "pro":     "#6eda2c",
    "lite":    "#ffffff",
    "starter": "#a0a0a0",
    "basic":   "#8ae650",
    "filha":   "#4c4c4c",
    "squad":   "#f0a500",
    "outros":  "#3a3a3a",
}

MODULE_LABELS = {
    "kids":             "Kids",
    "jornada":          "Jornada",
    "loja_inteligente": "Loja Inteligente",
    "totem":            "Totem",
    "upgrade_plano":    "Upgrade de Plano",
}
MODULE_COLORS = {
    "kids":             "#6eda2c",
    "jornada":          "#ffffff",
    "loja_inteligente": "#a0a0a0",
    "totem":            "#8ae650",
    "upgrade_plano":    "#4c4c4c",
}

# Centros de custo que entram no CAC
CAC_CENTROS = [
    "Field Sales", "Inbound", "Sales", "Outside Sales",  # comercial
    "Marketing",                                          # marketing
    "Eventos", "Parceiros",                               # parcerias
    "Outbound",                                           # outbound
]

# Google Drive — pasta compartilhada com o Controle_Budget
_FOLDER_ID = "1BSuJkp8wPxMwCXBxADuyoaNvy8VTJ-sh"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SHEET_MIME = "application/vnd.google-apps.spreadsheet"

# Filtro SQL para excluir linhas de módulos (só plano base)
_EXCL_MODULOS = """
    {col} NOT LIKE '%[KIDS]%'
    AND {col} NOT LIKE '%[JORNADA]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE]%'
    AND {col} NOT LIKE '%[LOJAINTELIGENTE_INC]%'
    AND {col} NOT LIKE '%[TOTEM]%'
    AND NOT ({col} LIKE '%[STARTER]%' AND {col} LIKE '%Módulo%')
"""

_PLAN_CASE = """
    CASE
      WHEN {col} LIKE '%[PRO]%'               THEN 'pro'
      WHEN {col} LIKE '%[LITE]%'              THEN 'lite'
      WHEN {col} LIKE '%[STARTER]%'           THEN 'starter'
      WHEN {col} LIKE '%[FILHA]%'             THEN 'filha'
      WHEN {col} LIKE '%[BASIC]%'             THEN 'basic'
      WHEN {col} LIKE '%0 - 9 Igrejas%'       THEN 'pro'
      WHEN {col} LIKE '%10+ Igrejas%'         THEN 'pro'
      WHEN {col} LIKE '%App Lite%'            THEN 'lite'
      WHEN {col} LIKE '%App da Igreja%'       THEN 'starter'
      WHEN {col} LIKE '%Squad as a Service%'  THEN 'squad'
      ELSE 'outros'
    END
"""


# ─────────────────────────────────────────────
# HELPERS VISUAIS
# ─────────────────────────────────────────────
def chart_layout(fig: go.Figure, height: int = 380, legend_bottom: bool = False) -> go.Figure:
    legend_cfg = dict(bgcolor="rgba(0,0,0,0)", font=dict(family="Outfit", size=12, color="#a0a0a0"))
    if legend_bottom:
        legend_cfg.update(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5)
    fig.update_layout(
        height=height,
        template="plotly_dark",
        margin=dict(l=4, r=4, t=32, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#ffffff", size=13),
        legend=legend_cfg,
        xaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title="", type="category"),
        yaxis=dict(showgrid=True, gridcolor="#292929", gridwidth=1, zeroline=False, title=""),
        hoverlabel=dict(bgcolor="#141414", bordercolor="#292929", font_size=13,
                        font_family="Outfit, sans-serif", font_color="#ffffff"),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    return df, df["mes_fmt"].drop_duplicates().tolist()


def period_selector(key: str = "default") -> int:
    with st.sidebar:
        st.markdown("### 🗓️ Período")
        n = st.selectbox(
            "Últimos N meses",
            options=[3, 6, 12, 18, 0],
            index=2,
            format_func=lambda x: "Todos" if x == 0 else f"Últimos {x} meses",
            key=f"period_{key}",
        )
    return n


def filter_months(df: pd.DataFrame, n_months: int, date_col: str = "mes") -> pd.DataFrame:
    if df.empty or n_months == 0:
        return df
    cutoff = pd.Timestamp(date.today() - relativedelta(months=n_months))
    col = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(col):
        col = pd.to_datetime(col, errors="coerce")
    return df[col >= cutoff].copy()


def last_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    val = df.sort_values(date_col)[col].iloc[-1]
    return None if pd.isna(val) else val


def prev_val(df: pd.DataFrame, col: str, date_col: str = "mes"):
    if df.empty or col not in df.columns:
        return None
    ordered = df.sort_values(date_col)
    if len(ordered) < 2:
        return None
    val = ordered[col].iloc[-2]
    return None if pd.isna(val) else val


def delta_str(curr, prev, fmt: str = "+,.0f", suffix: str = "") -> str | None:
    if curr is None or prev is None:
        return None
    try:
        return f"{curr - prev:{fmt}}{suffix}"
    except Exception:
        return f"{curr - prev:+.2f}{suffix}"


def fmt_brl(value, decimals: int = 0) -> str:
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CONEXÃO BIGQUERY
# ─────────────────────────────────────────────
def _get_bq_client(project_key: str) -> bigquery.Client:
    cfg = st.secrets["connections"][project_key]
    project = cfg["project"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=project, credentials=credentials)


@st.cache_resource
def _bq_bi() -> bigquery.Client:
    return _get_bq_client("bigquery_bi")


@st.cache_resource
def _bq_tech() -> bigquery.Client:
    return _get_bq_client("bigquery_tech")


def _query_bi(query: str) -> pd.DataFrame:
    try:
        return _bq_bi().query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro BigQuery BI: {e}")
        return pd.DataFrame()


def _query_tech(query: str) -> pd.DataFrame:
    try:
        return _bq_tech().query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro BigQuery Tech: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# GOOGLE DRIVE — acesso às despesas
# ─────────────────────────────────────────────
@st.cache_resource
def _drive_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=creds)


@st.cache_data(ttl=21600)
def _list_drive_folder() -> list[dict]:
    svc = _drive_service()
    q = f"'{_FOLDER_ID}' in parents and trashed=false"
    res = svc.files().list(q=q, fields="files(id,name,mimeType)", pageSize=200).execute()
    return res.get("files", [])


def _find_in_folder(pattern: str, mime: str = None) -> str | None:
    for f in _list_drive_folder():
        if mime and f["mimeType"] != mime:
            continue
        if re.fullmatch(pattern, f["name"]):
            return f["id"]
    return None


@st.cache_data(ttl=21600)
def _download_sheet_csv(file_id: str) -> str:
    from googleapiclient.http import MediaIoBaseDownload
    svc = _drive_service()
    request = svc.files().export_media(fileId=file_id, mimeType="text/csv")
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


@st.cache_data(ttl=21600)
def _download_file(file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    svc = _drive_service()
    request = svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


# ─────────────────────────────────────────────
# QUERY 1 — MRR WATERFALL MENSAL
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_mrr_waterfall() -> pd.DataFrame:
    """
    Retorna por mês (últimos 18 meses):
      mrr_inicio, clientes_inicio,
      new_logo_mrr, new_clients,
      expansion_mrr, expanded_clients,
      churned_mrr, churned_clients,
      mrr_fim,
      nrr (%)
    Upsell = produtos com dt_inicio > min(dt_inicio) do cliente, excluindo renovações.
    """
    query = f"""
    WITH
    meses AS (
      SELECT mes FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ),
    primeiro_inicio AS (
      SELECT
        st_sincro_sac,
        MIN(CAST(dt_inicio_mens AS DATE)) AS dt_first
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      GROUP BY 1
    ),
    -- MRR ativo no início de cada mês (snapshot: contratos que já iniciaram mas não terminaram)
    mrr_inicio_mes AS (
      SELECT
        cal.mes,
        SUM(mrr.valor_total)              AS mrr_inicio,
        COUNT(DISTINCT mrr.st_sincro_sac) AS clientes_inicio
      FROM meses cal
      CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
      WHERE CAST(mrr.dt_inicio_mens AS DATE) < cal.mes
        AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) >= cal.mes)
        AND mrr.st_descricao_prd NOT LIKE '%Setup%'
        AND mrr.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      GROUP BY 1
    ),
    -- New Logo: todos os produtos que iniciaram no mesmo dia = dt_first do cliente
    new_logo_mes AS (
      SELECT
        DATE_TRUNC(p.dt_first, MONTH)     AS mes,
        SUM(m.valor_total)                AS new_logo_mrr,
        COUNT(DISTINCT p.st_sincro_sac)   AS new_clients
      FROM primeiro_inicio p
      JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
        ON p.st_sincro_sac = m.st_sincro_sac
        AND CAST(m.dt_inicio_mens AS DATE) = p.dt_first
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      WHERE DATE_TRUNC(p.dt_first, MONTH) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
      GROUP BY 1
    ),
    -- Expansion candidatos: dt_inicio > dt_first do cliente
    expansao_raw AS (
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(m.dt_inicio_mens AS DATE)                             AS dt_inicio,
        DATE_TRUNC(CAST(m.dt_inicio_mens AS DATE), MONTH)          AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      JOIN primeiro_inicio p ON m.st_sincro_sac = p.st_sincro_sac
      WHERE CAST(m.dt_inicio_mens AS DATE) > p.dt_first
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND CAST(m.dt_inicio_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
    ),
    -- Excluir renovações da expansion: mesmo produto que encerrou no último dia do mês anterior
    renovacoes_exp AS (
      SELECT DISTINCT e.st_sincro_sac, e.st_descricao_prd, e.mes
      FROM expansao_raw e
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` prev
        ON e.st_sincro_sac    = prev.st_sincro_sac
        AND e.st_descricao_prd = prev.st_descricao_prd
        AND CAST(prev.dt_fim_mens AS DATE) = LAST_DAY(CAST(prev.dt_fim_mens AS DATE))
        AND DATE_TRUNC(CAST(prev.dt_fim_mens AS DATE), MONTH) = DATE_SUB(e.mes, INTERVAL 1 MONTH)
    ),
    expansion_mes AS (
      SELECT
        e.mes,
        SUM(e.valor_total)                AS expansion_mrr,
        COUNT(DISTINCT e.st_sincro_sac)   AS expanded_clients
      FROM expansao_raw e
      LEFT JOIN renovacoes_exp r
        ON e.st_sincro_sac = r.st_sincro_sac AND e.st_descricao_prd = r.st_descricao_prd AND e.mes = r.mes
      WHERE r.st_sincro_sac IS NULL
      GROUP BY 1
    ),
    -- Churn (com exclusão de renovações — mesmo padrão do dashboard de desativações)
    desativados_raw AS (
      SELECT
        st_sincro_sac, st_descricao_prd,
        CAST(dt_fim_mens AS DATE)                            AS dt_fim,
        DATE_TRUNC(CAST(dt_fim_mens AS DATE), MONTH)         AS mes,
        valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND CAST(dt_fim_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      UNION ALL
      SELECT
        m.st_sincro_sac, m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                   AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH) AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      QUALIFY ROW_NUMBER() OVER (PARTITION BY m.st_sincro_sac, m.st_descricao_prd ORDER BY m.dt_inicio_mens DESC) = 1
    ),
    renovacoes_churn AS (
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados_raw d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON d.st_sincro_sac    = r.st_sincro_sac
        AND d.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim) AND r.dt_inicio_mens IS NOT NULL
    ),
    churn_mes AS (
      SELECT
        d.mes,
        SUM(d.valor_total)                AS churned_mrr,
        COUNT(DISTINCT d.st_sincro_sac)   AS churned_clients
      FROM desativados_raw d
      LEFT JOIN renovacoes_churn rc
        ON d.st_sincro_sac = rc.st_sincro_sac AND d.st_descricao_prd = rc.st_descricao_prd AND d.mes = rc.mes
      WHERE rc.st_sincro_sac IS NULL
      GROUP BY 1
    )
    SELECT
      m.mes,
      COALESCE(mi.mrr_inicio, 0)       AS mrr_inicio,
      COALESCE(mi.clientes_inicio, 0)  AS clientes_inicio,
      COALESCE(nl.new_logo_mrr, 0)     AS new_logo_mrr,
      COALESCE(nl.new_clients, 0)      AS new_clients,
      COALESCE(e.expansion_mrr, 0)     AS expansion_mrr,
      COALESCE(e.expanded_clients, 0)  AS expanded_clients,
      COALESCE(c.churned_mrr, 0)       AS churned_mrr,
      COALESCE(c.churned_clients, 0)   AS churned_clients,
      COALESCE(mi.mrr_inicio, 0) + COALESCE(nl.new_logo_mrr, 0)
        + COALESCE(e.expansion_mrr, 0) - COALESCE(c.churned_mrr, 0) AS mrr_fim
    FROM meses m
    LEFT JOIN mrr_inicio_mes mi ON m.mes = mi.mes
    LEFT JOIN new_logo_mes    nl ON m.mes = nl.mes
    LEFT JOIN expansion_mes   e  ON m.mes = e.mes
    LEFT JOIN churn_mes        c  ON m.mes = c.mes
    ORDER BY m.mes
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        # NRR: retorno sobre a base existente (exclui new logo do numerador)
        df["nrr"] = df.apply(
            lambda r: round((r["mrr_inicio"] + r["expansion_mrr"] - r["churned_mrr"])
                            / r["mrr_inicio"] * 100, 1)
            if r["mrr_inicio"] > 0 else None,
            axis=1,
        )
    return df


# ─────────────────────────────────────────────
# QUERY 2 — MRR ATIVO POR PLANO (snapshot)
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_mrr_por_plano() -> pd.DataFrame:
    """MRR ativo no início de cada mês por plano base (últimos 18 meses)."""
    query = f"""
    SELECT
      cal.mes,
      {_PLAN_CASE.format(col="mrr.st_descricao_prd")}        AS plano,
      SUM(mrr.valor_total)                                    AS mrr,
      COUNT(DISTINCT mrr.st_sincro_sac)                       AS clientes
    FROM (
      SELECT mes FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ) cal
    CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
    WHERE CAST(mrr.dt_inicio_mens AS DATE) < cal.mes
      AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) >= cal.mes)
      AND mrr.st_descricao_prd NOT LIKE '%Setup%'
      AND mrr.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      AND {_EXCL_MODULOS.format(col="mrr.st_descricao_prd")}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 3 — NOVOS CLIENTES POR PLANO
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_new_logos_por_plano() -> pd.DataFrame:
    """Clientes novos por plano por mês — primeiro produto ativado (últimos 18 meses)."""
    query = f"""
    WITH primeiro_inicio AS (
      SELECT
        st_sincro_sac,
        MIN(CAST(dt_inicio_mens AS DATE)) AS dt_first
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      GROUP BY 1
    )
    SELECT
      DATE_TRUNC(p.dt_first, MONTH)                           AS mes,
      {_PLAN_CASE.format(col="m.st_descricao_prd")}           AS plano,
      COUNT(DISTINCT p.st_sincro_sac)                         AS new_clients,
      SUM(m.valor_total)                                      AS new_logo_mrr
    FROM primeiro_inicio p
    JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      ON p.st_sincro_sac = m.st_sincro_sac
      AND CAST(m.dt_inicio_mens AS DATE) = p.dt_first
      AND m.st_descricao_prd NOT LIKE '%Setup%'
      AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      AND {_EXCL_MODULOS.format(col="m.st_descricao_prd")}
    WHERE DATE_TRUNC(p.dt_first, MONTH) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 4 — EXPANSION MRR POR MÓDULO/TIPO
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_expansion_por_modulo() -> pd.DataFrame:
    """
    Expansion MRR por tipo de upsell (módulo ou upgrade de plano) por mês.
    Exclui renovações. Upsell = dt_inicio > min(dt_inicio) do cliente.
    """
    query = """
    WITH
    primeiro_inicio AS (
      SELECT st_sincro_sac, MIN(CAST(dt_inicio_mens AS DATE)) AS dt_first
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      GROUP BY 1
    ),
    expansao_raw AS (
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(m.dt_inicio_mens AS DATE)                           AS dt_inicio,
        DATE_TRUNC(CAST(m.dt_inicio_mens AS DATE), MONTH)        AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      JOIN primeiro_inicio p ON m.st_sincro_sac = p.st_sincro_sac
      WHERE CAST(m.dt_inicio_mens AS DATE) > p.dt_first
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND CAST(m.dt_inicio_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
    ),
    renovacoes_exp AS (
      SELECT DISTINCT e.st_sincro_sac, e.st_descricao_prd, e.mes
      FROM expansao_raw e
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` prev
        ON e.st_sincro_sac     = prev.st_sincro_sac
        AND e.st_descricao_prd  = prev.st_descricao_prd
        AND CAST(prev.dt_fim_mens AS DATE) = LAST_DAY(CAST(prev.dt_fim_mens AS DATE))
        AND DATE_TRUNC(CAST(prev.dt_fim_mens AS DATE), MONTH) = DATE_SUB(e.mes, INTERVAL 1 MONTH)
    )
    SELECT
      e.mes,
      CASE
        WHEN e.st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
        WHEN e.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
        WHEN e.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
        WHEN e.st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
        WHEN e.st_descricao_prd LIKE '%[TOTEM]%'               THEN 'totem'
        ELSE                                                        'upgrade_plano'
      END                                                       AS tipo,
      SUM(e.valor_total)                                        AS expansion_mrr,
      COUNT(DISTINCT e.st_sincro_sac)                           AS clientes
    FROM expansao_raw e
    LEFT JOIN renovacoes_exp r
      ON e.st_sincro_sac = r.st_sincro_sac AND e.st_descricao_prd = r.st_descricao_prd AND e.mes = r.mes
    WHERE r.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]  = pd.to_datetime(df["mes"])
        df["tipo"] = df["tipo"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 5 — CHURN POR PLANO
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_churn_por_plano() -> pd.DataFrame:
    """Desativações de plano base por mês — MRR perdido e clientes (últimos 18 meses)."""
    query = f"""
    WITH desativados AS (
      SELECT
        st_sincro_sac, st_descricao_prd,
        CAST(dt_fim_mens AS DATE)                            AS dt_fim,
        DATE_TRUNC(CAST(dt_fim_mens AS DATE), MONTH)         AS mes,
        valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE dt_fim_mens IS NOT NULL
        AND CAST(dt_fim_mens AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
        AND st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_MODULOS.format(col="st_descricao_prd")}
      UNION ALL
      SELECT
        m.st_sincro_sac, m.st_descricao_prd,
        CAST(c.dt_desativacao_sac AS DATE)                   AS dt_fim,
        DATE_TRUNC(CAST(c.dt_desativacao_sac AS DATE), MONTH) AS mes,
        m.valor_total
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      INNER JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
        ON m.st_sincro_sac = c.st_sincro_sac
      WHERE m.dt_fim_mens IS NULL
        AND c.dt_desativacao_sac IS NOT NULL
        AND CAST(c.dt_desativacao_sac AS DATE) >= DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH)
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND {_EXCL_MODULOS.format(col="m.st_descricao_prd")}
      QUALIFY ROW_NUMBER() OVER (PARTITION BY m.st_sincro_sac, m.st_descricao_prd ORDER BY m.dt_inicio_mens DESC) = 1
    ),
    renovacoes AS (
      SELECT DISTINCT d.st_sincro_sac, d.st_descricao_prd, d.mes
      FROM desativados d
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` r
        ON d.st_sincro_sac = r.st_sincro_sac AND d.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(CAST(r.dt_inicio_mens AS DATE), MONTH) = DATE_ADD(d.mes, INTERVAL 1 MONTH)
      WHERE d.dt_fim = LAST_DAY(d.dt_fim) AND r.dt_inicio_mens IS NOT NULL
    )
    SELECT
      d.mes,
      {_PLAN_CASE.format(col="d.st_descricao_prd")}          AS plano,
      COUNT(DISTINCT d.st_sincro_sac)                         AS churned_clients,
      SUM(d.valor_total)                                      AS churned_mrr
    FROM desativados d
    LEFT JOIN renovacoes rv
      ON d.st_sincro_sac = rv.st_sincro_sac AND d.st_descricao_prd = rv.st_descricao_prd AND d.mes = rv.mes
    WHERE rv.st_sincro_sac IS NULL
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 6 — BASE ATIVA POR PLANO (para churn %)
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_base_ativa_por_plano() -> pd.DataFrame:
    """Clientes ativos por plano no início de cada mês (últimos 18 meses)."""
    query = f"""
    SELECT
      cal.mes,
      {_PLAN_CASE.format(col="mrr.st_descricao_prd")}        AS plano,
      COUNT(DISTINCT mrr.st_sincro_sac)                       AS clientes_ativos,
      SUM(mrr.valor_total)                                    AS mrr_ativo
    FROM (
      SELECT mes FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ) cal
    CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
    WHERE CAST(mrr.dt_inicio_mens AS DATE) < cal.mes
      AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) >= cal.mes)
      AND mrr.st_descricao_prd NOT LIKE '%Setup%'
      AND mrr.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      AND {_EXCL_MODULOS.format(col="mrr.st_descricao_prd")}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]   = pd.to_datetime(df["mes"])
        df["plano"] = df["plano"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 7 — ATTACH RATE DE MÓDULOS
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_module_attach_rate() -> pd.DataFrame:
    """
    Para cada mês: % da base de clientes ativos que tem cada módulo ativo.
    Base = clientes com plano base ativo no início do mês.
    """
    query = """
    WITH
    meses AS (
      SELECT mes FROM UNNEST(GENERATE_DATE_ARRAY(
        DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 17 MONTH),
        DATE_TRUNC(CURRENT_DATE(), MONTH),
        INTERVAL 1 MONTH
      )) AS mes
    ),
    base_ativa AS (
      SELECT cal.mes, COUNT(DISTINCT mrr.st_sincro_sac) AS total_clientes
      FROM meses cal
      CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
      WHERE CAST(mrr.dt_inicio_mens AS DATE) < cal.mes
        AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) >= cal.mes)
        AND mrr.st_descricao_prd NOT LIKE '%Setup%'
        AND mrr.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
        AND mrr.st_descricao_prd NOT LIKE '%[KIDS]%'
        AND mrr.st_descricao_prd NOT LIKE '%[JORNADA]%'
        AND mrr.st_descricao_prd NOT LIKE '%[LOJAINTELIGENTE]%'
        AND mrr.st_descricao_prd NOT LIKE '%[TOTEM]%'
        AND NOT (mrr.st_descricao_prd LIKE '%[STARTER]%' AND mrr.st_descricao_prd LIKE '%Módulo%')
      GROUP BY 1
    ),
    modulos_ativos AS (
      SELECT
        cal.mes,
        CASE
          WHEN mrr.st_descricao_prd LIKE '%[KIDS]%'                THEN 'kids'
          WHEN mrr.st_descricao_prd LIKE '%[JORNADA]%'             THEN 'jornada'
          WHEN mrr.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'     THEN 'loja_inteligente'
          WHEN mrr.st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%' THEN 'loja_inteligente'
          WHEN mrr.st_descricao_prd LIKE '%[TOTEM]%'               THEN 'totem'
        END AS modulo,
        COUNT(DISTINCT mrr.st_sincro_sac) AS clientes_com_modulo
      FROM meses cal
      CROSS JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` mrr
      WHERE CAST(mrr.dt_inicio_mens AS DATE) < cal.mes
        AND (mrr.dt_fim_mens IS NULL OR CAST(mrr.dt_fim_mens AS DATE) >= cal.mes)
        AND (
          mrr.st_descricao_prd LIKE '%[KIDS]%'
          OR mrr.st_descricao_prd LIKE '%[JORNADA]%'
          OR mrr.st_descricao_prd LIKE '%[LOJAINTELIGENTE]%'
          OR mrr.st_descricao_prd LIKE '%[LOJAINTELIGENTE_INC]%'
          OR mrr.st_descricao_prd LIKE '%[TOTEM]%'
        )
      GROUP BY 1, 2
    )
    SELECT
      ma.mes,
      ma.modulo,
      ma.clientes_com_modulo,
      ba.total_clientes,
      ROUND(ma.clientes_com_modulo / ba.total_clientes * 100, 1) AS attach_rate
    FROM modulos_ativos ma
    JOIN base_ativa ba ON ma.mes = ba.mes
    WHERE ma.modulo IS NOT NULL
    ORDER BY 1, 2
    """
    df = _query_bi(query)
    if not df.empty:
        df["mes"]    = pd.to_datetime(df["mes"])
        df["modulo"] = df["modulo"].str.lower()
    return df


# ─────────────────────────────────────────────
# QUERY 8 — TEMPO ATÉ PRIMEIRO UPSELL
# ─────────────────────────────────────────────
@st.cache_data(ttl=3600)
def load_upsell_timing() -> pd.DataFrame:
    """
    Dias entre o primeiro produto ativado e o primeiro upsell por cliente.
    Retorna distribuição por faixa de dias.
    """
    query = """
    WITH
    primeiro_inicio AS (
      SELECT st_sincro_sac, MIN(CAST(dt_inicio_mens AS DATE)) AS dt_first
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos`
      WHERE st_descricao_prd NOT LIKE '%Setup%'
        AND st_descricao_prd NOT LIKE '%[PRO-RATA]%'
      GROUP BY 1
    ),
    expansao_raw AS (
      SELECT
        m.st_sincro_sac,
        m.st_descricao_prd,
        CAST(m.dt_inicio_mens AS DATE) AS dt_inicio,
        p.dt_first
      FROM `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` m
      JOIN primeiro_inicio p ON m.st_sincro_sac = p.st_sincro_sac
      WHERE CAST(m.dt_inicio_mens AS DATE) > p.dt_first
        AND m.st_descricao_prd NOT LIKE '%Setup%'
        AND m.st_descricao_prd NOT LIKE '%[PRO-RATA]%'
    ),
    renovacoes_exp AS (
      SELECT DISTINCT e.st_sincro_sac, e.st_descricao_prd, DATE_TRUNC(e.dt_inicio, MONTH) AS mes
      FROM expansao_raw e
      INNER JOIN `business-intelligence-467516.Splgc.vw-splgc-tabela_mrr_validos` prev
        ON e.st_sincro_sac = prev.st_sincro_sac AND e.st_descricao_prd = prev.st_descricao_prd
        AND CAST(prev.dt_fim_mens AS DATE) = LAST_DAY(CAST(prev.dt_fim_mens AS DATE))
        AND DATE_TRUNC(CAST(prev.dt_fim_mens AS DATE), MONTH) = DATE_SUB(DATE_TRUNC(e.dt_inicio, MONTH), INTERVAL 1 MONTH)
    ),
    primeiro_upsell AS (
      SELECT
        e.st_sincro_sac,
        MIN(e.dt_inicio) AS dt_primeiro_upsell,
        e.dt_first
      FROM expansao_raw e
      LEFT JOIN renovacoes_exp r
        ON e.st_sincro_sac = r.st_sincro_sac AND e.st_descricao_prd = r.st_descricao_prd
        AND DATE_TRUNC(e.dt_inicio, MONTH) = r.mes
      WHERE r.st_sincro_sac IS NULL
      GROUP BY e.st_sincro_sac, e.dt_first
    )
    SELECT
      DATE_DIFF(dt_primeiro_upsell, dt_first, DAY) AS dias_ate_upsell,
      COUNT(*) AS clientes
    FROM primeiro_upsell
    GROUP BY 1
    ORDER BY 1
    """
    df = _query_bi(query)
    if not df.empty:
        df["dias_ate_upsell"] = df["dias_ate_upsell"].astype(int)
    return df


# ─────────────────────────────────────────────
# GOOGLE DRIVE — Despesas para CAC
# ─────────────────────────────────────────────
@st.cache_data(ttl=21600)
def load_despesas_cac() -> pd.DataFrame:
    """
    Lê as despesas liquidadas do Google Drive e filtra pelos centros de custo
    que compõem o CAC: Comercial, Marketing, Eventos, Parceiros, Outbound.
    Retorna DataFrame vazio se [gcp_service_account] não estiver nos secrets.
    Retorna total por mês e por grupo de custo.
    """
    try:
        st.secrets["gcp_service_account"]
    except (KeyError, Exception):
        return pd.DataFrame(columns=["mes", "grupo", "valor"])

    def _parse_br_float(s: str) -> float:
        s = str(s).strip().strip('"').replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return 0.0

    def _iter_rows(content: str):
        reader = _csv.reader(io.StringIO(content))
        rows = [r for r in reader if any(c.strip() for c in r)]
        if not rows:
            return
        is_sheet_format = len(rows[0]) == 1 and "," in rows[0][0]
        for row in rows:
            if not row:
                continue
            if is_sheet_format:
                yield next(_csv.reader([row[0]]))
            else:
                yield row

    # Localiza arquivo de despesas no Drive (Sheet ou CSV)
    sheet_id = _find_in_folder(r"despesas_liquidadas.*", mime=_SHEET_MIME)
    if sheet_id:
        content = _download_sheet_csv(sheet_id)
    else:
        csv_id = _find_in_folder(r"190B.*\.csv")
        if not csv_id:
            return pd.DataFrame(columns=["mes", "grupo", "valor"])
        content = _download_file(csv_id).decode("latin1")

    # DE-PARA de centro de custo → grupo CAC
    cac_map = {
        "Field Sales":    "comercial",
        "Inbound":        "comercial",
        "Sales":          "comercial",
        "Outside Sales":  "comercial",
        "Marketing":      "marketing",
        "Eventos":        "eventos_parceiros",
        "Parceiros":      "eventos_parceiros",
        "Outbound":       "outbound",
    }

    records = []
    row_iter = _iter_rows(content)
    next(row_iter)  # skip header
    for row in row_iter:
        if len(row) < 13:
            continue
        # Detecta deslocamento por vírgula no nome do fornecedor
        shift = 0
        for _s in range(5):
            _val = row[8 + _s].strip() if (8 + _s) < len(row) else ""
            if re.match(r'^\d+\.\d+\.\d+$', _val):
                shift = _s
                break
        liquidacao_str = row[6 + shift].strip()
        valor_pago = _parse_br_float(row[12 + shift])
        try:
            liquidacao = pd.to_datetime(liquidacao_str, format="%d/%m/%Y", errors="coerce")
        except Exception:
            liquidacao = pd.NaT
        if pd.isna(liquidacao):
            continue
        idx = 13 + shift
        while idx + 1 < len(row):
            centro = row[idx].strip().strip('"')
            pct_str = row[idx + 1] if idx + 1 < len(row) else "0"
            try:
                pct = _parse_br_float(pct_str)
                valor_alocado = valor_pago * (pct / 100.0)
            except Exception:
                idx += 3
                continue
            if centro in cac_map and valor_alocado < 0:
                records.append({
                    "liquidacao": liquidacao,
                    "centro_custo": centro,
                    "grupo": cac_map[centro],
                    "valor": abs(valor_alocado),
                })
            idx += 3

    if not records:
        return pd.DataFrame(columns=["mes", "grupo", "valor"])

    df = pd.DataFrame(records)
    df["mes"] = df["liquidacao"].dt.to_period("M").dt.to_timestamp()
    df = df.groupby(["mes", "grupo"], as_index=False)["valor"].sum()
    df["mes"] = pd.to_datetime(df["mes"])
    return df


# ─────────────────────────────────────────────
# HELPER — CAC + PAYBACK + LTV:CAC
# ─────────────────────────────────────────────
def compute_cac_metrics(
    df_despesas: pd.DataFrame,
    df_waterfall: pd.DataFrame,
) -> pd.DataFrame:
    """
    Junta despesas CAC com novos clientes do waterfall.
    Retorna por mês: total_cac, new_clients, cac, arpu (base), payback_meses, ltv_cac.
    LTV estimado = ARPU / churn_rate_mensal (usando média dos últimos 3 meses para suavizar).
    """
    if df_despesas.empty or df_waterfall.empty:
        return pd.DataFrame()

    # Total CAC por mês
    cac_total = df_despesas.groupby("mes", as_index=False)["valor"].sum()
    cac_total.rename(columns={"valor": "total_cac"}, inplace=True)

    # Novos clientes e ARPU do waterfall
    wf = df_waterfall[["mes", "new_clients", "new_logo_mrr", "mrr_inicio",
                        "clientes_inicio", "churned_mrr"]].copy()
    wf["arpu"] = (wf["mrr_inicio"] / wf["clientes_inicio"].replace(0, pd.NA)).round(2)
    wf["churn_rate"] = (wf["churned_mrr"] / wf["mrr_inicio"].replace(0, pd.NA)).clip(upper=1)

    merged = cac_total.merge(wf, on="mes", how="inner")
    merged["cac"] = (merged["total_cac"] / merged["new_clients"].replace(0, pd.NA)).round(2)

    # LTV suavizado com média móvel de 3 meses
    merged = merged.sort_values("mes")
    merged["churn_rate_smooth"] = merged["churn_rate"].rolling(3, min_periods=1).mean()
    merged["ltv"] = (merged["arpu"] / merged["churn_rate_smooth"].replace(0, pd.NA)).round(0)
    merged["payback_meses"] = (merged["cac"] / merged["arpu"].replace(0, pd.NA)).round(1)
    merged["ltv_cac"] = (merged["ltv"] / merged["cac"].replace(0, pd.NA)).round(2)

    return merged
