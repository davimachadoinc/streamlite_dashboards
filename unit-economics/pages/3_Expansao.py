"""
pages/3_📈_Expansao.py
Expansion MRR, upsells por módulo, detalhamento de upgrades, attach rate e timing.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np

st.set_page_config(page_title="Expansão | Unit Economics", layout="wide")

if "auth" in st.secrets and not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado.")
    st.stop()

st.session_state["_page_key"] = "expansao"

from utils.style import inject_css
from utils.data import (
    PALETTE, MODULE_LABELS, MODULE_COLORS,
    chart_layout, mes_fmt_ordered, period_selector, filter_months,
    last_val, prev_val, delta_str, fmt_brl, no_data,
    load_mrr_waterfall, load_expansion_por_modulo,
    load_module_attach_rate, load_upsell_timing,
    load_expansion_detalhado, load_upgrade_detalhado,
)

inject_css()

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_period = st.columns([8, 2], vertical_alignment="bottom")
with col_title:
    st.markdown("<h1>Expansão <span>Upsell & Módulos</span></h1>", unsafe_allow_html=True)
with col_period:
    n_months = period_selector("expansao")

with st.expander("ℹ️ Como ler esta página"):
    st.markdown("""
**Expansão** mede o crescimento gerado dentro da base existente — clientes que contrataram módulos adicionais ou fizeram upgrade de plano.

---

#### Definição de Expansion
Um evento é classificado como expansion quando um cliente já existente (`dt_inicio_mens > dt_first`) adiciona um novo produto ao MRR.
Renovações são excluídas: se um produto encerrou no último dia do mês X e reiniciou no mês X+1 com a mesma descrição, é renovação — não expansion.

---

#### KPIs do topo
| Métrica | O que é |
|---|---|
| **Expansion MRR** | MRR adicional de clientes existentes |
| **Clientes Expandidos** | Clientes com ao menos um upsell no mês |
| **Attach Kids / Jornada** | % da base ativa com o módulo |
| **Tempo médio ao upsell** | Dias entre entrada do cliente e primeiro upsell |

---

#### Detalhamento de Upgrades de Plano
Para os eventos de expansion classificados como "Upgrade de Plano", identifica o que mudou:
- **Mudança de Plano** — ex: Lite → Pro, Starter → Lite
- **Mudança de Faixa** — mesmo plano, faixa de membros maior (ex: Lite 1-100 → Lite 101-300)
- **Novo sem anterior** — novo plano contratado sem plano anterior identificável no período

A lógica compara o plano/faixa que o cliente tinha até 60 dias antes com o novo plano ativado.

#### Attach Rate por Módulo
`Attach Rate = Clientes com módulo ativo ÷ Total de clientes ativos`

