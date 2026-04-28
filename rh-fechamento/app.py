"""
app.py — RH Fechamento de Solicitações
Atualiza status nas abas Contratação / Demissão / Alteração da planilha de RH.
"""
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from utils.style import inject_css

# ── Configuração da página ────────────────────
st.set_page_config(
    page_title="RH · Fechamento",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()

# ── Constantes ────────────────────────────────
SHEET_ID = "1j8UdznWVfZlAzzA_0uTRoCs2dPkCjBcTTqxkXamg8SM"
ABAS = ["Contratação", "Demissão", "Alteração"]
STATUS_OPTIONS = ["Finalizado", "Aguardando", "Cancelado"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ── Autenticação Google OIDC ──────────────────
def check_allowed(email: str) -> bool:
    allowed = st.secrets.get("app_config", {}).get("allowed_emails", [])
    return email in allowed


if not st.user.is_logged_in:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            """
            <div style="text-align:center; padding: 60px 0 32px 0;">
              <h1 style="font-size:2.4rem; margin-bottom:4px;">
                In<span>Church</span>
              </h1>
              <p style="color:#a0a0a0; font-size:1rem; margin-top:0;">
                RH · Fechamento de Solicitações
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🔐  Entrar com Google", use_container_width=True):
            st.login()
    st.stop()

user_email = st.user.email
user_name  = getattr(st.user, "name", user_email)

if not check_allowed(user_email):
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.error(
            f"❌ O e-mail **{user_email}** não tem permissão de acesso.\n\n"
            "Entre em contato com o administrador."
        )
        if st.button("↩️  Sair", use_container_width=True):
            st.logout()
    st.stop()

# ── Sidebar ───────────────────────────────────
with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        st.logout()

# ── Google Sheets helper ──────────────────────
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def load_aba(aba: str) -> tuple[list[dict], list]:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(aba)
    values = ws.get_all_values()
    if len(values) < 2:
        return [], values
    headers = values[0]
    rows = [dict(zip(headers, row)) for row in values[1:]]
    return rows, values


def update_status(aba: str, row_index_1based: int, new_status: str) -> None:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.worksheet(aba)

    headers = ws.row_values(1)
    try:
        col_status = headers.index("status") + 1
        col_data   = headers.index("dataAtualizacaoStatus") + 1
    except ValueError as e:
        st.error(f"Coluna não encontrada: {e}")
        return

    today = datetime.today().strftime("%d/%m/%Y %H:%M")
    ws.update_cell(row_index_1based, col_status, new_status)
    ws.update_cell(row_index_1based, col_data, today)


# ── Estado de sessão ──────────────────────────
if "aba_selecionada"   not in st.session_state: st.session_state.aba_selecionada   = None
if "linha_selecionada" not in st.session_state: st.session_state.linha_selecionada = None
if "concluido"         not in st.session_state: st.session_state.concluido         = False

# ── Layout principal ──────────────────────────
st.markdown(
    "<h1>In<span>Church</span> · RH</h1>"
    "<p style='color:#a0a0a0; margin-top:0; margin-bottom:24px;'>Fechamento de Solicitações</p>",
    unsafe_allow_html=True,
)

# ────────────────────────────────────────────
# PASSO 1 — Selecionar aba
# ────────────────────────────────────────────
st.markdown("### 1. Qual tipo de solicitação?")

cols = st.columns(3)
for i, aba in enumerate(ABAS):
    with cols[i]:
        selected = st.session_state.aba_selecionada == aba
        btn_label = f"{'✅ ' if selected else ''}{aba}"
        if st.button(btn_label, key=f"aba_{aba}", use_container_width=True):
            if st.session_state.aba_selecionada != aba:
                st.session_state.aba_selecionada   = aba
                st.session_state.linha_selecionada = None
                st.session_state.concluido         = False
            st.rerun()

if not st.session_state.aba_selecionada:
    st.stop()

aba = st.session_state.aba_selecionada
st.divider()

# ────────────────────────────────────────────
# PASSO 2 — Tabela + seleção da linha
# ────────────────────────────────────────────
with st.spinner("Carregando planilha..."):
    rows, all_values = load_aba(aba)

headers = all_values[0] if all_values else []

def col_val(row: dict, col_letter: str) -> str:
    idx = ord(col_letter.upper()) - ord("A")
    if idx < len(headers):
        return row.get(headers[idx], "").strip()
    return ""

def build_label(row: dict) -> str:
    cargo = col_val(row, "E")
    ts    = col_val(row, "A")
    area  = col_val(row, "H")
    parts = [p for p in [cargo, ts, area] if p]
    return " — ".join(parts) if parts else "(sem identificação)"

# Filtrar apenas "Em andamento"
abertas = [
    (i + 2, r)
    for i, r in enumerate(rows)
    if r.get("status", "").strip() == "Em andamento"
]

if not abertas:
    st.info(f"Nenhuma solicitação com status **Em andamento** em **{aba}**.")
    st.stop()

st.markdown(f"### 2. Solicitações em andamento — {aba}")
st.caption(f"{len(abertas)} registro(s) encontrado(s)")

# Montar dados para exibição
label_map = {}
table_rows_html = ""
for row_idx, r in abertas:
    label = build_label(r)
    label_map[label] = row_idx
    cargo = col_val(r, "E") or "—"
    data  = col_val(r, "A") or "—"
    area  = col_val(r, "H") or "—"
    table_rows_html += f"""
    <tr>
      <td>{cargo}</td>
      <td>{data}</td>
      <td>{area}</td>
    </tr>"""

st.markdown(f"""
<table style="width:100%; border-collapse:collapse; font-family:'Outfit',sans-serif; font-size:0.9rem;">
  <thead>
    <tr style="border-bottom:2px solid #6eda2c;">
      <th style="text-align:left; padding:10px 14px; color:#a0a0a0; font-weight:500; text-transform:uppercase; font-size:0.75rem; letter-spacing:0.06em;">Cargo / Identificação</th>
      <th style="text-align:left; padding:10px 14px; color:#a0a0a0; font-weight:500; text-transform:uppercase; font-size:0.75rem; letter-spacing:0.06em;">Data</th>
      <th style="text-align:left; padding:10px 14px; color:#a0a0a0; font-weight:500; text-transform:uppercase; font-size:0.75rem; letter-spacing:0.06em;">Área</th>
    </tr>
  </thead>
  <tbody style="color:#ffffff;">
    {table_rows_html}
  </tbody>
</table>
<style>
  tbody tr {{ border-bottom: 1px solid #292929; }}
  tbody tr:last-child {{ border-bottom: none; }}
  tbody td {{ padding: 10px 14px; vertical-align: middle; }}
  tbody tr:hover td {{ background: #1e1e1e; }}
</style>
""", unsafe_allow_html=True)

st.divider()

# Seleção via dropdown
st.markdown("### 3. Selecione a solicitação para atualizar")

escolha = st.selectbox(
    "Solicitação:",
    options=list(label_map.keys()),
    index=None,
    placeholder="Escolha...",
)

if escolha:
    st.session_state.linha_selecionada = (escolha, label_map[escolha])

if not st.session_state.linha_selecionada:
    st.stop()

label_escolhido, row_idx = st.session_state.linha_selecionada
st.divider()

# ────────────────────────────────────────────
# PASSO 4 — Escolher novo status
# ────────────────────────────────────────────
if st.session_state.concluido:
    st.success("✅ Status atualizado com sucesso!")
    if st.button("↩️  Fazer outra atualização", use_container_width=True):
        st.session_state.aba_selecionada   = None
        st.session_state.linha_selecionada = None
        st.session_state.concluido         = False
        st.rerun()
    st.stop()

st.markdown("### 4. Novo status")
st.markdown(
    f"<div style='background:#121212; border:1px solid #292929; border-left:3px solid #6eda2c;"
    f"border-radius:8px; padding:12px 16px; margin-bottom:20px; color:#fff; font-size:0.97rem;'>"
    f"{label_escolhido}</div>",
    unsafe_allow_html=True,
)

btn_cols = st.columns(3)
for i, status in enumerate(STATUS_OPTIONS):
    with btn_cols[i]:
        if st.button(status, key=f"status_{status}", use_container_width=True):
            with st.spinner("Atualizando..."):
                update_status(aba, row_idx, status)
                get_gspread_client.clear()
            st.session_state.concluido = True
            st.rerun()
