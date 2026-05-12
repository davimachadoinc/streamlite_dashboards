"""
pages/1_Carteira.py
Receita de mensalidade 1.2.2 dos fechamentos de Fabiano Lomar — mês a mês.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Carteira Fabiano | InChurch", page_icon="💼", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

st.session_state["_page_key"] = "carteira_fabiano"

from utils.style import inject_css
from utils.data import (
    PALETTE, COMISSAO_CARTEIRA_PCT,
    chart_layout, mes_fmt_ordered, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_carteira_mensal, load_carteira_clientes, load_carteira_detalhe_mensal,
)

inject_css()

# ── Sidebar — período ─────────────────────────
with st.sidebar:
    st.markdown("### 🗓️ Período")
    n = st.selectbox(
        "Histórico",
        options=[12, 18, 24, 36, 0],
        index=1,
        format_func=lambda x: "Tudo" if x == 0 else f"Últimos {x} meses",
        key="period_carteira",
    )
    st.markdown("---")
    st.caption(
        "**Comissão 5%** = 5% sobre receita liquidada dos clientes vendidos por Fabiano "
        "nos últimos 12 meses (excluindo mês de entrada)."
    )

# ── Header ─────────────────────────────────────
st.markdown(
    "<h1>Carteira <span>Fabiano Lomar</span> — Mensalidade 1.2.2</h1>",
    unsafe_allow_html=True,
)

# ── Carga de dados ─────────────────────────────
with st.spinner("Carregando dados..."):
    df_raw    = load_carteira_mensal()
    df_cli    = load_carteira_clientes()
    df_detalhe = load_carteira_detalhe_mensal()

df = filter_months(df_raw, n, "mes")

if df.empty:
    no_data("Nenhum dado encontrado para o período selecionado.")
    st.stop()

# ── KPI Cards ─────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)

curr_emit = last_val(df, "receita_emitida")
prev_emit = prev_val(df, "receita_emitida")
with k1:
    st.metric(
        "Emitida (último mês)",
        f"R$ {fmt_brl(curr_emit, 0)}" if curr_emit else "—",
        delta=delta_str(curr_emit, prev_emit, fmt="+,.0f", suffix=" R$"),
    )

curr_liq = last_val(df, "receita_liquidada")
prev_liq = prev_val(df, "receita_liquidada")
with k2:
    st.metric(
        "Liquidada (último mês)",
        f"R$ {fmt_brl(curr_liq, 0)}" if curr_liq else "—",
        delta=delta_str(curr_liq, prev_liq, fmt="+,.0f", suffix=" R$"),
    )

curr_pct = last_val(df, "pct_pago")
prev_pct = prev_val(df, "pct_pago")
with k3:
    st.metric(
        "% Pago (último mês)",
        f"{curr_pct:.1f}%" if curr_pct else "—",
        delta=delta_str(curr_pct, prev_pct, fmt="+.1f", suffix=" p.p."),
    )

curr_cli = last_val(df, "clientes")
prev_cli = prev_val(df, "clientes")
with k4:
    st.metric(
        "Clientes (último mês)",
        f"{int(curr_cli):,}" if curr_cli else "—",
        delta=delta_str(curr_cli, prev_cli),
    )

curr_com = last_val(df, "comissao_5pct")
prev_com = prev_val(df, "comissao_5pct")
with k5:
    st.metric(
        "Comissão 5% (último mês)",
        f"R$ {fmt_brl(curr_com, 0)}" if curr_com else "—",
        delta=delta_str(curr_com, prev_com, fmt="+,.0f", suffix=" R$"),
    )

st.divider()

# ── Tabs ──────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Receita", "👥 Clientes", "💰 Comissão 5%", "📋 Tabela Mensal", "🏢 Por Cliente", "🔍 Detalhe por Mês",
])

# ─────────────────────────────────────────────
# TAB 1 — Receita Emitida vs Liquidada
# ─────────────────────────────────────────────
with tab1:
    df_plot, x_order = mes_fmt_ordered(df)

    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["receita_emit_comissao"],
        name="Emitida (elegível)", marker_color=PALETTE[4], opacity=0.85,
        hovertemplate="<b>%{x}</b><br>Emitida elegível: R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["receita_liq_comissao"],
        name="Liquidada (elegível)", marker_color=PALETTE[0], opacity=0.95,
        hovertemplate="<b>%{x}</b><br>Liquidada elegível: R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=df_plot["mes_fmt"], y=df_plot["pct_pago_comissao"],
        name="% Pago", mode="lines+markers",
        line=dict(color=PALETTE[8], width=2, dash="dot"),
        marker=dict(size=6),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>% Pago: %{y:.1f}%<extra></extra>",
    )
    fig.update_layout(
        barmode="overlay",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        yaxis=dict(tickprefix="R$ "),
        yaxis2=dict(
            overlaying="y", side="right", showgrid=False,
            ticksuffix="%", range=[0, 120],
            title=dict(text="% Pago", font=dict(color=PALETTE[8])),
            tickfont=dict(color=PALETTE[8]),
            zeroline=False,
        ),
    )
    st.plotly_chart(chart_layout(fig, height=440, legend_bottom=True), use_container_width=True)
    st.caption("Apenas clientes elegíveis (primeiros 12 meses, excluindo entrada). Linha pontilhada = % pago (eixo direito).")

    # Sumário do período
    total_emit = df["receita_emit_comissao"].sum()
    total_liq  = df["receita_liq_comissao"].sum()
    pct_total  = (total_liq / total_emit * 100) if total_emit > 0 else 0
    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("Total Emitido Elegível", f"R$ {fmt_brl(total_emit, 0)}")
    with s2:
        st.metric("Total Liquidado Elegível", f"R$ {fmt_brl(total_liq, 0)}")
    with s3:
        st.metric("% Pago Médio (elegível)", f"{pct_total:.1f}%")

# ─────────────────────────────────────────────
# TAB 2 — Clientes Pagantes por Mês
# ─────────────────────────────────────────────
with tab2:
    df_plot2, x_order2 = mes_fmt_ordered(df)

    fig2 = go.Figure()
    fig2.add_scatter(
        x=df_plot2["mes_fmt"], y=df_plot2["clientes"],
        mode="lines+markers",
        line=dict(color=PALETTE[0], width=2.5),
        marker=dict(size=7),
        name="Clientes",
        fill="tozeroy",
        fillcolor="rgba(110, 218, 44, 0.08)",
        hovertemplate="<b>%{x}</b><br>Clientes: %{y:,}<extra></extra>",
    )
    fig2.update_layout(
        xaxis=dict(categoryorder="array", categoryarray=x_order2, type="category"),
    )
    st.plotly_chart(chart_layout(fig2, height=400), use_container_width=True)
    st.caption("Clientes distintos com boleto 1.2.2 emitido no mês.")

# ─────────────────────────────────────────────
# TAB 3 — Comissão 5%
# ─────────────────────────────────────────────
with tab3:
    st.info(
        f"Comissão de **{COMISSAO_CARTEIRA_PCT*100:.0f}%** sobre a receita liquidada "
        "dos clientes de carteira de Fabiano (últimos 12 meses de vínculo, excluindo mês de entrada).",
        icon="ℹ️",
    )
    df_plot3, x_order3 = mes_fmt_ordered(df)

    fig3 = go.Figure()
    fig3.add_bar(
        x=df_plot3["mes_fmt"], y=df_plot3["comissao_5pct"],
        name="Comissão (R$)",
        marker_color=PALETTE[6],
        hovertemplate="<b>%{x}</b><br>Comissão: R$ %{y:,.0f}<extra></extra>",
    )
    fig3.update_layout(
        xaxis=dict(categoryorder="array", categoryarray=x_order3, type="category"),
        yaxis=dict(tickprefix="R$ "),
    )
    st.plotly_chart(chart_layout(fig3, height=400), use_container_width=True)

    total_com = df["comissao_5pct"].sum()
    st.metric(
        f"Total Comissão 5% no Período ({n if n > 0 else 'todo histórico'} meses)",
        f"R$ {fmt_brl(total_com, 0)}",
    )

# ─────────────────────────────────────────────
# TAB 4 — Tabela Mensal
# ─────────────────────────────────────────────
with tab4:
    display = df.sort_values("mes", ascending=False).copy()

    display = display.rename(columns={
        "mes":              "Mês",
        "clientes":         "Clientes",
        "receita_emitida":  "Emitida (R$)",
        "receita_liquidada":"Liquidada (R$)",
        "pct_pago":         "% Pago",
        "comissao_5pct":    "Comissão 5% (R$)",
    })

    for col in ["Emitida (R$)", "Liquidada (R$)", "Comissão 5% (R$)"]:
        display[col] = display[col].apply(lambda v: fmt_brl(v, 0))
    display["% Pago"] = display["% Pago"].apply(lambda v: f"{v:.1f}%")

    st.dataframe(
        display[["Mês", "Clientes", "Emitida (R$)", "Liquidada (R$)", "% Pago", "Comissão 5% (R$)"]],
        column_config={"Mês": st.column_config.DateColumn("Mês", format="MMM/YYYY")},
        use_container_width=True,
        hide_index=True,
    )

# ─────────────────────────────────────────────
# TAB 5 — Por Cliente
# ─────────────────────────────────────────────
with tab5:
    if df_cli.empty:
        no_data()
    else:
        col_search, col_sort = st.columns([3, 1])
        with col_search:
            busca = st.text_input("Buscar cliente", placeholder="Digite parte do nome...")
        with col_sort:
            ordenar_por = st.selectbox(
                "Ordenar por",
                ["Liquidada (R$)", "Emitida (R$)", "Meses faturados", "Primeiro boleto"],
                index=0,
            )

        df_show = df_cli.copy()
        if busca:
            df_show = df_show[df_show["cliente"].str.contains(busca, case=False, na=False)]

        sort_map = {
            "Liquidada (R$)":    "receita_liquidada",
            "Emitida (R$)":      "receita_emitida",
            "Meses faturados":   "meses_faturados",
            "Primeiro boleto":   "primeiro_boleto",
        }
        df_show = df_show.sort_values(sort_map[ordenar_por], ascending=False if ordenar_por != "Primeiro boleto" else True)

        st.caption(f"{len(df_show)} clientes encontrados")

        # Formata para exibição
        disp = df_show.copy()
        disp["primeiro_boleto"]   = disp["primeiro_boleto"].dt.strftime("%m/%Y").fillna("—")
        disp["receita_emitida"]   = disp["receita_emitida"].apply(lambda v: fmt_brl(v, 0))
        disp["receita_liquidada"] = disp["receita_liquidada"].apply(lambda v: fmt_brl(v, 0))
        disp["comissao_5pct"]     = disp["comissao_5pct"].apply(lambda v: fmt_brl(v, 0))
        disp["pct_pago"]          = disp["pct_pago"].apply(lambda v: f"{v:.1f}%")

        disp = disp.rename(columns={
            "cliente":          "Cliente",
            "st_sincro_sac":    "ID",
            "primeiro_boleto":  "1° Boleto",
            "meses_faturados":  "Meses Fat.",
            "receita_emitida":  "Emitida Total (R$)",
            "receita_liquidada":"Liquidada Total (R$)",
            "pct_pago":         "% Pago",
            "comissao_5pct":    "Comissão 5% (R$)",
        })

        st.dataframe(
            disp[["Cliente", "ID", "1° Boleto", "Meses Fat.",
                  "Emitida Total (R$)", "Liquidada Total (R$)", "% Pago", "Comissão 5% (R$)"]],
            use_container_width=True,
            hide_index=True,
        )

# ─────────────────────────────────────────────
# TAB 6 — Detalhe por Mês
# ─────────────────────────────────────────────
with tab6:
    if df_detalhe.empty:
        no_data()
    else:
        # Filtro de mês
        meses_disp = (
            df_detalhe[["mes"]]
            .drop_duplicates()
            .sort_values("mes", ascending=False)
            .assign(label=lambda d: d["mes"].dt.strftime("%b/%Y").str.capitalize())
        )
        meses_list = meses_disp["label"].tolist()
        prev_month_label = (pd.Timestamp.today() - pd.DateOffset(months=1)).strftime("%b/%Y").capitalize()
        default_idx = meses_list.index(prev_month_label) if prev_month_label in meses_list else 0
        mes_sel_label = st.selectbox(
            "Mês",
            options=meses_list,
            index=default_idx,
            key="detalhe_mes",
        )
        mes_sel_ts = meses_disp.loc[meses_disp["label"] == mes_sel_label, "mes"].iloc[0]

        df_mes = df_detalhe[df_detalhe["mes"] == mes_sel_ts].copy()

        # KPIs do mês selecionado
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Igrejas elegíveis", f"{df_mes['elegivel'].sum()}")
        with m2:
            st.metric("Base comissão", f"R$ {fmt_brl(df_mes['liq_comissao'].sum(), 0)}")
        with m3:
            st.metric("Comissão 5%", f"R$ {fmt_brl(df_mes['comissao_5pct'].sum(), 0)}")

        st.divider()

        # Filtro de elegibilidade
        filtro_eleg = st.radio(
            "Exibir",
            ["Todas", "Elegíveis (comissão)", "Fora da janela"],
            index=1,
            horizontal=True,
            key="detalhe_filtro",
        )
        if filtro_eleg == "Elegíveis (comissão)":
            df_mes = df_mes[df_mes["elegivel"]]
        elif filtro_eleg == "Fora da janela":
            df_mes = df_mes[~df_mes["elegivel"]]

        st.caption(f"{len(df_mes)} igrejas")

        # Formata tabela
        disp6 = df_mes.copy()
        disp6["entry_month"] = disp6["entry_month"].dt.strftime("%m/%Y")
        disp6["emitida"]     = disp6["emitida"].apply(lambda v: fmt_brl(v, 0))
        disp6["liquidada"]   = disp6["liquidada"].apply(lambda v: fmt_brl(v, 0))
        disp6["liq_comissao"]  = disp6["liq_comissao"].apply(lambda v: fmt_brl(v, 0))
        disp6["comissao_5pct"] = disp6["comissao_5pct"].apply(lambda v: fmt_brl(v, 0))
        disp6["pct_pago"]    = disp6["pct_pago"].apply(lambda v: f"{v:.1f}%")
        disp6["elegivel"]    = disp6["elegivel"].map({True: "✅", False: "❌"})

        disp6 = disp6.rename(columns={
            "cliente":      "Igreja",
            "id":           "ID",
            "entry_month":  "Entrada",
            "emitida":      "Emitida (R$)",
            "liquidada":    "Liquidada (R$)",
            "pct_pago":     "% Pago",
            "elegivel":     "Comissão?",
            "liq_comissao": "Base Comissão (R$)",
            "comissao_5pct":"Comissão 5% (R$)",
        })

        st.dataframe(
            disp6[["Igreja", "ID", "Entrada", "Emitida (R$)", "Liquidada (R$)",
                   "% Pago", "Comissão?", "Base Comissão (R$)", "Comissão 5% (R$)"]],
            use_container_width=True,
            hide_index=True,
        )