#### Distribuição — Dias até Primeiro Upsell
Histograma mostrando quanto tempo os clientes levam para o primeiro upsell após a entrada.
""")

# ── Carga ─────────────────────────────────────────────────────────────────────
with st.spinner("Carregando dados..."):
    df_wf      = load_mrr_waterfall()
    df_exp_mod = load_expansion_por_modulo()
    df_attach  = load_module_attach_rate()
    df_timing  = load_upsell_timing()
    df_exp_det = load_expansion_detalhado()
    df_upgrade = load_upgrade_detalhado()

df_wf_f      = filter_months(df_wf, n_months)
df_exp_mod_f = filter_months(df_exp_mod, n_months)
df_attach_f  = filter_months(df_attach, n_months)
df_upgrade_f = filter_months(df_upgrade, n_months)
df_exp_det_f = df_exp_det.copy()

# ── KPIs ──────────────────────────────────────────────────────────────────────
st.subheader("Métricas de Expansão")
k1, k2, k3, k4, k5 = st.columns(5)

exp_mrr   = last_val(df_wf_f, "expansion_mrr")
exp_mrr_p = prev_val(df_wf_f, "expansion_mrr")
exp_cl    = last_val(df_wf_f, "expanded_clients")
exp_cl_p  = prev_val(df_wf_f, "expanded_clients")

if not df_attach_f.empty:
    ultimo_mes = df_attach_f["mes"].max()
    ar_last = df_attach_f[df_attach_f["mes"] == ultimo_mes].set_index("modulo")["attach_rate"]
else:
    ar_last = pd.Series(dtype=float)

if not df_timing.empty:
    avg_dias = int(np.average(df_timing["dias_ate_upsell"], weights=df_timing["clientes"]))
else:
    avg_dias = None

with k1:
    st.metric("Expansion MRR", f"R$ {fmt_brl(exp_mrr)}" if exp_mrr else "—",
              delta=delta_str(exp_mrr, exp_mrr_p, fmt="+,.0f", suffix=" R$"))
with k2:
    st.metric("Clientes Expandidos", f"{int(exp_cl):,}".replace(",", ".") if exp_cl else "—",
              delta=delta_str(exp_cl, exp_cl_p, fmt="+,.0f"))
with k3:
    kids_rate = ar_last.get("kids", None)
    st.metric("Attach Kids", f"{kids_rate:.1f}%" if kids_rate else "—")
with k4:
    jornada_rate = ar_last.get("jornada", None)
    st.metric("Attach Jornada", f"{jornada_rate:.1f}%" if jornada_rate else "—")
with k5:
    st.metric("Tempo médio ao upsell", f"{avg_dias} dias" if avg_dias else "—")

st.divider()

# ── Gráfico 1: Expansion MRR por tipo ────────────────────────────────────────
st.subheader("Expansion MRR por Tipo")

col_a, col_b = st.columns([3, 2])

with col_a:
    if df_exp_mod_f.empty:
        no_data()
    else:
        df_plot, x_order = mes_fmt_ordered(df_exp_mod_f)
        fig = go.Figure()
        for tipo in ["kids", "jornada", "loja_inteligente", "totem", "upgrade_plano"]:
            sub = df_plot[df_plot["tipo"] == tipo].sort_values("mes")
            if sub.empty:
                continue
            fig.add_bar(
                x=sub["mes_fmt"], y=sub["expansion_mrr"],
                name=MODULE_LABELS.get(tipo, tipo),
                marker_color=MODULE_COLORS.get(tipo, PALETTE[3]),
                hovertemplate=f"<b>{MODULE_LABELS.get(tipo, tipo)}</b><br>R$ %{{y:,.0f}} | %{{customdata}} clientes<extra></extra>",
                customdata=sub["clientes"],
            )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

with col_b:
    if not df_exp_mod_f.empty:
        ultimo_mes = df_exp_mod_f["mes"].max()
        df_pie = df_exp_mod_f[df_exp_mod_f["mes"] == ultimo_mes].copy()
        df_pie = df_pie[df_pie["expansion_mrr"] > 0]
        if not df_pie.empty:
            fig = go.Figure(go.Pie(
                labels=df_pie["tipo"].map(MODULE_LABELS),
                values=df_pie["expansion_mrr"],
                hole=0.45,
                marker_colors=[MODULE_COLORS.get(t, PALETTE[3]) for t in df_pie["tipo"]],
                textfont=dict(size=12, family="Outfit"),
            ))
            fig.update_traces(
                texttemplate="%{label}<br>%{percent}",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.0f} (%{percent})<extra></extra>",
            )
            mes_label = ultimo_mes.strftime("%b/%y").capitalize()
            st.plotly_chart(chart_layout(fig, height=360), use_container_width=True)
            st.caption(f"Composição — {mes_label}")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO: DETALHAMENTO DE UPGRADES DE PLANO
# ═══════════════════════════════════════════════════════════════════════════════
st.subheader("Detalhamento de Upgrades de Plano")

TIPO_UPGRADE_LABELS = {
    "mudanca_plano":     "Mudança de Plano",
    "mudanca_faixa":     "Mudança de Faixa",
    "novo_sem_anterior": "Novo (sem anterior)",
    "outro":             "Outro",
}
TIPO_UPGRADE_COLORS = {
    "mudanca_plano":     PALETTE[0],
    "mudanca_faixa":     PALETTE[1],
    "novo_sem_anterior": PALETTE[3],
    "outro":             PALETTE[4],
}

PLAN_LABELS_EXT = {
    "pro":          "PRO",
    "lite":         "LITE",
    "starter":      "STARTER",
    "basic":        "BASIC",
    "filha":        "FILHA",
    "squad":        "Squad",
    "outros":       "Outros",
    "sem_anterior": "—",
}

if df_upgrade_f.empty:
    no_data("Nenhum upgrade de plano encontrado no período.")
else:
    # KPIs de upgrade
    n_upgrades     = len(df_upgrade_f)
    mrr_upgrades   = df_upgrade_f["delta_mrr"].sum()
    n_plan_change  = (df_upgrade_f["tipo_upgrade"] == "mudanca_plano").sum()
    n_faixa_change = (df_upgrade_f["tipo_upgrade"] == "mudanca_faixa").sum()

    uk1, uk2, uk3, uk4 = st.columns(4)
    with uk1:
        st.metric("Total Upgrades", f"{n_upgrades:,}".replace(",", "."))
    with uk2:
        st.metric("Mudanças de Plano", f"{n_plan_change:,}".replace(",", "."))
    with uk3:
        st.metric("Mudanças de Faixa", f"{n_faixa_change:,}".replace(",", "."))
    with uk4:
        st.metric("Delta MRR de Upgrades", f"R$ {fmt_brl(mrr_upgrades)}")

    # ── Gráfico: upgrades por tipo ao longo do tempo ──────────────────────────
    col_u1, col_u2 = st.columns([3, 2])

    with col_u1:
        df_up_mes = (
            df_upgrade_f.groupby(["mes", "tipo_upgrade"], as_index=False)
            .agg(qtd=("cliente_id", "count"), delta=("delta_mrr", "sum"))
        )
        df_up_base = df_upgrade_f.groupby("mes", as_index=False)["delta_mrr"].sum()
        df_up_base, x_order_up = mes_fmt_ordered(df_up_base)

        fig = go.Figure()
        for tipo in ["mudanca_plano", "mudanca_faixa", "novo_sem_anterior", "outro"]:
            sub = df_up_mes[df_up_mes["tipo_upgrade"] == tipo].copy()
            if sub.empty:
                continue
            sub, _ = mes_fmt_ordered(sub)
            fig.add_bar(
                x=sub["mes_fmt"], y=sub["delta"],
                name=TIPO_UPGRADE_LABELS.get(tipo, tipo),
                marker_color=TIPO_UPGRADE_COLORS.get(tipo, PALETTE[3]),
                customdata=sub["qtd"],
                hovertemplate=f"<b>{TIPO_UPGRADE_LABELS.get(tipo, tipo)}</b><br>R$ %{{y:,.0f}} | %{{customdata}} clientes<extra></extra>",
            )
        fig.update_layout(
            barmode="stack",
            xaxis=dict(categoryorder="array", categoryarray=x_order_up, type="category"),
        )
        st.plotly_chart(chart_layout(fig, height=340, legend_bottom=True), use_container_width=True)

    with col_u2:
        # Pizza por tipo_upgrade no período
        df_tipo_pie = (
            df_upgrade_f.groupby("tipo_upgrade", as_index=False)
            .agg(delta=("delta_mrr", "sum"), qtd=("cliente_id", "count"))
        )
        df_tipo_pie = df_tipo_pie[df_tipo_pie["delta"] > 0]
        if not df_tipo_pie.empty:
            fig = go.Figure(go.Pie(
                labels=df_tipo_pie["tipo_upgrade"].map(TIPO_UPGRADE_LABELS),
                values=df_tipo_pie["delta"],
                hole=0.45,
                marker_colors=[TIPO_UPGRADE_COLORS.get(t, PALETTE[3]) for t in df_tipo_pie["tipo_upgrade"]],
                textfont=dict(size=11, family="Outfit"),
            ))
            fig.update_traces(
                texttemplate="%{label}<br>%{percent}",
                hovertemplate="<b>%{label}</b><br>R$ %{value:,.0f} (%{percent})<extra></extra>",
            )
            st.plotly_chart(chart_layout(fig, height=340), use_container_width=True)
            st.caption("Delta MRR por tipo de upgrade no período")

    # ── Tabela de fluxos: Plano Antigo → Plano Novo ───────────────────────────
    col_f1, col_f2 = st.columns(2)

    with col_f1:
        st.markdown("##### Fluxos de Mudança de Plano")
        df_plano_flow = (
            df_upgrade_f[df_upgrade_f["tipo_upgrade"] == "mudanca_plano"]
            .groupby(["plano_antigo", "plano_novo"], as_index=False)
            .agg(qtd=("cliente_id", "count"), delta_mrr=("delta_mrr", "sum"))
            .sort_values("delta_mrr", ascending=False)
        )
        if df_plano_flow.empty:
            no_data("Nenhuma mudança de plano no período.")
        else:
            df_plano_flow["plano_antigo"] = df_plano_flow["plano_antigo"].map(
                lambda x: PLAN_LABELS_EXT.get(x, x.upper())
            )
            df_plano_flow["plano_novo"] = df_plano_flow["plano_novo"].map(
                lambda x: PLAN_LABELS_EXT.get(x, x.upper())
            )
            df_plano_flow = df_plano_flow.rename(columns={
                "plano_antigo": "De",
                "plano_novo":   "Para",
                "qtd":          "Upgrades",
                "delta_mrr":    "Delta MRR",
            })
            st.dataframe(
                df_plano_flow,
                use_container_width=True,
                hide_index=True,
                column_config={"Delta MRR": st.column_config.NumberColumn(format="R$ %,.0f")},
            )

    with col_f2:
        st.markdown("##### Fluxos de Mudança de Faixa")
        df_faixa_flow = (
            df_upgrade_f[df_upgrade_f["tipo_upgrade"] == "mudanca_faixa"]
            .groupby(["plano_novo", "faixa_antiga", "faixa_nova"], as_index=False)
            .agg(qtd=("cliente_id", "count"), delta_mrr=("delta_mrr", "sum"))
            .sort_values("delta_mrr", ascending=False)
        )
        if df_faixa_flow.empty:
            no_data("Nenhuma mudança de faixa no período.")
        else:
            df_faixa_flow["plano_novo"] = df_faixa_flow["plano_novo"].map(
                lambda x: PLAN_LABELS_EXT.get(x, x.upper())
            )
            df_faixa_flow = df_faixa_flow.rename(columns={
                "plano_novo":  "Plano",
                "faixa_antiga": "Faixa Anterior",
                "faixa_nova":   "Faixa Nova",
                "qtd":          "Upgrades",
                "delta_mrr":    "Delta MRR",
            })
            st.dataframe(
                df_faixa_flow,
                use_container_width=True,
                hide_index=True,
                column_config={"Delta MRR": st.column_config.NumberColumn(format="R$ %,.0f")},
            )

    # ── Tabela detalhada de upgrades ──────────────────────────────────────────
    with st.expander("🔍 Detalhes por Cliente"):
        df_det_up = df_upgrade_f.sort_values(["mes", "delta_mrr"], ascending=[False, False]).copy()
        df_det_up["mes"] = df_det_up["mes"].dt.strftime("%b/%y").str.capitalize()
        df_det_up["tipo_upgrade"] = df_det_up["tipo_upgrade"].map(TIPO_UPGRADE_LABELS).fillna(df_det_up["tipo_upgrade"])
        df_det_up["plano_antigo"] = df_det_up["plano_antigo"].map(lambda x: PLAN_LABELS_EXT.get(x, x.upper()))
        df_det_up["plano_novo"]   = df_det_up["plano_novo"].map(lambda x: PLAN_LABELS_EXT.get(x, x.upper()))
        df_det_up = df_det_up.rename(columns={
            "mes":          "Mês",
            "cliente_id":   "ID Cliente",
            "prd_antigo":   "Produto Anterior",
            "prd_novo":     "Produto Novo",
            "mrr_antigo":   "MRR Anterior",
            "mrr_novo":     "MRR Novo",
            "delta_mrr":    "Delta MRR",
            "plano_antigo": "Plano Ant.",
            "plano_novo":   "Plano Novo",
            "faixa_antiga": "Faixa Ant.",
            "faixa_nova":   "Faixa Nova",
            "tipo_upgrade": "Tipo",
        })
        st.dataframe(
            df_det_up[[
                "Mês", "ID Cliente", "Tipo",
                "Plano Ant.", "Plano Novo", "Faixa Ant.", "Faixa Nova",
                "MRR Anterior", "MRR Novo", "Delta MRR",
            ]],
            use_container_width=True, hide_index=True,
            column_config={
                "MRR Anterior": st.column_config.NumberColumn(format="R$ %,.0f"),
                "MRR Novo":     st.column_config.NumberColumn(format="R$ %,.0f"),
                "Delta MRR":    st.column_config.NumberColumn(format="R$ %,.0f"),
            },
        )

st.divider()

# ── Gráfico 2: Attach Rate por módulo ────────────────────────────────────────
st.subheader("Attach Rate por Módulo")

if df_attach_f.empty:
    no_data()
else:
    df_plot, x_order = mes_fmt_ordered(df_attach_f)
    fig = go.Figure()
    for modulo in ["kids", "jornada", "loja_inteligente", "totem"]:
        sub = df_plot[df_plot["modulo"] == modulo].sort_values("mes")
        if sub.empty:
            continue
        fig.add_scatter(
            x=sub["mes_fmt"], y=sub["attach_rate"],
            name=MODULE_LABELS.get(modulo, modulo),
            mode="lines+markers",
            line=dict(color=MODULE_COLORS.get(modulo, PALETTE[3]), width=2.5),
            marker=dict(size=7),
            hovertemplate=f"<b>{MODULE_LABELS.get(modulo, modulo)}</b><br>%{{y:.1f}}%<extra></extra>",
        )
    fig.update_layout(
        yaxis=dict(ticksuffix="%"),
        xaxis=dict(categoryorder="array", categoryarray=x_order, type="category"),
    )
    st.plotly_chart(chart_layout(fig, height=360, legend_bottom=True), use_container_width=True)

st.divider()

# ── Gráfico 3: Distribuição tempo até primeiro upsell ────────────────────────
st.subheader("Distribuição — Dias até Primeiro Upsell")

col_hist, col_stats = st.columns([3, 2])

with col_hist:
    if df_timing.empty:
        no_data()
    else:
        df_t = df_timing.copy()
        df_t["faixa"] = pd.cut(
            df_t["dias_ate_upsell"],
            bins=[0, 30, 60, 90, 180, 365, 730, float("inf")],
            labels=["≤30d", "31-60d", "61-90d", "3-6m", "6-12m", "1-2a", ">2a"],
        )
        faixa_agg = df_t.groupby("faixa", observed=True)["clientes"].sum().reset_index()
        fig = go.Figure()
        fig.add_bar(
            x=faixa_agg["faixa"].astype(str),
            y=faixa_agg["clientes"],
            marker_color=PALETTE[0],
            text=faixa_agg["clientes"],
            textposition="outside",
            textfont=dict(size=11, color="#a0a0a0"),
            hovertemplate="<b>%{x}</b><br>%{y} clientes<extra></extra>",
        )
        fig.update_layout(showlegend=False)
        st.plotly_chart(chart_layout(fig, height=320), use_container_width=True)

with col_stats:
    if not df_timing.empty:
        df_t = df_timing.copy()
        total_upsell = df_t["clientes"].sum()
        pct_menos_90 = df_t[df_t["dias_ate_upsell"] <= 90]["clientes"].sum() / total_upsell * 100
        pct_mais_365 = df_t[df_t["dias_ate_upsell"] > 365]["clientes"].sum() / total_upsell * 100
        mediana = int(np.median(
            np.repeat(df_t["dias_ate_upsell"].values, df_t["clientes"].values)
        ))
        st.markdown("#### Estatísticas")
        stats = {
            "Clientes com upsell": f"{total_upsell:,}".replace(",", "."),
            "Tempo médio":         f"{avg_dias} dias" if avg_dias else "—",
            "Mediana":             f"{mediana} dias",
            "Upsell em ≤90 dias":  f"{pct_menos_90:.1f}%",
            "Upsell após 1 ano":   f"{pct_mais_365:.1f}%",
        }
        for label, valor in stats.items():
            cols = st.columns([2, 2])
            cols[0].markdown(f"<span style='color:#a0a0a0;font-size:0.85rem;'>{label}</span>",
                             unsafe_allow_html=True)
            cols[1].markdown(f"<span style='font-weight:600;'>{valor}</span>",
                             unsafe_allow_html=True)

st.divider()

# ── Tabelas no rodapé ─────────────────────────────────────────────────────────
with st.expander("📋 Tabela de Expansion MRR por Módulo"):
    if df_exp_mod_f.empty:
        no_data()
    else:
        df_show = df_exp_mod_f.sort_values(["mes", "expansion_mrr"], ascending=[False, False]).copy()
        df_show["mes"] = df_show["mes"].dt.strftime("%b/%y").str.capitalize()
        df_show["tipo"] = df_show["tipo"].map(MODULE_LABELS)
        df_show = df_show.rename(columns={
            "mes":           "Mês",
            "tipo":          "Tipo",
            "expansion_mrr": "Expansion MRR",
            "clientes":      "Clientes",
        })
        st.dataframe(df_show, use_container_width=True, hide_index=True,
                     column_config={"Expansion MRR": st.column_config.NumberColumn(format="R$ %,.0f")})

with st.expander("🔍 Clientes com Maior Expansion (últimos 6 meses)"):
    if df_exp_det_f.empty:
        no_data()
    else:
        df_det = df_exp_det_f.sort_values(["mes", "expansion_mrr"], ascending=[False, False]).copy()
        df_det["mes"] = df_det["mes"].dt.strftime("%b/%y").str.capitalize()
        df_det["tipo"] = df_det["tipo"].map(MODULE_LABELS).fillna(df_det["tipo"])
        df_det = df_det.rename(columns={
            "mes":           "Mês",
            "cliente_id":    "ID Cliente",
            "produto":       "Produto",
            "expansion_mrr": "Expansion MRR",
            "tipo":          "Tipo",
        })
        st.dataframe(df_det, use_container_width=True, hide_index=True,
                     column_config={"Expansion MRR": st.column_config.NumberColumn(format="R$ %,.0f")})
