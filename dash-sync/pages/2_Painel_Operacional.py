"""
pages/2_Painel_Operacional.py
DASH SYNC — Painel Operacional (semana a semana, últimas 10 colunas).
"""
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Operacional | Dash Sync", page_icon="⚙️", layout="wide")

if not st.user.is_logged_in:
    st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
    st.stop()

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.style import inject_css
from utils.sheets import load_operacional

inject_css()

# ── Paleta / helpers ────────────────────────────────────────────────────
_ACCENT  = "#6eda2c"
_MUTED   = "#a0a0a0"
_BG_CARD = "#121212"
_BORDER  = "#292929"

_BAR_UNITS = {"num", ""}


def _chart_layout() -> dict:
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Outfit, sans-serif", color="#a0a0a0", size=11),
        margin=dict(l=0, r=0, t=8, b=0),
        xaxis=dict(
            showgrid=False, zeroline=False,
            tickfont=dict(size=10, color=_MUTED),
            linecolor=_BORDER,
        ),
        yaxis=dict(
            showgrid=True, gridcolor=_BORDER, zeroline=False,
            tickfont=dict(size=10, color=_MUTED),
        ),
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=10)),
        hovermode="x unified",
    )


def _status_badge(emoji: str, color: str, name: str) -> str:
    dot = f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{color};margin-right:6px;vertical-align:middle;'></span>"
    return f"<span style='font-size:0.82rem;font-weight:600;color:{color};'>{dot}{name}</span>"


def _indicator_card(ind: dict) -> None:
    dates  = ind["dates"]
    values = ind["values"]
    limite = ind["limite"]
    unit   = ind["unit"].lower()
    color  = ind["status_color"]
    name   = ind["name"]

    use_bar = unit in _BAR_UNITS

    fig = go.Figure()

    if use_bar:
        fig.add_trace(go.Bar(
            x=dates, y=values,
            name=name,
            marker_color=color,
            opacity=0.85,
        ))
    else:
        fig.add_trace(go.Scatter(
            x=dates, y=values,
            mode="lines+markers",
            name=name,
            line=dict(color=color, width=2),
            marker=dict(size=5),
        ))

    if limite is not None:
        fig.add_hline(
            y=limite,
            line_dash="dash",
            line_color="#4c4c4c",
            annotation_text=f"Limite: {ind['limite_raw']}",
            annotation_font_size=10,
            annotation_font_color=_MUTED,
            annotation_position="top right",
        )

    fig.update_layout(**_chart_layout())
    fig.update_layout(showlegend=False, height=200)

    limite_label = (
        f"<div style='font-size:0.72rem;color:#4c4c4c;margin-bottom:4px;'>Limite saudável: {ind['limite_raw']}</div>"
        if ind["limite_raw"] and ind["limite_raw"] not in ("-", "em breve")
        else ""
    )

    st.markdown(
        f"<div style='margin-bottom:4px;'>{_status_badge(ind['status_emoji'], color, name)}</div>"
        + limite_label,
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ── Carga ───────────────────────────────────────────────────────────────
st.markdown("<h1>Painel <span>Operacional</span></h1>", unsafe_allow_html=True)

with st.spinner("Carregando dados da planilha..."):
    indicators = load_operacional()

if not indicators:
    st.warning("Nenhum dado encontrado. Verifique se a planilha está compartilhada com a conta de serviço.")
    st.stop()

# Filtro de área
areas = sorted({ind["area"] for ind in indicators})
col_f, _ = st.columns([3, 7])
with col_f:
    area_filter = st.selectbox("Área", ["Todas"] + areas, key="op_area")

if area_filter != "Todas":
    indicators = [i for i in indicators if i["area"] == area_filter]

st.caption(f"Mostrando as últimas 10 semanas disponíveis · {len(indicators)} indicadores")
st.divider()

# ── Renderiza por área ──────────────────────────────────────────────────
grouped: dict[str, list] = {}
for ind in indicators:
    grouped.setdefault(ind["area"], []).append(ind)

for area, inds in grouped.items():
    st.markdown(f"### {area}")

    pairs = [inds[i:i+2] for i in range(0, len(inds), 2)]
    for pair in pairs:
        cols = st.columns(len(pair))
        for col, ind in zip(cols, pair):
            with col:
                st.markdown(
                    "<div style='background:#121212;border:1px solid #292929;border-radius:12px;padding:16px 16px 4px 16px;margin-bottom:12px;'>",
                    unsafe_allow_html=True,
                )
                _indicator_card(ind)
                st.markdown("</div>", unsafe_allow_html=True)

    st.divider()
