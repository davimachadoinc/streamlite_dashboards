"""
pages/2_💳_Transacoes.py
Dashboard de Transações — últimos 15 meses.
Métodos: pix, credit, billet (excluídos: free, external, debit).
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Transações | InChurch", page_icon="💳", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "transacoes"

from utils.style import inject_css
from utils.data import (
    PALETTE, chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, no_data,
    load_transactions_por_metodo, load_transactions_clientes_por_mes,
    load_intermediacao_mensal, load_take_rate_snapshot, load_take_rate_historico,
)

inject_css()

METHOD_PALETTE = {
    "pix":    "#6eda2c",
    "credit": "#ffffff",
    "billet": "#a0a0a0",
}

def method_color(m: str) -> str:
    colors = ["#6eda2c","#ffffff","#57d124","#a0a0a0","#8ae650","#3ba811","#cccccc"]
    keys = list(METHOD_PALETTE.keys())
    if m in METHOD_PALETTE:
        return METHOD_PALETTE[m]
    idx = hash(m) % len(colors)
    return colors[idx]

# ── Header ────────────────────────────────────
col_title, col_filter = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Transações <span>por Método</span></h1>", unsafe_allow_html=True)
with col_filter:
    n_months = period_selector()

# ── Carga ─────────────────────────────────────
with st.spinner("Carregando dados de transações..."):
    df_raw        = load_transactions_por_metodo()
    df_cli_raw    = load_transactions_clientes_por_mes()
    df_interm_raw = load_intermediacao_mensal()
    snap_tr       = load_take_rate_snapshot()
    df_tr_hist    = load_take_rate_historico()

if df_raw.empty:
    no_data("Nenhum dado de transação encontrado.")
    st.stop()

# ── Filtros (sidebar) ─────────────────────────
with st.sidebar:
    st.markdown("### 📡 Canal de Pagamento")
    channels = sorted(df_raw["payment_channel"].dropna().unique().tolist())
    selected_channels = st.multiselect(
        "Filtrar por canal", options=channels, default=channels, key="filter_channels"
    )
    st.markdown("### 🏷️ Tipo de Transação")
    tipos = sorted(df_raw["tipo"].dropna().unique().tolist())
    TIPO_LABELS = {"doacao": "Doação", "outros": "Outros"}
    selected_tipos = st.multiselect(
        "Filtrar por tipo",
        options=tipos,
        default=tipos,
        format_func=lambda t: TIPO_LABELS.get(t, t),
        key="filter_tipos",
    )

if not selected_channels:
    st.warning("Selecione ao menos um canal.", icon="⚠️")
    st.stop()
if not selected_tipos:
    st.warning("Selecione ao menos um tipo.", icon="⚠️")
    st.stop()

# ── Aplicar filtros ───────────────────────────
df = df_raw[
    df_raw["payment_channel"].isin(selected_channels) &
    df_raw["tipo"].isin(selected_tipos)
].copy()
df = filter_months(df, n_months, "mes")

df_cli = df_cli_raw[
    df_cli_raw["payment_channel"].isin(selected_channels) &
    df_cli_raw["tipo"].isin(selected_tipos)
].copy()
df_cli = filter_months(df_cli, n_months, "mes")

df_interm = filter_months(df_interm_raw, n_months, "mes")

if df.empty:
    no_data("Nenhuma transação com os filtros selecionados.")
    st.stop()

# Agrupa por mês + método
df_agg = (
    df.groupby(["mes", "payment_method"], as_index=False)
    .agg(total_value=("total_value", "sum"), qtd=("qtd_transacoes", "sum"))
)
df_agg, x_order = mes_fmt_ordered(df_agg)

# Total geral por mês
df_total = df_agg.groupby("mes", as_index=False).agg(
    total_value=("total_value", "sum"), qtd=("qtd", "sum")
).sort_values("mes")
df_total, x_order_total = mes_fmt_ordered(df_total)

methods = sorted(df_agg["payment_method"].unique().tolist())

# ── KPI Cards ─────────────────────────────────
# Clientes por mês (sem dupla contagem por método)
df_cli_mes = (
    df_cli.groupby("mes", as_index=False)
    .agg(clientes=("clientes", "sum"))
    .sort_values("mes")
)

st.subheader("Visão Geral do Período")
k1, k2, k3, k4, k5 = st.columns(5)

curr_val = last_val(df_total, "total_value", "mes")
prev_val_ = prev_val(df_total, "total_value", "mes")
with k1:
    st.metric("Volume Total (R$)",
              f"R$ {curr_val:,.2f}" if curr_val else "—",
              delta=delta_str(curr_val, prev_val_, fmt="+,.2f", suffix=" R$"))

curr_qtd = last_val(df_total, "qtd", "mes")
prev_qtd = prev_val(df_total, "qtd", "mes")
with k2:
    st.metric("Qtd. de Transações",
              f"{int(curr_qtd):,}" if curr_qtd else "—",
              delta=delta_str(curr_qtd, prev_qtd))

ticket    = (curr_val / curr_qtd) if (curr_val and curr_qtd and curr_qtd > 0) else None
prev_tick = (prev_val_ / prev_qtd) if (prev_val_ and prev_qtd and prev_qtd > 0) else None
with k3:
    st.metric("Ticket Médio",
              f"R$ {ticket:,.2f}" if ticket else "—",
              delta=delta_str(ticket, prev_tick, fmt="+,.2f", suffix=" R$"))

curr_cli = last_val(df_cli_mes, "clientes", "mes")
prev_cli = prev_val(df_cli_mes, "clientes", "mes")
with k4:
    st.metric("Clientes Transacionando",
              f"{int(curr_cli):,}" if curr_cli else "—",
              delta=delta_str(curr_cli, prev_cli))

with k5:
    st.metric("Métodos Ativos", str(len(methods)))

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 1 — Volume por Método
# ─────────────────────────────────────────────
st.subheader("Volume Financeiro por Método de Pagamento")
col_a, col_b = st.columns(2)

# Gráfico 1A — Barras empilhadas
with col_a:
    st.subheader("Volume (R$) — Empilhado por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_bar(x=sub["mes_fmt"], y=sub["total_value"],
                    name=method, marker_color=method_color(method))
    fig.update_layout(
        barmode="stack",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# Gráfico 1B — Barras agrupadas
with col_b:
    st.subheader("Volume (R$) — Comparativo por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_bar(x=sub["mes_fmt"], y=sub["total_value"],
                    name=method, marker_color=method_color(method))
    fig.update_layout(
        barmode="group",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 2 — Tendência e Distribuição
# ─────────────────────────────────────────────
st.subheader("Tendência e Distribuição")
col_c, col_d = st.columns(2)

# Gráfico 2A — Linhas de tendência
with col_c:
    st.subheader("Tendência de Volume por Método")
    fig = go.Figure()
    for method in methods:
        sub = df_agg[df_agg["payment_method"] == method].sort_values("mes")
        fig.add_scatter(
            x=sub["mes_fmt"], y=sub["total_value"],
            name=method, mode="lines+markers",
            line=dict(color=method_color(method), width=2.5),
            marker=dict(size=6),
        )
    fig.update_layout(
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, legend_bottom=True), use_container_width=True)

# Gráfico 2B — Participação % último mês (pizza)
with col_d:
    st.subheader("Participação por Método — Último Mês")
    last_month = df_agg["mes"].max()
    df_last = df_agg[df_agg["mes"] == last_month]
    if df_last.empty:
        no_data()
    else:
        fig = go.Figure(go.Pie(
            labels=df_last["payment_method"],
            values=df_last["total_value"],
            hole=0.45,
            marker_colors=[method_color(m) for m in df_last["payment_method"]],
            textfont=dict(size=12, family="Outfit"),
        ))
        fig.update_traces(
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>",
        )
        st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 3 — Volume Total + Qtd (dual axis)
# ─────────────────────────────────────────────
st.subheader("Volume Total (R$) e Quantidade de Transações")
fig = go.Figure()
fig.add_bar(
    x=df_total["mes_fmt"], y=df_total["total_value"],
    name="Volume (R$)", marker_color=PALETTE[0], opacity=0.85, yaxis="y",
)
fig.add_scatter(
    x=df_total["mes_fmt"], y=df_total["qtd"],
    name="Qtd. Transações", mode="lines+markers",
    line=dict(color=PALETTE[1], width=2.5), marker=dict(size=7), yaxis="y2",
)
fig.update_layout(
    yaxis2=dict(overlaying="y", side="right", showgrid=False, color=PALETTE[1]),
    xaxis=dict(categoryorder="array", categoryarray=x_order_total, type="category"),
)
st.plotly_chart(chart_layout(fig, height=400, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 4 — Clientes Transacionando
# ─────────────────────────────────────────────
st.subheader("Clientes Transacionando por Mês")

if df_cli_mes.empty:
    no_data("Sem dados de clientes para o período.")
else:
    df_cli_mes_fmt, x_order_cli = mes_fmt_ordered(df_cli_mes)

    col_e, col_f = st.columns(2)

    # Gráfico 4A — Barras de clientes por mês
    with col_e:
        st.subheader("Clientes com Transação (por Mês)")
        fig = go.Figure()
        fig.add_bar(
            x=df_cli_mes_fmt["mes_fmt"], y=df_cli_mes_fmt["clientes"],
            name="Clientes", marker_color=PALETTE[0],
        )
        fig.update_layout(
            xaxis=dict(categoryorder="array", categoryarray=x_order_cli, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

    # Gráfico 4B — Clientes por tipo (doacao vs outros), se ambos selecionados
    with col_f:
        st.subheader("Clientes por Tipo de Transação")
        df_cli_tipo = (
            df_cli.groupby(["mes", "tipo"], as_index=False)
            .agg(clientes=("clientes", "sum"))
        )
        TIPO_COLORS = {"doacao": PALETTE[0], "outros": PALETTE[3]}
        if df_cli_tipo.empty:
            no_data()
        else:
            df_cli_tipo_fmt, x_order_ct = mes_fmt_ordered(df_cli_tipo)
            fig = go.Figure()
            for t in sorted(df_cli_tipo_fmt["tipo"].unique()):
                sub = df_cli_tipo_fmt[df_cli_tipo_fmt["tipo"] == t].sort_values("mes")
                fig.add_bar(
                    x=sub["mes_fmt"], y=sub["clientes"],
                    name=TIPO_LABELS.get(t, t),
                    marker_color=TIPO_COLORS.get(t, PALETTE[3]),
                )
            fig.update_layout(
                barmode="group",
                xaxis=dict(categoryorder="array", categoryarray=x_order_ct, type="category"),
            )
            st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ─────────────────────────────────────────────
# SEÇÃO 5 — Take Rate (Intermediação / TPV)
# ─────────────────────────────────────────────
st.subheader("Take Rate — Intermediação de Negócios / TPV")

if snap_tr == {} and df_tr_hist.empty:
    no_data("Sem dados suficientes para calcular o Take Rate.")
else:
    # ── Snapshot — intermediação do mês / TPV do último dia de liquidação ───
    snap_dia = snap_tr.get("dia", "—")
    snap_int = snap_tr.get("receita_intermediacao")
    snap_tpv = snap_tr.get("tpv")
    snap_pct = snap_tr.get("take_rate_pct")

    st.caption(
        f"Snapshot: intermediação liquidada no mês atual · "
        f"TPV do último dia de liquidação: **{snap_dia}**"
    )

    sn1, sn2, sn3 = st.columns(3)
    with sn1:
        st.metric(
            "Take Rate",
            f"{snap_pct:.4f}%" if snap_pct is not None else "—",
        )
    with sn2:
        st.metric(
            "Intermediação Liquidada no Mês (R$)",
            f"R$ {snap_int:,.2f}" if snap_int is not None else "—",
        )
    with sn3:
        st.metric(
            "TPV no Último Dia de Liquidação (R$)",
            f"R$ {snap_tpv:,.2f}" if snap_tpv is not None else "—",
        )

    st.markdown("")

    # ── Gráficos históricos — regra: último dia de liquidação por mês ───
    df_tr_hist_f = filter_months(df_tr_hist, n_months, "mes")

    if df_tr_hist_f.empty:
        no_data("Sem histórico de take rate para o período.")
    else:
        df_tr_fmt, x_order_tr = mes_fmt_ordered(df_tr_hist_f)
        col_tr_a, col_tr_b = st.columns(2)

        with col_tr_a:
            st.subheader("Take Rate (%) — Evolução Mensal")
            fig = go.Figure()
            fig.add_scatter(
                x=df_tr_fmt["mes_fmt"], y=df_tr_fmt["take_rate_pct"],
                name="Take Rate (%)", mode="lines+markers",
                line=dict(color=PALETTE[0], width=2.5),
                marker=dict(size=7),
                hovertemplate="<b>%{x}</b><br>Take Rate: %{y:.4f}%<br>Ref: %{customdata}<extra></extra>",
                customdata=df_tr_fmt["dia_ref"],
            )
            fig.update_layout(
                xaxis=dict(categoryorder="array", categoryarray=x_order_tr, type="category"),
                yaxis=dict(ticksuffix="%"),
            )
            st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)

        with col_tr_b:
            st.subheader("Intermediação (R$) e TPV do Dia — Mensal")
            fig = go.Figure()
            fig.add_bar(
                x=df_tr_fmt["mes_fmt"], y=df_tr_fmt["tpv"],
                name="TPV do Dia (R$)", marker_color=PALETTE[3], opacity=0.7,
                hovertemplate="<b>%{x}</b><br>TPV: R$ %{y:,.2f}<extra></extra>",
            )
            fig.add_bar(
                x=df_tr_fmt["mes_fmt"], y=df_tr_fmt["receita_intermediacao"],
                name="Intermediação (R$)", marker_color=PALETTE[0],
                hovertemplate="<b>%{x}</b><br>Intermediação: R$ %{y:,.2f}<extra></extra>",
            )
            fig.update_layout(
                barmode="overlay",
                xaxis=dict(categoryorder="array", categoryarray=x_order_tr, type="category"),
            )
            st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ── Tabela detalhada ──────────────────────────
with st.expander("📋 Tabela Detalhada por Mês e Método"):
    st.markdown("**Volume (R$) por método**")
    df_table_val = (
        df_agg
        .pivot_table(index="mes_fmt", columns="payment_method",
                     values="total_value", aggfunc="sum")
        .round(2)
        .reindex(x_order)
        .reset_index()
        .rename(columns={"mes_fmt": "Mês"})
    )
    st.dataframe(df_table_val, use_container_width=True, hide_index=True)

    st.markdown("**Quantidade de transações por método**")
    df_table_qtd = (
        df_agg
        .pivot_table(index="mes_fmt", columns="payment_method",
                     values="qtd", aggfunc="sum")
        .astype("Int64")
        .reindex(x_order)
        .reset_index()
        .rename(columns={"mes_fmt": "Mês"})
    )
    st.dataframe(df_table_qtd, use_container_width=True, hide_index=True)