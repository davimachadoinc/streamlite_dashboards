"""
pages/2_⚠️_Conferencias.py
Painel de conferências — problemas de validação por fechamento.
"""
import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Conferências | InChurch",
    page_icon="⚠️",
    layout="wide",
)

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "conferencias"

from utils.style import inject_css
from utils.data import load_fechamentos, load_conferencias_detalhado

inject_css()

# ── Header ──────────────────────────────────────
st.markdown("<h1>Conferências <span>& Pendências</span></h1>", unsafe_allow_html=True)

# ── Carga de dados ───────────────────────────────
with st.spinner("Carregando validações..."):
    df_issues = load_conferencias_detalhado()
    df_fech   = load_fechamentos()

# ── Sidebar ─────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Filtros")

    if not df_issues.empty:
        tipos = sorted(df_issues["tipo"].dropna().unique())
        sel_tipos = st.multiselect("Tipo de Conferência", tipos, placeholder="Todos")
    else:
        sel_tipos = []

    vendedores = sorted(df_fech["sales_owner"].dropna().unique()) if not df_fech.empty else []
    sel_vendedores = st.multiselect("Vendedor", vendedores, placeholder="Todos")

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

# ── Sem dados ────────────────────────────────────
if df_issues.empty:
    st.success("✅ Nenhuma pendência de conferência encontrada.", icon="✅")
    st.stop()

# ── Enriquecer issues com contexto de fechamento ─
ctx_cols = ["tertiarygroup_id", "company_name", "sales_owner", "sdr_owner",
            "first_payment", "plan", "channel"]
df_ctx = (
    df_fech[ctx_cols]
    .sort_values("first_payment", ascending=False)
    .drop_duplicates("tertiarygroup_id")
    if not df_fech.empty else pd.DataFrame(columns=ctx_cols)
)
df = df_issues.merge(df_ctx, on="tertiarygroup_id", how="left")
df["first_payment"] = pd.to_datetime(df["first_payment"], errors="coerce")

# ── Aplicar filtros ───────────────────────────────
if sel_tipos:
    df = df[df["tipo"].isin(sel_tipos)]
if sel_vendedores:
    df = df[df["sales_owner"].isin(sel_vendedores)]

# ── KPIs ─────────────────────────────────────────
n_issues    = len(df)
n_igrejas   = df["tertiarygroup_id"].nunique()
n_tipos     = df["tipo"].nunique()

k1, k2, k3 = st.columns(3)
k1.metric("Total de Pendências", f"{n_issues:,}".replace(",", "."))
k2.metric("Igrejas Afetadas",    f"{n_igrejas:,}".replace(",", "."))
k3.metric("Tipos de Problema",   f"{n_tipos:,}".replace(",", "."))

st.divider()

# ── Resumo por tipo ───────────────────────────────
st.markdown("### 📊 Pendências por Tipo")
df_tipo = (
    df.groupby("tipo")
    .agg(
        Pendências=("tertiarygroup_id", "count"),
        Igrejas=("tertiarygroup_id", "nunique"),
    )
    .reset_index()
    .sort_values("Pendências", ascending=False)
    .rename(columns={"tipo": "Tipo"})
)
st.dataframe(df_tipo, use_container_width=True, hide_index=True, height=min(300, 60 + 35 * len(df_tipo)))

st.divider()

# ── Tabela detalhada ──────────────────────────────
st.markdown("### 📋 Detalhamento")

display_cols = {
    "tipo":             "Tipo",
    "detalhe":          "Detalhe",
    "company_name":     "Igreja",
    "tertiarygroup_id": "Cód. InChurch",
    "sales_owner":      "Vendedor",
    "sdr_owner":        "Pré-Vendedor",
    "first_payment":    "1º Pagamento",
    "plan":             "Plano",
    "channel":          "Canal",
}

# Only include columns that exist
existing = {k: v for k, v in display_cols.items() if k in df.columns}
df_display = df[list(existing.keys())].rename(columns=existing)

st.dataframe(
    df_display,
    use_container_width=True,
    height=580,
    column_config={
        "1º Pagamento": st.column_config.DateColumn("1º Pagamento", format="DD/MM/YYYY"),
        "Cód. InChurch": st.column_config.TextColumn("Cód. InChurch"),
    },
    hide_index=True,
)

csv = df_display.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
st.download_button(
    label="⬇️ Exportar CSV",
    data=csv,
    file_name="conferencias_pendencias.csv",
    mime="text/csv",
)
