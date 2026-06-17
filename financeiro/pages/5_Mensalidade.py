"""
pages/5_Mensalidade.py
Mensalidade mês a mês — receita emitida vs liquidada, por plano, ticket médio e tabela.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Mensalidade | InChurch", page_icon="📅", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "mensalidade"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_mensalidade_historico,
)

inject_css()

# ── Sidebar — período ─────────────────────────
with st.sidebar:
    st.markdown("### 🗓️ Período")
    n = st.selectbox(
        "Histórico",
        options=[12, 24, 36, 0],
        index=1,
        format_func=lambda x: "Tudo" if x == 0 else f"Últimos {x} meses",
        key="period_mensalidade",
    )

# ── Header ─────────────────────────────────────
st.markdown("<h1>Mensalidade <span>Mês a Mês</span></h1>", unsafe_allow_html=True)

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_raw = load_mensalidade_historico(n_months=n if n > 0 else 60)

df = filter_months(df_raw, n, "mes")

# ── Agrega total por mês (sem quebra por plano) ─
df_total = (
    df.groupby("mes", as_index=False)
    .agg(
        clientes=("clientes", "sum"),
        receita_emitida=("receita_emitida", "sum"),
        receita_liquidada=("receita_liquidada", "sum"),
    )
)
df_total["pct_pago"] = (
    df_total["receita_liquidada"] / df_total["receita_emitida"].where(df_total["receita_emitida"] > 0) * 100
).round(1)

# ── KPI Cards ─────────────────────────────────
k1, k2, k3, k4 = st.columns(4)

curr_emit = last_val(df_total, "receita_emitida", "mes")
prev_emit = prev_val(df_total, "receita_emitida", "mes")
with k1:
    st.metric(
        "Receita Emitida (último mês)",
        f"R$ {fmt_brl(curr_emit, 0)}" if curr_emit else "—",
        delta=delta_str(curr_emit, prev_emit, fmt="+,.0f", suffix=" R$"),
    )

curr_liq = last_val(df_total, "receita_liquidada", "mes")
prev_liq = prev_val(df_total, "receita_liquidada", "mes")
with k2:
    st.metric(
        "Receita Liquidada (último mês)",
        f"R$ {fmt_brl(curr_liq, 0)}" if curr_liq else "—",
        delta=delta_str(curr_liq, prev_liq, fmt="+,.0f", suffix=" R$"),
    )

curr_pct = last_val(df_total, "pct_pago", "mes")
prev_pct = prev_val(df_total, "pct_pago", "mes")
with k3:
    st.metric(
        "% Pago (último mês)",
        f"{curr_pct:.1f}%" if curr_pct else "—",
        delta=delta_str(curr_pct, prev_pct, fmt="+.1f", suffix=" p.p."),
    )

curr_cli = last_val(df_total, "clientes", "mes")
prev_cli = prev_val(df_total, "clientes", "mes")
with k4:
    st.metric(
        "Clientes com Mensalidade",
        f"{int(curr_cli):,}" if curr_cli else "—",
        delta=delta_str(curr_cli, prev_cli),
    )

st.divider()

# ── Tabs ──────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["📊 Receita Total", "🗂️ Por Plano", "🎫 Ticket Médio", "📋 Tabela"])

# ─────────────────────────────────────────────
# TAB 1 — Receita Total: Emitida vs Liquidada
# ─────────────────────────────────────────────
with tab1:
    if df_total.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_total)

        fig = go.Figure()
        fig.add_bar(
            x=df_plot["mes_fmt"], y=df_plot["receita_emitida"],
            name="Emitida", marker_color=PALETTE[4], opacity=0.85,
        )
        fig.add_bar(
            x=df_plot["mes_fmt"], y=df_plot["receita_liquidada"],
            name="Liquidada", marker_color=PALETTE[0], opacity=0.95,
        )
        fig.add_scatter(
            x=df_plot["mes_fmt"], y=df_plot["pct_pago"],
            name="% Pago", mode="lines+markers",
            line=dict(color=PALETTE[8], width=2, dash="dot"),
            marker=dict(size=6),
            yaxis="y2",
        )
        fig.update_layout(
            barmode="overlay",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
            yaxis2=dict(
                overlaying="y", side="right", showgrid=False,
                ticksuffix="%", range=[0, 120],
                title="% Pago",
                titlefont=dict(color=PALETTE[8]),
                tickfont=dict(color=PALETTE[8]),
                zeroline=False,
            ),
        )
        st.plotly_chart(chart_layout(fig, height=420, legend_bottom=True), use_container_width=True)

        # % pago como linha separada abaixo
        st.caption("Barras sobrepostas: cinza = emitida, verde = liquidada. Linha pontilhada = % pago (eixo direito).")

# ─────────────────────────────────────────────
# TAB 2 — Por Plano
# ─────────────────────────────────────────────
with tab2:
    if df.empty:
        no_data()
    else:
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Receita Emitida por Plano")
            df_plot, x_order = mes_fmt_ordered(df)
            fig = go.Figure()
            for plano, label in PLAN_LABELS.items():
                sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
                if sub.empty:
                    continue
                fig.add_bar(
                    x=sub["mes_fmt"], y=sub["receita_emitida"],
                    name=label, marker_color=PLAN_COLORS[plano],
                )
            fig.update_layout(
                barmode="stack",
                xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
            )
            st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

        with col_b:
            st.subheader("Clientes por Plano")
            df_plot2, x_order2 = mes_fmt_ordered(df)
            fig2 = go.Figure()
            for plano, label in PLAN_LABELS.items():
                sub = df_plot2[df_plot2["plano"] == plano].sort_values("mes")
                if sub.empty:
                    continue
                fig2.add_scatter(
                    x=sub["mes_fmt"], y=sub["clientes"],
                    name=label, mode="lines+markers",
                    line=dict(color=PLAN_COLORS[plano], width=2.5),
                    marker=dict(size=7),
                )
            fig2.update_layout(
                xaxis=dict(categoryorder="array", categoryarray=x_order2, type="category"),
            )
            st.plotly_chart(chart_layout(fig2, legend_bottom=True), use_container_width=True)

        st.subheader("Receita Liquidada por Plano")
        df_plot3, x_order3 = mes_fmt_ordered(df)
        fig3 = go.Figure()
        for plano, label in PLAN_LABELS.items():
            sub = df_plot3[df_plot3["plano"] == plano].sort_values("mes")
            if sub.empty:
                continue
            fig3.add_bar(
                x=sub["mes_fmt"], y=sub["receita_liquidada"],
                name=label, marker_color=PLAN_COLORS[plano],
            )
        fig3.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order3, type="category"),
        )
        st.plotly_chart(chart_layout(fig3, height=360, legend_bottom=True), use_container_width=True)

# ─────────────────────────────────────────────
# TAB 3 — Ticket Médio
# ─────────────────────────────────────────────
with tab3:
    if df.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df)
        fig = go.Figure()
        for plano, label in PLAN_LABELS.items():
            sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
            if sub.empty or sub["ticket_medio"].isna().all():
                continue
            fig.add_scatter(
                x=sub["mes_fmt"], y=sub["ticket_medio"],
                name=label, mode="lines+markers",
                line=dict(color=PLAN_COLORS[plano], width=2.5),
                marker=dict(size=7),
            )
        fig.update_layout(
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
            yaxis=dict(tickprefix="R$ "),
        )
        st.plotly_chart(chart_layout(fig, height=420, legend_bottom=True), use_container_width=True)
        st.caption("Ticket médio = receita emitida ÷ clientes com mensalidade no mês.")

# ─────────────────────────────────────────────
# TAB 4 — Tabela Detalhada
# ─────────────────────────────────────────────
with tab4:
    if df_total.empty:
        no_data()
    else:
        # Pivot por plano para visualização tabular
        pivot = df.pivot_table(
            index="mes", columns="plano",
            values="receita_emitida", aggfunc="sum", fill_value=0,
        ).reset_index()

        # Junta com totais
        pivot = pivot.merge(
            df_total[["mes", "receita_emitida", "receita_liquidada", "pct_pago", "clientes"]],
            on="mes",
        )
        pivot = pivot.sort_values("mes", ascending=False)
        pivot["mes_fmt"] = pivot["mes"].dt.strftime("%b/%Y").str.capitalize()

        # Colunas de plano presentes no pivot
        plan_cols = [c for c in PLAN_LABELS if c in pivot.columns]

        display_cols = ["mes_fmt"] + plan_cols + ["receita_emitida", "receita_liquidada", "pct_pago", "clientes"]
        display = pivot[display_cols].copy()

        rename_map = {p: PLAN_LABELS[p] for p in plan_cols}
        rename_map.update({
            "mes_fmt": "Mês",
            "receita_emitida": "Total Emitido (R$)",
            "receita_liquidada": "Total Liquidado (R$)",
            "pct_pago": "% Pago",
            "clientes": "Clientes",
        })
        display = display.rename(columns=rename_map)

        # Formata colunas numéricas
        money_cols = [PLAN_LABELS[p] for p in plan_cols] + ["Total Emitido (R$)", "Total Liquidado (R$)"]
        for col in money_cols:
            if col in display.columns:
                display[col] = display[col].apply(lambda v: fmt_brl(v, 0))

        if "% Pago" in display.columns:
            display["% Pago"] = display["% Pago"].apply(lambda v: f"{v:.1f}%")

        st.dataframe(display, use_container_width=True, hide_index=True)
