"""
pages/4_🔄_Retencao.py
Churn rate por plano, MRR perdido, LTV por plano.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Retenção | Unit Economics", layout="wide")

if "auth" in st.secrets and not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado.")
    st.stop()

st.session_state["_page_key"] = "retencao"

from utils.style import inject_css
from utils.data import (
    PALETTE, PLAN_LABELS, PLAN_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_mrr_waterfall, load_churn_por_plano, load_base_ativa_por_plano,
)

inject_css()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Retenção <span>Churn & LTV</span></h1>", unsafe_allow_html=True)
with col_period:
    n_months = period_selector("retencao")

with st.expander("ℹ️ Como ler esta página"):
    st.markdown("""
**Retenção** mede quanto da base de clientes e de MRR está sendo perdido a cada mês — e quanto vale um cliente enquanto permanece ativo.

---

#### Definição de Churn
Um cliente é contabilizado como churn quando:
1. Tem `dt_fim_mens IS NOT NULL` no MRR, **ou**
2. Tem `dt_desativacao_sac IS NOT NULL` na base de clientes (mesmo sem `dt_fim_mens` — casos de encerramento manual)

Itens excluídos do churn (não representam cancelamento real): Setup, PRO-RATA, renovações (produto que encerrou no último dia do mês e reiniciou no mês seguinte).

---

#### KPIs do topo
| Métrica | O que é | Como é calculado |
|---|---|---|
| **Churn Rate (clientes)** | % de clientes perdidos no mês | `Clientes churned ÷ Clientes ativos no início do mês × 100` |
| **Churn Rate (MRR)** | % de MRR perdido no mês | `MRR churned ÷ MRR ativo no início do mês × 100` |
| **MRR Churned** | Receita absoluta perdida | Soma do `valor_total` dos produtos cancelados no mês |
| **Clientes Churned** | Quantidade de clientes que saíram | `COUNT(DISTINCT st_sincro_sac)` com churn no mês |
| **LTV Médio (base)** | Valor vitalício médio ponderado por clientes ativos | `ARPU ÷ Churn Rate` — média dos últimos 3 meses, ponderada por tamanho do plano |

> ⚠️ Churn Rate (clientes) e Churn Rate (MRR) costumam divergir: clientes menores churnam mais em quantidade, mas o impacto em MRR é menor. Se o MRR churn for sistematicamente menor que o de clientes, é sinal de que quem sai é a base mais barata.

---

#### Churn Rate Mensal
- **Gráfico esquerdo** — evolução temporal do churn consolidado (clientes e MRR)
- **Gráfico direito** — comparativo entre planos no último mês (barras horizontais)

#### MRR Churned por Plano
Barras empilhadas mostrando a composição do MRR perdido por plano ao longo do tempo. Útil para identificar qual segmento está churning mais em termos de receita.

#### LTV por Plano
```
ARPU por plano   = MRR ativo do plano ÷ Clientes ativos do plano
Churn rate       = Clientes churned ÷ Clientes ativos  (média últimos 3 meses)
LTV              = ARPU ÷ Churn rate mensal
```
Usa a média dos últimos 3 meses para suavizar variações pontuais.
- **Gráfico LTV** — valor vitalício estimado por plano
- **Gráfico ARPU** — ticket médio por plano (ao lado)

> O LTV é uma estimativa simplificada. Pressupõe churn constante e ARPU estável. Em planos com baixo churn, o LTV pode parecer muito alto — interprete com cautela.

