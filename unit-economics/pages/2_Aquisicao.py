"""
pages/2_🎯_Aquisicao.py
Novos clientes, CAC, Payback e LTV:CAC.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Aquisição | Unit Economics", page_icon="🎯", layout="wide")

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
)

inject_css()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Aquisição <span>CAC & Payback</span></h1>", unsafe_allow_html=True)
with col_period:
    n_months = period_selector("aquisicao")

with st.expander("ℹ️ Como ler esta página"):
    st.markdown("""
**Aquisição** mede o custo e a eficiência de trazer novos clientes — quanto se gasta, quantos chegam e se o investimento se paga.

---

#### Definição de "novo cliente"
Um cliente é contado como novo no mês em que o seu **primeiro produto ativo** no MRR começou (`MIN(dt_inicio_mens)`).
Módulos adicionais (Kids, Jornada, Loja) e itens de Setup e PRO-RATA são ignorados — só o plano base entra na contagem.

> ⚠️ Se um mês aparecer com volume anormalmente alto, pode indicar carga retroativa de dados no MRR — verifique se os clientes têm `dt_cadastro_sac` muito anterior à `dt_inicio_mens`.

---

#### KPIs do topo
| Métrica | O que é | Como é calculado |
|---|---|---|
| **Novos Clientes** | Clientes entrando pela primeira vez | `COUNT(DISTINCT st_sincro_sac)` com `dt_inicio_mens = dt_first` no mês |
| **New Logo MRR** | MRR trazido pelos novos clientes | `SUM(valor_total)` de todos os produtos do cliente no mês de entrada |
| **CAC** | Custo de Aquisição por Cliente | `Total de despesas de aquisição ÷ Novos clientes` do mês |
| **Payback** | Meses para recuperar o CAC | `CAC ÷ ARPU` |
| **LTV:CAC** | Razão entre valor gerado e custo de aquisição | `LTV ÷ CAC`. Meta: ≥ 3x |

---

#### Novos Clientes por Mês
Barras empilhadas por plano + linha de total. A pizza ao lado mostra a distribuição entre planos no último mês selecionado.

#### CAC & Payback por Mês
- **Barra** = custo total de aquisição (despesas liquidadas nos centros de custo abaixo)
- **Linha sólida** = CAC por cliente (eixo direito)
- **Linha pontilhada** = Payback em meses (eixo direito)

#### Composição dos Custos de Aquisição
Despesas liquidadas no mês, agrupadas por tipo:
| Grupo | Centros de custo incluídos |
|---|---|
| Comercial | Field Sales, Inbound, Sales, Outside Sales |
| Marketing | Marketing |
| Eventos & Parceiros | Eventos, Parceiros |
| Outbound | Outbound |

> As despesas vêm de uma planilha no Drive (`despesas_liquidadas`) e são filtradas pelo mês de liquidação (não competência).

