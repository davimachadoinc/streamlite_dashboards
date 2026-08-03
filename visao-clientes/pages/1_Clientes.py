"""
pages/1_Clientes.py
Tabela de clientes: MRR ativo e transacionado (TPV) dos últimos 6 meses, com filtro de plano.
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Visão de Clientes | InChurch", page_icon="🏢", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "visao_clientes"

from utils.style import inject_css
from utils.data import (
    PLAN_LABELS, DEFAULT_PLAN_FILTER,
    fmt_brl, no_data, load_visao_clientes,
)

inject_css()

with st.sidebar:
    st.markdown("---")
    if st.button("🔄 Limpar cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "**MRR ativo** = soma das mensalidades vigentes hoje no Superlógica (exclui Setup/PRO-RATA).\n\n"
        "**Transacionado (6m)** = volume pago via pix/crédito/boleto na plataforma InChurch "
        "nos últimos 6 meses (exclui métodos free/external/debit)."
    )

st.markdown("<h1>Visão de <span>Clientes</span></h1>", unsafe_allow_html=True)

with st.spinner("Carregando dados..."):
    df = load_visao_clientes()

if df.empty:
    no_data("Nenhuma igreja com MRR ativo encontrada.")
    st.stop()

# ── Filtro de plano ────────────────────────────
planos_disponiveis = sorted(df["plano"].dropna().unique().tolist())
default_sel = [p for p in DEFAULT_PLAN_FILTER if p in planos_disponiveis] or planos_disponiveis

planos_sel = st.multiselect(
    "Plano",
    options=planos_disponiveis,
    default=default_sel,
    format_func=lambda p: PLAN_LABELS.get(p, p.title()),
)

df_f = df[df["plano"].isin(planos_sel)] if planos_sel else df.iloc[0:0]

# ── KPIs ────────────────────────────────────────
k1, k2, k3 = st.columns(3)
with k1:
    st.metric("Igrejas", f"{len(df_f):,}")
with k2:
    st.metric("MRR Ativo Total", f"R$ {fmt_brl(df_f['mrr_ativo'].sum(), 0)}")
with k3:
    st.metric("Transacionado Total (6m)", f"R$ {fmt_brl(df_f['transacionado_6m'].sum(), 0)}")

st.divider()

# ── Tabela ─────────────────────────────────────
busca = st.text_input("Buscar igreja", placeholder="Digite parte do nome...")

df_show = df_f.copy()
if busca:
    df_show = df_show[df_show["tertiarygroup_name"].str.contains(busca, case=False, na=False)]

st.caption(f"{len(df_show)} igrejas")

disp = df_show.copy()
disp["plano"] = disp["plano"].map(lambda p: PLAN_LABELS.get(p, p.title()))
disp["mrr_ativo"] = disp["mrr_ativo"].apply(lambda v: fmt_brl(v, 2))
disp["transacionado_6m"] = disp["transacionado_6m"].apply(lambda v: fmt_brl(v, 2))

disp = disp.rename(columns={
    "tertiarygroup_id":   "ID",
    "tertiarygroup_name": "Igreja",
    "plano":              "Plano",
    "mrr_ativo":          "MRR Ativo (R$)",
    "transacionado_6m":   "Transacionado 6m (R$)",
})

st.dataframe(
    disp[["ID", "Igreja", "Plano", "MRR Ativo (R$)", "Transacionado 6m (R$)"]],
    use_container_width=True,
    hide_index=True,
)
