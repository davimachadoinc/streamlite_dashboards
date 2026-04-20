"""
pages/2_🎯_Aquisicao.py
Fechamentos de vendas, comparação fechado vs MRR atual, CAC e Payback.
Fonte principal: Fechamentos_com_ajustes (BQ_BI).
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Aquisição | Unit Economics", layout="wide")

if "auth" in st.secrets and not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado.")
    st.stop()

st.session_state["_page_key"] = "aquisicao"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_mrr_waterfall, load_new_logos_por_plano,
    load_despesas_cac, compute_cac_metrics,
    load_fechamentos_vendas, load_fechamentos_vs_mrr_atual,
)

inject_css()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Aquisição <span>Fechamentos & CAC</span></h1>", unsafe_allow_html=True)
with col_period:
    n_months = period_selector("aquisicao")

with st.expander("ℹ️ Como ler esta página"):
    st.markdown("""
**Aquisição** tem duas visões complementares:

1. **Fechamentos** — o que foi vendido, quando e por quem (fonte: `Fechamentos_com_ajustes`).
2. **Fechado vs Atual** — compara o MRR contratado na venda com o MRR que o cliente paga hoje.
3. **CAC & Payback** — custo de aquisição vs receita gerada.

---

#### Fechamentos
Registra todas as vendas (`first_payment` = data do primeiro boleto pago).
Filtros de canal, produto e vendedor aplicam-se às seções 1 e 2.

#### Fechado vs Atual
| Coluna | Significado |
|---|---|
| **MRR Fechado** | Valor da mensalidade contratada na venda (`value`) |
| **MRR Atual** | MRR ativo do cliente hoje no Superlógica (sem Setup/PRO-RATA) |
| **Delta** | MRR Atual − MRR Fechado |
| **Var%** | (Delta ÷ MRR Fechado) × 100 |

> Delta negativo indica queda de receita em relação ao contrato original (churn parcial, downsell ou saída de módulos).

