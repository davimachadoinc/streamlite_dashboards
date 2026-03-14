"""
pages/4_⚠️_Inadimplencia.py
Dashboard de Inadimplência — série diária 30d / 90d e perfil dos inadimplentes.

Racional — janela ROLANTE:
  Para cada dia de observação D no eixo X:
    30d → considera boletos com vencimento em [D-30, D]
    90d → considera boletos com vencimento em [D-90, D]
    % = valor não pago EM D / total emitido na janela

  Exemplo: em 12/02, 30d olha boletos vencidos de 13/jan a 12/fev.
  Se em 13/02 um boleto de 05/fev for pago, ele sai do numerador do dia 13/02.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Inadimplência | InChurch", page_icon="⚠️", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "inadimplencia"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data, fmt_brl,
    load_inadimplencia_serie, load_inadimplencia_por_plano,
    load_inadimplencia_top_clientes,
)

inject_css()

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Inadimplência <span>& Perfil</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de inadimplência..."):
    df_serie  = load_inadimplencia_serie()
    df_plano  = load_inadimplencia_por_plano()
    df_top30  = load_inadimplencia_top_clientes(30)
    df_top90  = load_inadimplencia_top_clientes(90)

if df_serie.empty:
    no_data("Nenhum dado de inadimplência encontrado.")
    st.stop()

df_serie = filter_months(df_serie, n_months, "dia")

if df_serie.empty:
    no_data("Nenhuma cobrança no período selecionado.")
    st.stop()

df_serie = df_serie.sort_values("dia")

# ── KPI Cards ─────────────────────────────────
st.subheader("Visão Geral do Período")
k1, k2, k3, k4 = st.columns(4)

curr_30 = last_val(df_serie, "pct_inadimp_30d", "dia")
prev_30 = prev_val(df_serie, "pct_inadimp_30d", "dia")
with k1:
    st.metric(
        "Inadimplência 30d (último dia)",
        f"{curr_30:.1f}%" if curr_30 is not None else "—",
        delta=delta_str(curr_30, prev_30, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

aberto_30d_atual = last_val(df_serie, "aberto_30d", "dia")
with k2:
    st.metric("Valor em Aberto 30d (snapshot)", f"R$ {fmt_brl(aberto_30d_atual)}" if aberto_30d_atual is not None else "—")

curr_90 = last_val(df_serie, "pct_inadimp_90d", "dia")
prev_90 = prev_val(df_serie, "pct_inadimp_90d", "dia")
with k3:
    st.metric(
        "Inadimplência 90d (último dia)",
        f"{curr_90:.1f}%" if curr_90 is not None else "—",
        delta=delta_str(curr_90, prev_90, fmt="+.1f", suffix=" p.p."),
        delta_color="inverse",
    )

aberto_90d_atual = last_val(df_serie, "aberto_90d", "dia")
with k4:
    st.metric("Valor em Aberto 90d (snapshot)", f"R$ {fmt_brl(aberto_90d_atual)}" if aberto_90d_atual is not None else "—")

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Inadimplência 30d vs 90d (janela rolante)
# ─────────────────────────────────────────────
st.subheader("Inadimplência — Janela 30 dias vs 90 dias")

if df_serie.empty:
    no_data("Sem dados suficientes para o período.")
else:
    fig = go.Figure()
    fig.add_scatter(
        x=df_serie["dia"], y=df_serie["pct_inadimp_30d"],
        name="30d (vencidos últimos 30 dias)",
        mode="lines", line=dict(color=PALETTE[0], width=2),
    )
    fig.add_scatter(
        x=df_serie["dia"], y=df_serie["pct_inadimp_90d"],
        name="90d (vencidos últimos 90 dias)",
        mode="lines", line=dict(color=PALETTE[3], width=1.5, dash="dot"),
    )
    fig.update_layout(
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(type="date", tickformat="%d/%b/%y", dtick=604800000),
    )
    st.plotly_chart(chart_layout(fig, height=380, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Perfil dos Inadimplentes (snapshot 30d atual)
# ─────────────────────────────────────────────
st.subheader("Perfil dos Inadimplentes (30d — snapshot atual)")

col_a, col_b = st.columns(2)

with col_a:
    st.subheader("Valor em Aberto por Plano")
    if df_plano.empty:
        no_data()
    else:
        df_p = df_plano[df_plano["plano"].isin(PLAN_LABELS.keys())].copy()
        df_p["label"] = df_p["plano"].map(PLAN_LABELS)
        df_p["cor"]   = df_p["plano"].map(PLAN_COLORS)
        df_p = df_p.sort_values("valor_aberto", ascending=True)
        fig = go.Figure()
        fig.add_bar(
            x=df_p["valor_aberto"], y=df_p["label"],
            orientation="h",
            marker_color=df_p["cor"].tolist(),
            text=df_p["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v, 0)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(
            showlegend=False,
            xaxis=dict(showgrid=True, gridcolor="#292929", type="linear"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

with col_b:
    st.subheader("Clientes Inadimplentes por Plano")
    if df_plano.empty:
        no_data()
    else:
        df_p2 = df_plano[df_plano["plano"].isin(PLAN_LABELS.keys())].copy()
        df_p2["label"] = df_p2["plano"].map(PLAN_LABELS)
        df_p2["cor"]   = df_p2["plano"].map(PLAN_COLORS)
        df_p2 = df_p2.sort_values("clientes_inadimplentes", ascending=False)
        fig = go.Figure()
        fig.add_bar(
            x=df_p2["label"], y=df_p2["clientes_inadimplentes"],
            marker_color=df_p2["cor"].tolist(),
            text=df_p2["clientes_inadimplentes"].apply(lambda v: f"{int(v):,}".replace(",", ".")),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

st.divider()

# ── Tabelas Top Inadimplentes ─────────────────
def _render_top_table(df: pd.DataFrame) -> None:
    if df.empty:
        no_data()
        return
    df_show = df.copy()
    df_show["plano"]        = df_show["plano"].map(PLAN_LABELS).fillna(df_show["plano"])
    df_show["valor_aberto"] = df_show["valor_aberto"].apply(lambda v: f"R$ {fmt_brl(v)}")
    df_show = df_show.rename(columns={
        "id_cliente":      "ID",
        "nome_cliente":    "Cliente",
        "plano":           "Plano",
        "valor_aberto":    "Valor em Aberto",
        "boletos_abertos": "Boletos Abertos",
        "max_dias_atraso": "Máx. Dias Atraso",
    })
    st.dataframe(df_show, use_container_width=True, hide_index=True)

with st.expander("📋 Top 30 Clientes — Maior Valor em Aberto (30d)"):
    _render_top_table(df_top30)

with st.expander("📋 Top 30 Clientes — Maior Valor em Aberto (90d)"):
    _render_top_table(df_top90)