#### Tabela LTV por Plano
Detalha todos os componentes usados no cálculo: clientes ativos, MRR ativo, ARPU, Churn Rate e LTV estimado.
""")

# ── Carga ─────────────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_wf    = load_mrr_waterfall()
    df_churn = load_churn_por_plano()
    df_base  = load_base_ativa_por_plano()

_last_closed_month = (pd.Timestamp.now().to_period("M") - 1).to_timestamp()

df_wf_f    = filter_months(df_wf, n_months)
df_churn_f = filter_months(df_churn, n_months)
df_base_f  = filter_months(df_base, n_months)

# Remove mês atual (incompleto) — exibe apenas até o mês anterior fechado
df_wf_f    = df_wf_f[df_wf_f["mes"] <= _last_closed_month]
df_churn_f = df_churn_f[df_churn_f["mes"] <= _last_closed_month]
df_base_f  = df_base_f[df_base_f["mes"] <= _last_closed_month]

# ── Churn rate consolidado por mês (join churn + base) ───────────────────────
df_churn_agg = df_churn_f.groupby("mes", as_index=False).agg(
    churned_clients=("churned_clients", "sum"),
    churned_mrr=("churned_mrr", "sum"),
)
df_base_agg = df_base_f.groupby("mes", as_index=False).agg(
    clientes_ativos=("clientes_ativos", "sum"),
    mrr_ativo=("mrr_ativo", "sum"),
)
df_churn_rate = df_churn_agg.merge(df_base_agg, on="mes", how="left")
df_churn_rate["churn_rate_cl"] = (
    df_churn_rate["churned_clients"] / df_churn_rate["clientes_ativos"].replace(0, pd.NA) * 100
).round(2)
df_churn_rate["churn_rate_mrr"] = (
    df_churn_rate["churned_mrr"] / df_churn_rate["mrr_ativo"].replace(0, pd.NA) * 100
).round(2)

# ── LTV por plano (média dos últimos 3 meses disponíveis) ────────────────────
def _compute_ltv_por_plano(
    df_churn: pd.DataFrame, df_base: pd.DataFrame
) -> pd.DataFrame:
    """LTV = ARPU_plano / churn_rate_plano (média 3 meses)."""
    if df_churn.empty or df_base.empty:
        return pd.DataFrame()

    # Pega os últimos 3 meses com dados
    ultimos = sorted(df_base["mes"].unique())[-3:]
    df_ch = df_churn[df_churn["mes"].isin(ultimos)]
    df_ba = df_base[df_base["mes"].isin(ultimos)]

    ch_avg = df_ch.groupby("plano").agg(
        churned_clients=("churned_clients", "mean"),
        churned_mrr=("churned_mrr", "mean"),
    ).reset_index()
    ba_avg = df_ba.groupby("plano").agg(
        clientes_ativos=("clientes_ativos", "mean"),
        mrr_ativo=("mrr_ativo", "mean"),
    ).reset_index()

    df_ltv = ba_avg.merge(ch_avg, on="plano", how="left").fillna(0)
    df_ltv["arpu"] = (df_ltv["mrr_ativo"] / df_ltv["clientes_ativos"].replace(0, pd.NA)).round(2)
    df_ltv["churn_rate"] = (
        df_ltv["churned_clients"] / df_ltv["clientes_ativos"].replace(0, pd.NA)
    ).clip(lower=0.001)
    df_ltv["ltv"] = (df_ltv["arpu"] / df_ltv["churn_rate"]).round(0)
    return df_ltv[df_ltv["ltv"].notna() & (df_ltv["ltv"] > 0)]

df_ltv = _compute_ltv_por_plano(df_churn_f, df_base_f)

# ── KPIs ──────────────────────────────────────────────────────────────────────
st.subheader("Métricas de Retenção")
k1, k2, k3, k4, k5 = st.columns(5)

churn_cl_v  = last_val(df_churn_rate, "churn_rate_cl")
churn_cl_p  = prev_val(df_churn_rate, "churn_rate_cl")
churn_mrr_v = last_val(df_churn_rate, "churn_rate_mrr")
churn_mrr_p = prev_val(df_churn_rate, "churn_rate_mrr")
churned_mrr = last_val(df_churn_rate, "churned_mrr")
churned_cl  = last_val(df_churn_rate, "churned_clients")

# LTV médio ponderado por clientes
if not df_ltv.empty:
    ltv_medio = (df_ltv["ltv"] * df_ltv["clientes_ativos"]).sum() / df_ltv["clientes_ativos"].sum()
else:
    ltv_medio = None

with k1:
    st.metric("Churn Rate (clientes)", f"{churn_cl_v:.2f}%" if churn_cl_v else "—",
              delta=delta_str(churn_cl_v, churn_cl_p, fmt="+.2f", suffix=" pp"),
              delta_color="inverse")
with k2:
    st.metric("Churn Rate (MRR)", f"{churn_mrr_v:.2f}%" if churn_mrr_v else "—",
              delta=delta_str(churn_mrr_v, churn_mrr_p, fmt="+.2f", suffix=" pp"),
              delta_color="inverse")
with k3:
    st.metric("MRR Churned", f"R$ {fmt_brl(churned_mrr)}" if churned_mrr else "—")
with k4:
    st.metric("Clientes Churned", f"{int(churned_cl):,}".replace(",", ".") if churned_cl else "—")
with k5:
    st.metric("LTV Médio (base)", f"R$ {fmt_brl(ltv_medio)}" if ltv_medio else "—")

st.divider()

# ── Gráfico 1: Churn rate % ao longo do tempo ────────────────────────────────
st.subheader("Churn Rate Mensal")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("##### Por clientes e MRR (consolidado)")
    if df_churn_rate.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_churn_rate)
        fig = go.Figure()
        fig.add_scatter(
            x=df_plot["mes_fmt"], y=df_plot["churn_rate_cl"],
            name="Churn Clientes %", mode="lines+markers",
            line=dict(color=PALETTE[9], width=2.5), marker=dict(size=7),
            hovertemplate="<b>Churn clientes</b> %{y:.2f}%<extra></extra>",
        )
        fig.add_scatter(
            x=df_plot["mes_fmt"], y=df_plot["churn_rate_mrr"],
            name="Churn MRR %", mode="lines+markers",
            line=dict(color=PALETTE[3], width=2, dash="dot"), marker=dict(size=6),
            hovertemplate="<b>Churn MRR</b> %{y:.2f}%<extra></extra>",
        )
        fig.update_layout(
            yaxis=dict(ticksuffix="%"),
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=320, legend_bottom=True), use_container_width=True)

with col_b:
    st.markdown("##### Churn Rate por Plano (último mês)")
    if df_churn_f.empty or df_base_f.empty:
        no_data()
    else:
        ultimo_mes = df_base_f["mes"].max()
        ch_last = df_churn_f[df_churn_f["mes"] == ultimo_mes].copy()
        ba_last = df_base_f[df_base_f["mes"] == ultimo_mes].copy()
        merged = ba_last.merge(ch_last, on="plano", how="left").fillna(0)
        merged["churn_rate"] = (
            merged["churned_clients"] / merged["clientes_ativos"].replace(0, pd.NA) * 100
        ).round(2)
        merged = merged[merged["clientes_ativos"] > 0].sort_values("churn_rate", ascending=True)

        fig = go.Figure()
        fig.add_bar(
            x=merged["churn_rate"],
            y=merged["plano"].map(PLAN_LABELS),
            orientation="h",
            marker_color=[PLAN_COLORS.get(p, PALETTE[3]) for p in merged["plano"]],
            text=merged["churn_rate"].apply(lambda v: f"{v:.2f}%"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
            hovertemplate="<b>%{y}</b><br>Churn: %{x:.2f}%<extra></extra>",
        )
        fig.update_layout(
            showlegend=False,
            xaxis=dict(ticksuffix="%", showgrid=True, gridcolor="#292929"),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

st.divider()

# ── Gráfico 2: MRR Churned por plano ─────────────────────────────────────────
st.subheader("MRR Churned por Plano")

if df_churn_f.empty:
    no_data()
else:
    df_plot, x_order = mes_fmt_ordered(df_churn_f)
    fig = go.Figure()
    for plano in ["pro", "lite", "starter", "basic", "filha", "squad", "outros"]:
        sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["mes_fmt"], y=sub["churned_mrr"],
            name=PLAN_LABELS.get(plano, plano),
            marker_color=PLAN_COLORS.get(plano, PALETTE[3]),
            hovertemplate=f"<b>{PLAN_LABELS.get(plano, plano)}</b><br>R$ %{{y:,.0f}} | %{{customdata}} clientes<extra></extra>",
            customdata=sub["churned_clients"],
        )
    fig.update_layout(
        barmode="stack",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ── Gráfico 3: LTV por plano ──────────────────────────────────────────────────
st.subheader("LTV por Plano (média últimos 3 meses)")
st.caption("LTV = ARPU ÷ Churn Rate mensal. Estimativa baseada na base ativa e nas desativações recentes.")

col_ltv, col_arpu = st.columns(2)

with col_ltv:
    if df_ltv.empty:
        no_data()
    else:
        df_plot = df_ltv[df_ltv["plano"].isin(["pro", "lite", "starter", "basic"])].sort_values("ltv")
        fig = go.Figure()
        fig.add_bar(
            x=df_plot["ltv"],
            y=df_plot["plano"].map(PLAN_LABELS),
            orientation="h",
            marker_color=[PLAN_COLORS.get(p, PALETTE[3]) for p in df_plot["plano"]],
            text=df_plot["ltv"].apply(lambda v: f"R$ {fmt_brl(v)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
            hovertemplate="<b>%{y}</b><br>LTV: R$ %{x:,.0f}<extra></extra>",
        )
        fig.update_layout(showlegend=False, xaxis=dict(showgrid=True, gridcolor="#292929"),
                          yaxis=dict(showgrid=False))
        st.plotly_chart(chart_layout(fig, height=300), use_container_width=True)

with col_arpu:
    if df_ltv.empty:
        no_data()
    else:
        df_plot = df_ltv[df_ltv["plano"].isin(["pro", "lite", "starter", "basic"])].sort_values("arpu")
        fig = go.Figure()
        fig.add_bar(
            x=df_plot["arpu"],
            y=df_plot["plano"].map(PLAN_LABELS),
            orientation="h",
            marker_color=[PLAN_COLORS.get(p, PALETTE[3]) for p in df_plot["plano"]],
            text=df_plot["arpu"].apply(lambda v: f"R$ {fmt_brl(v)}"),
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
            hovertemplate="<b>%{y}</b><br>ARPU: R$ %{x:,.0f}<extra></extra>",
        )
        fig.update_layout(showlegend=False, xaxis=dict(showgrid=True, gridcolor="#292929"),
                          yaxis=dict(showgrid=False))
        st.plotly_chart(chart_layout(fig, height=300), use_container_width=True)
    st.caption("ARPU por plano (média últimos 3 meses)")

st.divider()

# ── Tabela LTV completa ───────────────────────────────────────────────────────
with st.expander("📋 Tabela LTV por Plano"):
    if df_ltv.empty:
        no_data()
    else:
        df_show = df_ltv.copy()
        df_show["plano"] = df_show["plano"].map(PLAN_LABELS)
        df_show = df_show.rename(columns={
            "plano":           "Plano",
            "clientes_ativos": "Clientes Ativos",
            "mrr_ativo":       "MRR Ativo",
            "arpu":            "ARPU",
            "churn_rate":      "Churn Rate",
            "ltv":             "LTV Estimado",
        })
        df_show["Churn Rate"] = df_show["Churn Rate"].apply(lambda v: f"{v*100:.2f}%")
        st.dataframe(
            df_show[["Plano", "Clientes Ativos", "MRR Ativo", "ARPU", "Churn Rate", "LTV Estimado"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "MRR Ativo":    st.column_config.NumberColumn(format="R$ %,.0f"),
                "ARPU":         st.column_config.NumberColumn(format="R$ %,.0f"),
                "LTV Estimado": st.column_config.NumberColumn(format="R$ %,.0f"),
            },
        )