#### CAC & Payback
Baseado em despesas liquidadas do Google Drive + novos clientes do MRR (waterfall).
""")

# ── Carga ─────────────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_fech    = load_fechamentos_vendas()
    df_vs      = load_fechamentos_vs_mrr_atual()
    df_wf      = load_mrr_waterfall()
    df_desp    = load_despesas_cac()

df_cac = compute_cac_metrics(df_desp, df_wf)

# ── Sidebar — Filtros de Fechamentos ──────────────────────────────────────────
with st.sidebar:
    st.markdown("### Filtros de Fechamento")

    canais = ["Todos"] + sorted(df_fech["channel"].dropna().unique().tolist()) if not df_fech.empty else ["Todos"]
    planos = ["Todos"] + sorted(df_fech["plan"].dropna().unique().tolist()) if not df_fech.empty else ["Todos"]
    vendedores = ["Todos"] + sorted(df_fech["sales_owner"].dropna().unique().tolist()) if not df_fech.empty else ["Todos"]

    sel_canal    = st.selectbox("Canal", canais, key="fech_canal")
    sel_plano    = st.selectbox("Produto / Plano", planos, key="fech_plano")
    sel_vendedor = st.selectbox("Vendedor", vendedores, key="fech_vendedor")


def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if sel_canal != "Todos":
        df = df[df["channel"] == sel_canal]
    if sel_plano != "Todos":
        df = df[df["plan"] == sel_plano]
    if sel_vendedor != "Todos":
        df = df[df["sales_owner"] == sel_vendedor]
    return df


df_fech_f = _apply_filters(filter_months(df_fech, n_months))
df_vs_f   = _apply_filters(filter_months(df_vs,   n_months))
df_wf_f   = filter_months(df_wf, n_months)
df_cac_f  = filter_months(df_cac, n_months)

# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 1 — FECHAMENTOS
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("Fechamentos por Mês")

k1, k2, k3, k4, k5 = st.columns(5)

total_fech  = len(df_fech_f)
mrr_total   = df_fech_f["mrr_fechado"].sum() if not df_fech_f.empty else 0
fyv_total   = df_fech_f["FYV"].sum()         if not df_fech_f.empty else 0
ticket_med  = mrr_total / total_fech          if total_fech > 0 else 0
novos       = int(df_fech_f["new_deal"].sum()) if not df_fech_f.empty and "new_deal" in df_fech_f else 0
upsells     = int(df_fech_f["upsell"].sum())   if not df_fech_f.empty and "upsell" in df_fech_f else 0

with k1:
    st.metric("Total Fechamentos", f"{total_fech:,}".replace(",", "."))
with k2:
    st.metric("Novos / Upsell", f"{novos} / {upsells}")
with k3:
    st.metric("MRR Fechado", f"R$ {fmt_brl(mrr_total)}")
with k4:
    st.metric("Ticket Médio (MRR)", f"R$ {fmt_brl(ticket_med)}" if ticket_med else "—")
with k5:
    st.metric("FYV Total", f"R$ {fmt_brl(fyv_total)}")

st.divider()

# ── Gráfico: Fechamentos por mês (new_deal vs upsell) ─────────────────────────
col_a, col_b = st.columns([3, 2])

with col_a:
    if df_fech_f.empty:
        no_data()
    else:
        df_plot = (
            df_fech_f.groupby(["mes", "new_deal", "upsell"], as_index=False)
            .agg(qtd=("mrr_fechado", "count"), mrr=("mrr_fechado", "sum"))
        )
        # Reagrupa por mes + tipo
        df_new = (
            df_fech_f[df_fech_f["new_deal"] == True]
            .groupby("mes", as_index=False)
            .agg(qtd=("mrr_fechado", "count"), mrr=("mrr_fechado", "sum"))
        )
        df_ups = (
            df_fech_f[df_fech_f["upsell"] == True]
            .groupby("mes", as_index=False)
            .agg(qtd=("mrr_fechado", "count"), mrr=("mrr_fechado", "sum"))
        )
        # Base para eixo X ordenado
        df_base = df_fech_f.groupby("mes", as_index=False)["mrr_fechado"].sum()
        df_base, x_order = mes_fmt_ordered(df_base)

        def _enrich(df_agg):
            df_agg, _ = mes_fmt_ordered(df_agg)
            return df_agg

        df_new = _enrich(df_new)
        df_ups = _enrich(df_ups)

        fig = go.Figure()
        fig.add_bar(
            x=df_new["mes_fmt"], y=df_new["mrr"],
            name="New Logo",
            marker_color=PALETTE[0],
            customdata=df_new["qtd"],
            hovertemplate="<b>New Logo</b><br>R$ %{y:,.0f} | %{customdata} fechamentos<extra></extra>",
        )
        fig.add_bar(
            x=df_ups["mes_fmt"], y=df_ups["mrr"],
            name="Upsell",
            marker_color=PALETTE[3],
            customdata=df_ups["qtd"],
            hovertemplate="<b>Upsell</b><br>R$ %{y:,.0f} | %{customdata} fechamentos<extra></extra>",
        )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

with col_b:
    # Pizza por canal no período selecionado
    if not df_fech_f.empty:
        df_canal = (
            df_fech_f.groupby("channel", as_index=False)
            .agg(mrr=("mrr_fechado", "sum"), qtd=("mrr_fechado", "count"))
            .sort_values("mrr", ascending=False)
        )
        df_canal = df_canal[df_canal["mrr"] > 0]
        if not df_canal.empty:
            canal_colors = [PALETTE[i % len(PALETTE)] for i in range(len(df_canal))]
            fig = go.Figure(go.Pie(
                labels=df_canal["channel"].fillna("—"),
                values=df_canal["mrr"],
                hole=0.45,
                marker_colors=canal_colors,
                textfont=dict(size=11, family="Outfit"),
            ))
            fig.update_traces(
                texttemplate="%{label}<br>%{percent}",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.0f} (%{percent})<extra></extra>",
            )
            st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)
            st.caption("MRR fechado por canal no período")

# ── Gráfico: MRR fechado por vendedor (barras horizontais) ───────────────────
if not df_fech_f.empty:
    with st.expander("📊 MRR Fechado por Vendedor"):
        df_vend = (
            df_fech_f.groupby("sales_owner", as_index=False)
            .agg(mrr=("mrr_fechado", "sum"), qtd=("mrr_fechado", "count"))
            .sort_values("mrr", ascending=True)
        )
        df_vend = df_vend[df_vend["mrr"] > 0].tail(20)
        fig = go.Figure()
        fig.add_bar(
            x=df_vend["mrr"],
            y=df_vend["sales_owner"].fillna("—"),
            orientation="h",
            marker_color=PALETTE[0],
            customdata=df_vend["qtd"],
            hovertemplate="<b>%{y}</b><br>R$ %{x:,.0f} | %{customdata} fechamentos<extra></extra>",
            text=df_vend["mrr"].apply(lambda v: f"R$ {fmt_brl(v)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
        )
        fig.update_layout(showlegend=False, yaxis=dict(type="category"))
        st.plotly_chart(chart_layout(fig, height=max(300, len(df_vend) * 28)), use_container_width=True)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2 — FECHADO vs MRR ATUAL
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("Fechado vs MRR Atual")

if df_vs_f.empty:
    no_data("Nenhum fechamento encontrado com os filtros selecionados.")
else:
    # KPIs resumo
    total_fech_v   = df_vs_f["mrr_fechado"].sum()
    total_atual_v  = df_vs_f["mrr_atual"].sum()
    total_delta_v  = df_vs_f["delta"].sum()
    pct_delta      = total_delta_v / total_fech_v * 100 if total_fech_v > 0 else 0

    kv1, kv2, kv3, kv4 = st.columns(4)
    with kv1:
        st.metric("MRR Total Fechado", f"R$ {fmt_brl(total_fech_v)}")
    with kv2:
        st.metric("MRR Total Atual", f"R$ {fmt_brl(total_atual_v)}")
    with kv3:
        color = "normal" if total_delta_v >= 0 else "inverse"
        st.metric("Delta Total", f"R$ {fmt_brl(total_delta_v, decimals=0)}",
                  delta_color=color)
    with kv4:
        st.metric("Variação Média", f"{pct_delta:+.1f}%")

    # Tabela comparativa
    df_tab = df_vs_f[[
        "company_name", "channel", "plan", "sales_owner",
        "first_payment", "mrr_fechado", "mrr_atual", "delta", "variacao_pct",
    ]].copy()
    df_tab = df_tab.sort_values("delta")
    df_tab = df_tab.rename(columns={
        "company_name":  "Cliente",
        "channel":       "Canal",
        "plan":          "Plano",
        "sales_owner":   "Vendedor",
        "first_payment": "Data Fechamento",
        "mrr_fechado":   "MRR Fechado",
        "mrr_atual":     "MRR Atual",
        "delta":         "Delta",
        "variacao_pct":  "Var%",
    })
    df_tab["Data Fechamento"] = df_tab["Data Fechamento"].dt.strftime("%d/%m/%Y")

    currency_cols = ["MRR Fechado", "MRR Atual", "Delta"]
    st.dataframe(
        df_tab,
        use_container_width=True,
        hide_index=True,
        column_config={
            **{c: st.column_config.NumberColumn(format="R$ %,.0f") for c in currency_cols},
            "Var%": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )

    # Gráfico: distribuição de delta (histograma)
    with st.expander("📊 Distribuição do Delta (Fechado → Atual)"):
        df_hist = df_vs_f[df_vs_f["variacao_pct"].notna()].copy()
        if not df_hist.empty:
            bins = [-float("inf"), -50, -20, -5, 5, 20, 50, float("inf")]
            labels = ["< -50%", "-50 a -20%", "-20 a -5%", "±5%", "+5 a +20%", "+20 a +50%", "> +50%"]
            df_hist["faixa_delta"] = pd.cut(df_hist["variacao_pct"], bins=bins, labels=labels)
            dist = df_hist.groupby("faixa_delta", observed=True).agg(
                qtd=("variacao_pct", "count"),
                mrr_delta=("delta", "sum"),
            ).reset_index()
            bar_colors = [
                PALETTE[9] if "−" in str(l) or l.startswith("<") or l.startswith("-")
                else (PALETTE[3] if l == "±5%" else PALETTE[0])
                for l in dist["faixa_delta"].astype(str)
            ]
            fig = go.Figure()
            fig.add_bar(
                x=dist["faixa_delta"].astype(str),
                y=dist["qtd"],
                marker_color=bar_colors,
                customdata=dist["mrr_delta"],
                hovertemplate="<b>%{x}</b><br>%{y} clientes<br>Delta total: R$ %{customdata:,.0f}<extra></extra>",
                text=dist["qtd"],
                textposition="outside",
                textfont=dict(size=11, color="#a0a0a0"),
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(chart_layout(fig, height=300), use_container_width=True)

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 3 — CAC & PAYBACK
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("CAC & Payback por Mês")

if df_cac_f.empty:
    no_data("Dados de despesas ou novos clientes insuficientes para calcular CAC.")
else:
    df_plot, x_order = mes_fmt_ordered(df_cac_f)
    fig = go.Figure()
    fig.add_bar(
        x=df_plot["mes_fmt"], y=df_plot["total_cac"],
        name="Custo total de aquisição", marker_color=PALETTE[4],
        opacity=0.8,
        hovertemplate="<b>Custo total</b> R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=df_plot["mes_fmt"], y=df_plot["cac"],
        name="CAC (R$/cliente)", mode="lines+markers",
        line=dict(color=PALETTE[0], width=2.5), marker=dict(size=7),
        yaxis="y2",
        hovertemplate="<b>CAC</b> R$ %{y:,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=df_plot["mes_fmt"], y=df_plot["payback_meses"],
        name="Payback (meses)", mode="lines+markers",
        line=dict(color=PALETTE[1], width=2, dash="dot"), marker=dict(size=6),
        yaxis="y2",
        hovertemplate="<b>Payback</b> %{y:.1f} meses<extra></extra>",
    )
    fig.update_layout(
        yaxis2=dict(overlaying="y", side="right", showgrid=False, color=PALETTE[0]),
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=380, legend_bottom=True), use_container_width=True)

st.divider()

# ── LTV:CAC ───────────────────────────────────────────────────────────────────
st.subheader("LTV : CAC")

col_ltv, col_tab = st.columns([3, 2])

with col_ltv:
    if df_cac_f.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_cac_f)
        fig = go.Figure()
        fig.add_bar(
            x=df_plot["mes_fmt"], y=df_plot["ltv_cac"],
            name="LTV:CAC",
            marker_color=[PALETTE[0] if v >= 3 else (PALETTE[3] if v >= 1 else PALETTE[9])
                          for v in df_plot["ltv_cac"].fillna(0)],
            text=df_plot["ltv_cac"].apply(lambda v: f"{v:.1f}x" if pd.notna(v) else "—"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
            hovertemplate="<b>LTV:CAC</b> %{y:.1f}x<extra></extra>",
        )
        fig.add_hline(y=3, line_dash="dot", line_color=PALETTE[6],
                      annotation_text="Meta 3x", annotation_position="right")
        fig.update_layout(
            showlegend=False,
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=340), use_container_width=True)

with col_tab:
    if not df_cac_f.empty:
        ultimo = df_cac_f.sort_values("mes").iloc[-1]
        st.markdown("#### Último mês")
        metricas = {
            "ARPU":         f"R$ {fmt_brl(ultimo.get('arpu', 0))}",
            "Churn Rate":   f"{ultimo.get('churn_rate', 0)*100:.1f}%",
            "LTV estimado": f"R$ {fmt_brl(ultimo.get('ltv', 0))}",
            "CAC":          f"R$ {fmt_brl(ultimo.get('cac', 0))}",
            "LTV:CAC":      f"{ultimo.get('ltv_cac', 0):.1f}x",
            "Payback":      f"{ultimo.get('payback_meses', 0):.1f} meses",
        }
        for label, valor in metricas.items():
            cols = st.columns([2, 2])
            cols[0].markdown(f"<span style='color:#a0a0a0;font-size:0.85rem;'>{label}</span>",
                             unsafe_allow_html=True)
            cols[1].markdown(f"<span style='font-weight:600;'>{valor}</span>",
                             unsafe_allow_html=True)
