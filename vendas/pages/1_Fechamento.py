"""
pages/1_Fechamento.py
Dashboard de Fechamento de Vendas com filtros e tabela detalhada.
"""
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Fechamento de Vendas | InChurch",
    page_icon="📋",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "fechamento"

from utils.style import inject_css
from utils.data import load_fechamentos, load_ids_com_problema, fmt_brl

inject_css()

# ── Header ─────────────────────────────────────
st.markdown("<h1>Fechamento <span>de Vendas</span></h1>", unsafe_allow_html=True)

# ── Carga de dados ─────────────────────────────
with st.spinner("Carregando dados..."):
    df = load_fechamentos()
    ids_com_problema = load_ids_com_problema()

if df.empty:
    st.info("Nenhum dado encontrado na base.", icon="ℹ️")
    st.stop()

# ── Sidebar — Filtros ──────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filtros")

    # Mês de fechamento — lista ordenada cronologicamente
    meses_ord = (
        df[["_mes_fmt", "_mes_ord"]]
        .drop_duplicates()
        .sort_values("_mes_ord")["_mes_fmt"]
        .tolist()
    )
    sel_meses = st.multiselect("Mês de Fechamento", meses_ord, placeholder="Todos")

    # Vendedor
    vendedores = sorted(df["sales_owner"].dropna().unique())
    sel_vendedores = st.multiselect("Vendedor", vendedores, placeholder="Todos")

    # Pré-Vendedor
    pre_vendedores = sorted(df["sdr_owner"].dropna().unique())
    sel_pre = st.multiselect("Pré-Vendedor", pre_vendedores, placeholder="Todos")

    # Canal
    canais = sorted(df["channel"].dropna().unique())
    sel_canais = st.multiselect("Canal", canais, placeholder="Todos")

    # Produto / Plano
    planos = sorted(df["plan"].dropna().unique())
    sel_planos = st.multiselect("Produto / Plano", planos, placeholder="Todos")

    # Conferência
    sel_conf = st.selectbox(
        "Conferência",
        options=["Todos", "Conferência OK", "Com pendências"],
        index=0,
    )

    st.divider()
    user_name  = getattr(st.user, "name", st.user.email)
    user_email = st.user.email
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    if st.button("🚪 Sair", use_container_width=True):
        st.logout()

# ── Aplicar filtros ────────────────────────────
dfv = df.copy()
if sel_meses:
    dfv = dfv[dfv["_mes_fmt"].isin(sel_meses)]
if sel_vendedores:
    dfv = dfv[dfv["sales_owner"].isin(sel_vendedores)]
if sel_pre:
    dfv = dfv[dfv["sdr_owner"].isin(sel_pre)]
if sel_canais:
    dfv = dfv[dfv["channel"].isin(sel_canais)]
if sel_planos:
    dfv = dfv[dfv["plan"].isin(sel_planos)]
if sel_conf == "Conferência OK":
    dfv = dfv[~dfv["tertiarygroup_id"].isin(ids_com_problema)]
elif sel_conf == "Com pendências":
    dfv = dfv[dfv["tertiarygroup_id"].isin(ids_com_problema)]

# ── KPI Cards ─────────────────────────────────
n_vendas    = len(dfv)
mrr_total   = dfv["value"].sum()
fyv_total   = dfv["FYV"].sum()
setup_total = dfv["setup"].fillna(0).sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total de Vendas",  f"{n_vendas:,}".replace(",", "."))
c2.metric("MRR Fechado",      f"R$ {fmt_brl(mrr_total, 0)}")
c3.metric("FYV Total",        f"R$ {fmt_brl(fyv_total, 0)}")
c4.metric("Setup Total",      f"R$ {fmt_brl(setup_total, 0)}")

st.divider()

# ── Tabela ─────────────────────────────────────
st.markdown("### 📋 Detalhamento")

# Colunas de validação (presença do ID no sistema externo)
dfv = dfv.copy()
dfv["_hs_ok"]  = dfv["hubspot_deal"].notna() & (dfv["hubspot_deal"].astype(str).str.strip().isin(["", "None", "nan"]) == False)
dfv["_spl_ok"] = dfv["superlogica_id"].notna() & (dfv["superlogica_id"].astype(str).str.strip().isin(["", "None", "nan"]) == False)

display_cols = {
    "first_payment":   "1º Pagamento",
    "company_name":    "Igreja",
    "tertiarygroup_id": "Cód. InChurch",
    "superlogica_id":  "Cód. Superl.",
    "plan":            "Plano",
    "sales_owner":     "Vendedor",
    "sdr_owner":       "Pré-Vendedor",
    "channel":         "Canal",
    "value":           "Mensalidade (R$)",
    "setup":           "Setup (R$)",
    "FYV":             "FYV (R$)",
    "_hs_ok":          "HubSpot ✓",
    "_spl_ok":         "Superlógica ✓",
    "observacao":      "Observação",
}

dfv_display = dfv[list(display_cols.keys())].rename(columns=display_cols)

st.dataframe(
    dfv_display,
    use_container_width=True,
    height=620,
    column_config={
        "1º Pagamento": st.column_config.DateColumn(
            "1º Pagamento",
            format="DD/MM/YYYY",
        ),
        "Mensalidade (R$)": st.column_config.NumberColumn(
            "Mensalidade (R$)",
            format="R$ %,.2f",
        ),
        "Setup (R$)": st.column_config.NumberColumn(
            "Setup (R$)",
            format="R$ %,.2f",
        ),
        "FYV (R$)": st.column_config.NumberColumn(
            "FYV (R$)",
            format="R$ %,.2f",
            help="12 × Mensalidade + Setup",
        ),
        "HubSpot ✓": st.column_config.CheckboxColumn(
            "HubSpot ✓",
            help="Deal vinculado ao HubSpot",
        ),
        "Superlógica ✓": st.column_config.CheckboxColumn(
            "Superlógica ✓",
            help="Cliente vinculado ao Superlógica",
        ),
        "Cód. InChurch": st.column_config.TextColumn("Cód. InChurch"),
        "Cód. Superl.":  st.column_config.TextColumn("Cód. Superl."),
    },
    hide_index=True,
)

# ── Exportar CSV ───────────────────────────────
csv = dfv_display.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
st.download_button(
    label="⬇️ Exportar CSV",
    data=csv,
    file_name="fechamento_vendas.csv",
    mime="text/csv",
)