#### LTV : CAC
```
ARPU          = MRR início ÷ Clientes ativos
Churn rate    = MRR churned ÷ MRR início  (suavizado: média móvel 3 meses)
LTV           = ARPU ÷ Churn rate suavizado
Payback       = CAC ÷ ARPU
LTV:CAC       = LTV ÷ CAC
```
Cor das barras: 🟢 ≥ 3x · 🟡 ≥ 1x · 🔴 < 1x.
A tabela lateral detalha todos os componentes do último mês.
""")

# ── Carga ─────────────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_wf       = load_mrr_waterfall()
    df_new_plan = load_new_logos_por_plano()
    df_desp     = load_despesas_cac()

_last_closed_month = (pd.Timestamp.now().to_period("M") - 1).to_timestamp()

df_wf_f       = filter_months(df_wf, n_months)
df_new_plan_f = filter_months(df_new_plan, n_months)
df_desp_f     = filter_months(df_desp, n_months)
df_cac        = compute_cac_metrics(df_desp, df_wf)
df_cac_f      = filter_months(df_cac, n_months)

# Remove mês atual (incompleto) — exibe apenas até o mês anterior fechado
df_wf_f       = df_wf_f[df_wf_f["mes"] <= _last_closed_month]
df_new_plan_f = df_new_plan_f[df_new_plan_f["mes"] <= _last_closed_month]
df_desp_f     = df_desp_f[df_desp_f["mes"] <= _last_closed_month]
df_cac_f      = df_cac_f[df_cac_f["mes"] <= _last_closed_month]

# ── KPIs ──────────────────────────────────────────────────────────────────────
st.subheader("Métricas de Aquisição")
k1, k2, k3, k4, k5 = st.columns(5)

new_cl   = last_val(df_wf_f, "new_clients")
new_cl_p = prev_val(df_wf_f, "new_clients")
new_mrr  = last_val(df_wf_f, "new_logo_mrr")
cac_v    = last_val(df_cac_f, "cac")
cac_p    = prev_val(df_cac_f, "cac")
pay_v    = last_val(df_cac_f, "payback_meses")
ltv_cac  = last_val(df_cac_f, "ltv_cac")

with k1:
    st.metric("Novos Clientes", f"{int(new_cl):,}".replace(",", ".") if new_cl else "—",
              delta=delta_str(new_cl, new_cl_p, fmt="+,.0f"))
with k2:
    st.metric("New Logo MRR", f"R$ {fmt_brl(new_mrr)}" if new_mrr else "—")
with k3:
    st.metric("CAC", f"R$ {fmt_brl(cac_v)}" if cac_v else "—",
              delta=delta_str(cac_v, cac_p, fmt="+,.0f", suffix=" R$"),
              delta_color="inverse")
with k4:
    st.metric("Payback", f"{pay_v:.1f} meses" if pay_v else "—")
with k5:
    st.metric("LTV:CAC", f"{ltv_cac:.1f}x" if ltv_cac else "—")

st.divider()

# ── Gráfico 1: Novos clientes por plano ──────────────────────────────────────
st.subheader("Novos Clientes por Mês")

col_a, col_b = st.columns([3, 2])

with col_a:
    if df_new_plan_f.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_new_plan_f)
        fig = go.Figure()
        for plano in ["pro", "lite", "starter", "basic", "filha", "outros"]:
            sub = df_plot[df_plot["plano"] == plano].sort_values("mes")
            if sub.empty:
                continue
            fig.add_bar(
                x=sub["mes_fmt"], y=sub["new_clients"],
                name=PLAN_LABELS.get(plano, plano),
                marker_color=PLAN_COLORS.get(plano, PALETTE[3]),
                hovertemplate=f"<b>{PLAN_LABELS.get(plano, plano)}</b><br>%{{y}} clientes<extra></extra>",
            )
        # Linha com total por mês
        total_por_mes = df_plot.groupby("mes_fmt", sort=False)["new_clients"].sum().reset_index()
        total_por_mes = total_por_mes.set_index("mes_fmt").reindex(x_order).reset_index()
        fig.add_scatter(
            x=total_por_mes["mes_fmt"], y=total_por_mes["new_clients"],
            name="Total", mode="lines+markers",
            line=dict(color=PALETTE[1], width=2),
            marker=dict(size=7),
            hovertemplate="<b>Total</b> %{y} clientes<extra></extra>",
        )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

with col_b:
    # Participação por plano no último mês
    if not df_new_plan_f.empty:
        ultimo_mes = df_new_plan_f["mes"].max()
        df_pie = df_new_plan_f[df_new_plan_f["mes"] == ultimo_mes].copy()
        df_pie = df_pie[df_pie["new_clients"] > 0]
        if not df_pie.empty:
            fig = go.Figure(go.Pie(
                labels=df_pie["plano"].map(PLAN_LABELS),
                values=df_pie["new_clients"],
                hole=0.45,
                marker_colors=[PLAN_COLORS.get(p, PALETTE[3]) for p in df_pie["plano"]],
                textfont=dict(size=12, family="Outfit"),
            ))
            fig.update_traces(
                texttemplate="%{label}<br>%{percent}",
                hovertemplate="<b>%{label}</b><br>%{value} clientes (%{percent})<extra></extra>",
            )
            mes_label = ultimo_mes.strftime("%b/%y").capitalize()
            st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)
            st.caption(f"Distribuição por plano — {mes_label}")

st.divider()

# ── Gráfico 2: CAC + Payback (dual axis) ─────────────────────────────────────
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

# ── Gráfico 3: Breakdown de custos de aquisição ───────────────────────────────
st.subheader("Composição dos Custos de Aquisição")

GRUPO_LABELS = {
    "comercial":        "Comercial",
    "marketing":        "Marketing",
    "eventos_parceiros": "Eventos & Parceiros",
    "outbound":         "Outbound",
}
GRUPO_COLORS = {
    "comercial":        "#6eda2c",
    "marketing":        "#ffffff",
    "eventos_parceiros": "#a0a0a0",
    "outbound":         "#4c4c4c",
}

if df_desp_f.empty:
    no_data("Nenhuma despesa encontrada para os centros de custo de aquisição.")
else:
    df_plot, x_order = mes_fmt_ordered(df_desp_f)
    fig = go.Figure()
    for grupo in ["comercial", "marketing", "eventos_parceiros", "outbound"]:
        sub = df_plot[df_plot["grupo"] == grupo].sort_values("mes")
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["mes_fmt"], y=sub["valor"],
            name=GRUPO_LABELS.get(grupo, grupo),
            marker_color=GRUPO_COLORS.get(grupo, PALETTE[3]),
            hovertemplate=f"<b>{GRUPO_LABELS.get(grupo, grupo)}</b><br>R$ %{{y:,.0f}}<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ── Gráfico 4: LTV:CAC ratio ─────────────────────────────────────────────────
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
        # Linha de referência 3x
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
            "ARPU": f"R$ {fmt_brl(ultimo.get('arpu', 0))}",
            "Churn Rate": f"{ultimo.get('churn_rate', 0)*100:.1f}%",
            "LTV estimado": f"R$ {fmt_brl(ultimo.get('ltv', 0))}",
            "CAC": f"R$ {fmt_brl(ultimo.get('cac', 0))}",
            "LTV:CAC": f"{ultimo.get('ltv_cac', 0):.1f}x",
            "Payback": f"{ultimo.get('payback_meses', 0):.1f} meses",
        }
        for label, valor in metricas.items():
            cols = st.columns([2, 2])
            cols[0].markdown(f"<span style='color:#a0a0a0;font-size:0.85rem;'>{label}</span>",
                             unsafe_allow_html=True)
            cols[1].markdown(f"<span style='font-weight:600;'>{valor}</span>",
                             unsafe_allow_html=True)
