"""
utils/data.py
Helpers de dados e queries BigQuery para o dashboard Carteira Fabiano.
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
import googleapiclient.discovery

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

COMISSAO_CARTEIRA_PCT = 0.05  # 5% sobre mensalidades liquidadas da carteira

SPREADSHEET_ID = "1RVkFz3-uROcKYoHTNlyWIHfzjSG3_jbx46fTCZT7c-Q"
SHEET_RANGE    = "Página1!A:F"  # colunas: Data Ass, Data 1°Pag, Company Name, Company ID, SDR, SR Owner

# ─────────────────────────────────────────────
# LAYOUT DE GRÁFICOS
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
        hoverlabel=dict(bgcolor="#141414", bordercolor="#292929", font_size=13, font_family="Outfit, sans-serif", font_color="#ffffff"),
    )
    return fig


def mes_fmt_ordered(df: pd.DataFrame, date_col: str = "mes") -> tuple[pd.DataFrame, list[str]]:
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)
    df["mes_fmt"] = df[date_col].dt.strftime("%b/%y").str.capitalize()
    ordered = df["mes_fmt"].drop_duplicates().tolist()
    return df, ordered


def filter_months(df: pd.DataFrame, n_months: int, date_col: str = "mes") -> pd.DataFrame:
    if df.empty or n_months == 0:
        return df
    cutoff = date.today() - relativedelta(months=n_months)
    col = df[date_col]
    if not pd.api.types.is_datetime64_any_dtype(col):
        col = pd.to_datetime(col, errors="coerce")
    return df[col >= pd.Timestamp(cutoff)].copy()


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
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def no_data(label: str = "Dados não disponíveis") -> None:
    st.info(label, icon="ℹ️")


# ─────────────────────────────────────────────
# CLIENTES DO SERVICE ACCOUNT — GOOGLE SHEETS + BQ
# ─────────────────────────────────────────────
def _get_bi_credentials(extra_scopes: list[str] | None = None) -> service_account.Credentials:
    cfg = st.secrets["connections"]["bigquery_bi"]
    creds_raw = cfg["credentials"]
    creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
    scopes = ["https://www.googleapis.com/auth/bigquery"]
    if extra_scopes:
        scopes += extra_scopes
    return service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)


@st.cache_resource
def _bq_client_bi() -> bigquery.Client:
    creds = _get_bi_credentials()
    cfg = st.secrets["connections"]["bigquery_bi"]
    return bigquery.Client(project=cfg["project"], credentials=creds)


def _bq_query(query: str) -> pd.DataFrame:
    try:
        return _bq_client_bi().query(query).to_dataframe()
    except Exception as e:
        st.error(f"Erro ao consultar BigQuery: {e}")
        return pd.DataFrame()


def _valid_company_id(cid: str) -> bool:
    """tertiarygroup_id é numérico e curto (≤ 8 dígitos)."""
    return cid.isdigit() and 1 <= len(cid) <= 8


@st.cache_data(ttl=3600)
def load_fabiano_ids() -> list[str]:
    """
    Retorna lista de Company IDs dos clientes vendidos por Fabiano Lomar.
    Combina planilha (histórico) + Fechamentos_com_ajustes (recentes).
    """
    return list(load_fabiano_sheet_data().keys())


@st.cache_data(ttl=3600)
def load_fabiano_sheet_data() -> dict[str, dict]:
    """
    Regra de fonte de dados:
    - Planilha (Reg Assinat): fonte canônica para todos os fechamentos até abril/2026.
    - BQ Fechamentos_com_ajustes: complementa com novos fechamentos a partir de maio/2026.

    Retorna {company_id: {name, entry_date}}.
    """
    data: dict[str, dict] = {}

    # 1. Planilha — fonte de todos os fechamentos até abril/2026
    try:
        creds = _get_bi_credentials(["https://www.googleapis.com/auth/spreadsheets.readonly"])
        svc = googleapiclient.discovery.build("sheets", "v4", credentials=creds, cache_discovery=False)
        result = svc.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=SHEET_RANGE
        ).execute()
        rows = result.get("values", [])
        for row in rows[1:]:
            if len(row) >= 6:
                company_id   = str(row[3]).strip()
                sr_owner     = str(row[5]).strip().lower()
                company_name = str(row[2]).strip() if len(row) > 2 else ""
                entry_date   = str(row[1]).strip() if len(row) > 1 else ""
                if "fabiano lomar" in sr_owner and _valid_company_id(company_id):
                    if company_id not in data:
                        data[company_id] = {"name": company_name, "entry": entry_date}
    except Exception as e:
        st.warning(f"Planilha indisponível: {e}. Usando somente dados do BigQuery.")

    # 2. BQ — complementa com todos os fechamentos não presentes na planilha
    #    (a planilha pode estar desatualizada; BQ é fonte para qualquer data ausente)
    q = """
    SELECT DISTINCT
      TRIM(tertiarygroup_id)      AS id,
      company_name,
      CAST(first_payment AS DATE) AS first_payment
    FROM `business-intelligence-467516.Fechamento_vendas.Fechamentos_com_ajustes`
    WHERE (LOWER(TRIM(sales_owner)) = 'fabiano lomar'
        OR TRIM(sales_owner) = 'fabiano.lomar@inchurch.com.br')
      AND tertiarygroup_id IS NOT NULL
      AND TRIM(tertiarygroup_id) != ''
    """
    df_bq = _bq_query(q)
    if not df_bq.empty:
        for _, row in df_bq.iterrows():
            cid = str(row["id"]).strip()
            if _valid_company_id(cid) and cid not in data:
                data[cid] = {
                    "name": row.get("company_name", ""),
                    "entry": str(row["first_payment"]) if pd.notna(row["first_payment"]) else "",
                }

    return data


def _ids_to_sql_list(ids: list[str]) -> str:
    """Formata lista de IDs como literal SQL: ('27550','27575',...)"""
    quoted = ",".join(f"'{i}'" for i in ids)
    return f"({quoted})"


# ─────────────────────────────────────────────
# QUERIES — CARTEIRA FABIANO
# ─────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_carteira_mensal() -> pd.DataFrame:
    """
    Receita 1.2.2 mês a mês dos clientes vendidos por Fabiano Lomar.
    Retorna: mes, clientes, receita_emitida, receita_liquidada, comissao_5pct, pct_pago.
    UNION ALL hist + all para histórico completo com deduplicação.
    """
    ids = load_fabiano_ids()
    if not ids:
        return pd.DataFrame()

    id_list = _ids_to_sql_list(ids)

    query = f"""
    WITH ids_in_all AS (
      SELECT DISTINCT id_recebimento_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    boletos AS (
      SELECT h.id_recebimento_recb, h.st_sincro_sac, h.dt_vencimento_recb,
             h.comp_valor, h.fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-hist` h
      LEFT JOIN ids_in_all ia ON h.id_recebimento_recb = ia.id_recebimento_recb
      WHERE h.st_sincro_sac IN {id_list}
        AND h.comp_st_conta_cont = '1.2.2'
        AND ia.id_recebimento_recb IS NULL
      UNION ALL
      SELECT id_recebimento_recb, st_sincro_sac, dt_vencimento_recb,
             comp_valor, fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    client_entry AS (
      -- mês de entrada de cada cliente = primeiro boleto 1.2.2 na carteira
      SELECT st_sincro_sac,
             DATE_TRUNC(MIN(CAST(dt_vencimento_recb AS DATE)), MONTH) AS entry_month
      FROM boletos
      GROUP BY 1
    )
    SELECT
      DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH)              AS mes,
      COUNT(DISTINCT b.st_sincro_sac)                                     AS clientes,
      SUM(b.comp_valor)                                                   AS receita_emitida,
      SUM(CASE WHEN b.fl_status_recb = '1' THEN b.comp_valor ELSE 0 END) AS receita_liquidada,
      -- elegível para comissão: após o mês de entrada e dentro dos primeiros 12 meses
      SUM(CASE
        WHEN DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) > e.entry_month
          AND DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) <= DATE_ADD(e.entry_month, INTERVAL 12 MONTH)
        THEN b.comp_valor ELSE 0
      END)                                                                AS receita_emit_comissao,
      SUM(CASE
        WHEN b.fl_status_recb = '1'
          AND DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) > e.entry_month
          AND DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) <= DATE_ADD(e.entry_month, INTERVAL 12 MONTH)
        THEN b.comp_valor ELSE 0
      END)                                                                AS receita_liq_comissao
    FROM boletos b
    JOIN client_entry e ON b.st_sincro_sac = e.st_sincro_sac
    GROUP BY 1
    ORDER BY 1
    """
    df = _bq_query(query)
    if not df.empty:
        df["mes"] = pd.to_datetime(df["mes"])
        df["comissao_5pct"] = (df["receita_liq_comissao"] * COMISSAO_CARTEIRA_PCT).round(2)
        df["pct_pago"] = (
            df["receita_liquidada"] / df["receita_emitida"].where(df["receita_emitida"] > 0) * 100
        ).round(1)
        df["pct_pago_comissao"] = (
            df["receita_liq_comissao"] / df["receita_emit_comissao"].where(df["receita_emit_comissao"] > 0) * 100
        ).round(1)
    return df


@st.cache_data(ttl=3600)
def load_carteira_clientes() -> pd.DataFrame:
    """
    Detalhamento por cliente: nome, data de entrada, meses faturados, receita total.
    Data de entrada = primeiro boleto 1.2.2. Nome = Superlógica ou planilha.
    """
    ids = load_fabiano_ids()
    if not ids:
        return pd.DataFrame()

    sheet_meta = load_fabiano_sheet_data()
    id_list = _ids_to_sql_list(ids)

    query = f"""
    WITH ids_in_all AS (
      SELECT DISTINCT id_recebimento_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    boletos AS (
      SELECT h.id_recebimento_recb, h.st_sincro_sac, h.dt_vencimento_recb,
             h.comp_valor, h.fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-hist` h
      LEFT JOIN ids_in_all ia ON h.id_recebimento_recb = ia.id_recebimento_recb
      WHERE h.st_sincro_sac IN {id_list}
        AND h.comp_st_conta_cont = '1.2.2'
        AND ia.id_recebimento_recb IS NULL
      UNION ALL
      SELECT id_recebimento_recb, st_sincro_sac, dt_vencimento_recb,
             comp_valor, fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    client_entry AS (
      SELECT st_sincro_sac,
             DATE_TRUNC(MIN(CAST(dt_vencimento_recb AS DATE)), MONTH) AS entry_month
      FROM boletos
      GROUP BY 1
    )
    SELECT
      a.st_sincro_sac,
      c.st_nome_sac                                                                AS nome_splgc,
      MIN(DATE_TRUNC(CAST(a.dt_vencimento_recb AS DATE), MONTH))                   AS primeiro_boleto,
      COUNT(DISTINCT DATE_TRUNC(CAST(a.dt_vencimento_recb AS DATE), MONTH))        AS meses_faturados,
      SUM(a.comp_valor)                                                             AS receita_emitida,
      SUM(CASE WHEN a.fl_status_recb = '1' THEN a.comp_valor ELSE 0 END)           AS receita_liquidada,
      SUM(CASE
        WHEN a.fl_status_recb = '1'
          AND DATE_TRUNC(CAST(a.dt_vencimento_recb AS DATE), MONTH) > e.entry_month
          AND DATE_TRUNC(CAST(a.dt_vencimento_recb AS DATE), MONTH) <= DATE_ADD(e.entry_month, INTERVAL 12 MONTH)
        THEN a.comp_valor ELSE 0
      END)                                                                           AS receita_liq_comissao
    FROM boletos a
    JOIN client_entry e ON a.st_sincro_sac = e.st_sincro_sac
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON a.st_sincro_sac = c.st_sincro_sac
    GROUP BY 1, 2
    """
    df = _bq_query(query)
    if df.empty:
        return pd.DataFrame()

    # Complementa nome e data de entrada com dados da planilha
    df["st_sincro_sac"] = df["st_sincro_sac"].astype(str)
    df["nome_planilha"] = df["st_sincro_sac"].map(lambda x: sheet_meta.get(x, {}).get("name", ""))
    df["cliente"] = df["nome_splgc"].fillna("").replace("", None)
    df["cliente"] = df["cliente"].fillna(df["nome_planilha"].replace("", None))
    df["cliente"] = df["cliente"].fillna(df["st_sincro_sac"])

    df["primeiro_boleto"] = pd.to_datetime(df["primeiro_boleto"], errors="coerce")
    df["comissao_5pct"] = (df["receita_liq_comissao"] * COMISSAO_CARTEIRA_PCT).round(2)
    df["pct_pago"] = (
        df["receita_liquidada"] / df["receita_emitida"].where(df["receita_emitida"] > 0) * 100
    ).round(1)

    return df.sort_values("receita_liquidada", ascending=False)


@st.cache_data(ttl=3600)
def load_carteira_detalhe_mensal() -> pd.DataFrame:
    """
    Receita 1.2.2 por cliente por mês, com flag de elegibilidade para comissão de carteira.
    Retorna: id, cliente, entry_month, mes, emitida, liquidada, liq_comissao, comissao_5pct, pct_pago, elegivel.
    """
    ids = load_fabiano_ids()
    if not ids:
        return pd.DataFrame()

    sheet_meta = load_fabiano_sheet_data()
    id_list = _ids_to_sql_list(ids)

    query = f"""
    WITH ids_in_all AS (
      SELECT DISTINCT id_recebimento_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    boletos AS (
      SELECT h.id_recebimento_recb, h.st_sincro_sac, h.dt_vencimento_recb,
             h.comp_valor, h.fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-hist` h
      LEFT JOIN ids_in_all ia ON h.id_recebimento_recb = ia.id_recebimento_recb
      WHERE h.st_sincro_sac IN {id_list}
        AND h.comp_st_conta_cont = '1.2.2'
        AND ia.id_recebimento_recb IS NULL
      UNION ALL
      SELECT id_recebimento_recb, st_sincro_sac, dt_vencimento_recb,
             comp_valor, fl_status_recb
      FROM `business-intelligence-467516.Splgc.splgc-cobrancas_competencia-all`
      WHERE st_sincro_sac IN {id_list}
        AND comp_st_conta_cont = '1.2.2'
    ),
    client_entry AS (
      SELECT st_sincro_sac,
             DATE_TRUNC(MIN(CAST(dt_vencimento_recb AS DATE)), MONTH) AS entry_month
      FROM boletos
      GROUP BY 1
    )
    SELECT
      b.st_sincro_sac                                                              AS id,
      c.st_nome_sac                                                                AS nome_splgc,
      DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH)                       AS mes,
      e.entry_month,
      SUM(b.comp_valor)                                                            AS emitida,
      SUM(CASE WHEN b.fl_status_recb = '1' THEN b.comp_valor ELSE 0 END)         AS liquidada,
      SUM(CASE
        WHEN b.fl_status_recb = '1'
          AND DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) > e.entry_month
          AND DATE_TRUNC(CAST(b.dt_vencimento_recb AS DATE), MONTH) <= DATE_ADD(e.entry_month, INTERVAL 12 MONTH)
        THEN b.comp_valor ELSE 0
      END)                                                                         AS liq_comissao
    FROM boletos b
    JOIN client_entry e ON b.st_sincro_sac = e.st_sincro_sac
    LEFT JOIN `business-intelligence-467516.Splgc.splgc-clientes-inchurch` c
      ON b.st_sincro_sac = c.st_sincro_sac
    GROUP BY 1, 2, 3, 4
    ORDER BY 3 DESC, 5 DESC
    """
    df = _bq_query(query)
    if df.empty:
        return pd.DataFrame()

    df["mes"]         = pd.to_datetime(df["mes"])
    df["entry_month"] = pd.to_datetime(df["entry_month"])
    df["id"]          = df["id"].astype(str)
    df["nome_planilha"] = df["id"].map(lambda x: sheet_meta.get(x, {}).get("name", ""))
    df["cliente"] = df["nome_splgc"].fillna("").replace("", None)
    df["cliente"] = df["cliente"].fillna(df["nome_planilha"].replace("", None))
    df["cliente"] = df["cliente"].fillna(df["id"])
    df["comissao_5pct"] = (df["liq_comissao"] * COMISSAO_CARTEIRA_PCT).round(2)
    df["pct_pago"]  = (df["liquidada"] / df["emitida"].where(df["emitida"] > 0) * 100).round(1)
    # elegível = está dentro da janela de 12 meses (independente de ter pago ou não)
    df["elegivel"]  = (
        (df["mes"] > df["entry_month"]) &
        (df["mes"] <= df["entry_month"] + pd.DateOffset(months=12))
    )
    return df
