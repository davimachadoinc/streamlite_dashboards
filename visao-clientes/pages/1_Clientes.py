"""
pages/1_Clientes.py
Tabela de clientes: MRR ativo e transacionado (TPV) mês a mês, com filtro de plano.
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
        "**MRR ativo** = soma das mensalidades vigentes hoje no Superlógica (exclui Setup/PRO-RATA/"
        "Desconto/Abono/Intermediação/Acordo/Reajuste).\n\n"
        "**Transacionado** = volume pago via pix/crédito/boleto na plataforma InChurch "
        "(exclui métodos free/external/debit). Tendência = últimos 6 meses; variação = mês atual vs. mês anterior."
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
    st.metric("Transacionado Total (mês atual)", f"R$ {fmt_brl(df_f['transacionado_mes_atual'].sum(), 0)}")

st.divider()

# ── Tabela ─────────────────────────────────────
busca = st.text_input("Buscar igreja", placeholder="Digite parte do nome...")

df_show = df_f.copy()
if busca:
    df_show = df_show[df_show["tertiarygroup_name"].str.contains(busca, case=False, na=False)]

st.caption(f"{len(df_show)} igrejas")

disp = df_show.copy()
disp["plano"] = disp["plano"].map(lambda p: PLAN_LABELS.get(p, p.title()))
disp["variacao_fmt"] = disp["transacionado_variacao_mom"].apply(
    lambda v: "—" if pd.isna(v) else f"{'▲' if v >= 0 else '▼'} {v:+.1f}%"
)

disp = disp.rename(columns={
    "tertiarygroup_id":       "ID",
    "tertiarygroup_name":     "Igreja",
    "plano":                  "Plano",
    "mrr_ativo":              "MRR Ativo (R$)",
    "transacionado_trend":    "Tendência (6m)",
    "transacionado_mes_atual":"Transacionado Mês Atual (R$)",
    "variacao_fmt":           "Variação vs. Mês Anterior",
})

st.dataframe(
    disp[[
        "ID", "Igreja", "Plano", "MRR Ativo (R$)",
        "Tendência (6m)", "Transacionado Mês Atual (R$)", "Variação vs. Mês Anterior",
    ]],
    use_container_width=True,
    hide_index=True,
    column_config={
        "MRR Ativo (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
        "Tendência (6m)": st.column_config.LineChartColumn(
            "Tendência (6m)", help="Transacionado nos últimos 6 meses (mais antigo → mais recente)",
        ),
        "Transacionado Mês Atual (R$)": st.column_config.NumberColumn(format="R$ %.2f"),
    },
)
