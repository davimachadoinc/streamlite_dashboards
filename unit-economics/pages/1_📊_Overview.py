"""
pages/1_📊_Overview.py
Visão geral: MRR waterfall, NRR, composição por plano.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Overview | Unit Economics", page_icon="📊", layout="wide")

if "auth" in st.secrets and not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado.")
    st.stop()

st.session_state["_page_key"] = "overview"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_mrr_waterfall, load_mrr_por_plano,
)

inject_css()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Overview <span>Unit Economics</span></h1>", unsafe_allow_html=True)
with col_period:
    n_months = period_selector("overview")

# ── Carga ─────────────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_wf  = load_mrr_waterfall()
    df_plan = load_mrr_por_plano()

df_wf_f   = filter_months(df_wf, n_months)
df_plan_f = filter_months(df_plan, n_months)

# ── KPIs ──────────────────────────────────────────────────────────────────────
st.subheader("Resumo do Período")
k1, k2, k3, k4, k5 = st.columns(5)

mrr_atual   = last_val(df_wf_f, "mrr_fim")
mrr_prev    = prev_val(df_wf_f, "mrr_fim")
clientes    = last_val(df_wf_f, "clientes_inicio")
nrr_atual   = last_val(df_wf_f, "nrr")
nrr_prev    = prev_val(df_wf_f, "nrr")
arpu_atual  = round(mrr_atual / clientes, 0) if (mrr_atual and clientes) else None

with k1:
    st.metric("MRR Atual", f"R$ {fmt_brl(mrr_atual)}" if mrr_atual else "—",
              delta=delta_str(mrr_atual, mrr_prev, fmt="+,.0f", suffix=" R$"))
with k2:
    st.metric("Clientes Ativos", f"{int(clientes):,}".replace(",", ".") if clientes else "—")
with k3:
    st.metric("ARPU", f"R$ {fmt_brl(arpu_atual)}" if arpu_atual else "—")
with k4:
    st.metric("NRR (último mês)", f"{nrr_atual:.1f}%" if nrr_atual else "—",
              delta=delta_str(nrr_atual, nrr_prev, fmt="+.1f", suffix=" pp"))
with k5:
    expansion = last_val(df_wf_f, "expansion_mrr")
    churn_mrr = last_val(df_wf_f, "churned_mrr")
    net_exp = (expansion or 0) - (churn_mrr or 0)
    color = "normal" if net_exp >= 0 else "inverse"
    st.metric("Net Expansion MRR", f"R$ {fmt_brl(abs(net_exp))}" if net_exp is not None else "—",
              delta=f"{'▲' if net_exp >= 0 else '▼'} líquido")

st.divider()

# ── Gráfico 1: Movimentos mensais de MRR (barras empilhadas + linha NRR) ──────
st.subheader("Movimentos de MRR")

if df_wf_f.empty:
    no_data()
else:
    df_plot, x_order = mes_fmt_ordered(df_wf_f)

    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["new_logo_mrr"],
        name="New Logo", marker_color=PALETTE[0],
        hovertemplate="<b>New Logo</b><br>R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["expansion_mrr"],
        name="Expansion", marker_color=PALETTE[3],
        hovertemplate="<b>Expansion</b><br>R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_bar(
        x=df_plot["mes_fmt"], y=-df_plot["churned_mrr"],
        name="Churn", marker_color=PALETTE[9],
        hovertemplate="<b>Churn</b><br>R$ %{customdata:,.0f}<extra></extra>",
        customdata=df_plot["churned_mrr"],
    )
    # NRR como linha no eixo secundário
    fig.add_scatter(
        x=df_plot["mes_fmt"], y=df_plot["nrr"],
        name="NRR %", mode="lines+markers",
        line=dict(color=PALETTE[1], width=2, dash="dot"),
        marker=dict(size=6),
        yaxis="y2",
        hovertemplate="<b>NRR</b> %{y:.1f}%<extra></extra>",
    )
    # Alinha o zero dos dois eixos Y proporcionalmente
    y1_neg = df_plot["churned_mrr"].max()  # barras de churn descem abaixo de zero
    y1_pos = (df_plot["new_logo_mrr"] + df_plot["expansion_mrr"]).max()
    nrr_vals = df_plot["nrr"].dropna()
    y2_max = nrr_vals.max() if not nrr_vals.empty else 120
    frac = y1_neg / (y1_neg + y1_pos) if (y1_neg + y1_pos) > 0 else 0
    y2_total = y2_max / (1 - frac) if frac < 1 else y2_max * 2
    y2_min_adj = -frac * y2_total

    fig.update_layout(
        barmode="relative",
        yaxis=dict(range=[-y1_neg * 1.2, y1_pos * 1.2]),
        yaxis2=dict(
            overlaying="y", side="right", showgrid=False,
            ticksuffix="%", color=PALETTE[1],
            range=[y2_min_adj * 1.2, y2_max * 1.1],
        ),
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=420, legend_bottom=True), use_container_width=True)

st.divider()

# ── Gráfico 1b: Variação mensal do MRR ───────────────────────────────────────
st.subheader("Variação Mensal do MRR")

if df_wf_f.empty:
    no_data()
else:
    df_var, x_order_var = mes_fmt_ordered(df_wf_f)
    df_var = df_var.sort_values("mes")
    df_var["mrr_delta"] = df_var["mrr_fim"].diff()

    delta_colors = [PALETTE[0] if v >= 0 else PALETTE[9]
                    for v in df_var["mrr_delta"].fillna(0)]

    fig = go.Figure()
    fig.add_bar(
        x=df_var["mes_fmt"], y=df_var["mrr_delta"],
        name="Δ MRR", marker_color=delta_colors,
        hovertemplate="<b>Variação</b><br>R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=df_var["mes_fmt"], y=df_var["mrr_fim"],
        name="MRR Total", mode="lines+markers",
        line=dict(color=PALETTE[1], width=2, dash="dot"),
        marker=dict(size=5),
        yaxis="y2",
        hovertemplate="<b>MRR</b> R$ %{y:,.0f}<extra></extra>",
    )
    fig.update_layout(
        yaxis2=dict(overlaying="y", side="right", showgrid=False, color=PALETTE[1]),
        xaxis=dict(categoryorder="array", categoryarray=x_order_var, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=320, legend_bottom=True), use_container_width=True)

st.divider()

# ── Gráfico 2: MRR Total acumulado (linha) + MRR por plano (área empilhada) ──
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("MRR Total")
    if df_wf_f.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_wf_f)
        fig = go.Figure()
        fig.add_scatter(
            x=df_plot["mes_fmt"], y=df_plot["mrr_fim"],
            mode="lines+markers",
            line=dict(color=PALETTE[0], width=3),
            marker=dict(size=7),
            fill="tozeroy",
            fillcolor="rgba(110,218,44,0.08)",
            hovertemplate="<b>MRR</b> R$ %{y:,.0f}<extra></extra>",
        )
        fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"))
        st.plotly_chart(chart_layout(fig, height=340), use_container_width=True)

with col_b:
    st.subheader("MRR por Plano")
    if df_plan_f.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_plan_f)
        fig = go.Figure()
        planos_ordem = ["pro", "lite", "starter", "basic", "filha", "squad", "outros"]
        for plano in planos_ordem:
            sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
            if sub.empty:
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["mrr"],
                name=PLAN_LABELS.get(plano, plano),
                mode="lines",
                stackgroup="one",
                line=dict(color=PLAN_COLORS.get(plano, PALETTE[3]), width=1),
                fillcolor=PLAN_COLORS.get(plano, PALETTE[3]),
                hovertemplate=f"<b>{PLAN_LABELS.get(plano, plano)}</b><br>R$ %{{y:,.0f}}<extra></extra>",
            )
        fig.update_layout(xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"))
        st.plotly_chart(chart_layout(fig, height=340, legend_bottom=True), use_container_width=True)

st.divider()

# ── Tabela resumo waterfall ───────────────────────────────────────────────────
with st.expander("📋 Tabela Waterfall Detalhada"):
    if df_wf_f.empty:
        no_data()
    else:
        df_show = df_wf_f.sort_values("mes", ascending=False).copy()
        df_show["mes"] = df_show["mes"].dt.strftime("%b/%y").str.capitalize()
        df_show = df_show.rename(columns={
            "mes":              "Mês",
            "mrr_inicio":       "MRR Início",
            "new_logo_mrr":     "New Logo",
            "new_clients":      "Novos Clientes",
            "expansion_mrr":    "Expansion",
            "expanded_clients": "Clientes c/ Upsell",
            "churned_mrr":      "Churn MRR",
            "churned_clients":  "Clientes Churned",
            "mrr_fim":          "MRR Fim",
            "nrr":              "NRR %",
        })
        currency_cols = ["MRR Início", "New Logo", "Expansion", "Churn MRR", "MRR Fim"]
        st.dataframe(
            df_show[["Mês", "MRR Início", "New Logo", "Novos Clientes",
                     "Expansion", "Clientes c/ Upsell", "Churn MRR",
                     "Clientes Churned", "MRR Fim", "NRR %"]],
            use_container_width=True,
            hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="R$ %,.0f") for c in currency_cols} | {
                "NRR %": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
