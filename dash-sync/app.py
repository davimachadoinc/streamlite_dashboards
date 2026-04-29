"""
app.py — DASH SYNC
Autenticação via Google OIDC (st.login / st.user).
"""
import streamlit as st
from utils.style import inject_css

st.set_page_config(
    page_title="Dash Sync | InChurch",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()


def _is_allowed(email: str) -> bool:
    allowed = st.secrets.get("app_config", {}).get("allowed_emails", [])
    return email in allowed


if not st.user.is_logged_in:
    st.markdown(
        """
        <style>
        [data-testid="stButton"] > button {
            background: #1E1E1E !important;
            color: #ffffff !important;
            border: 1px solid #292929 !important;
            border-radius: 10px !important;
            font-weight: 500 !important;
            transition: all 0.2s ease;
        }
        [data-testid="stButton"] > button:hover {
            background: rgba(110,218,44,0.1) !important;
            border-color: #6eda2c !important;
            color: #6eda2c !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            """
            <div style="text-align:center; padding: 60px 0 32px 0;">
              <h1 style="font-size:2.4rem; margin-bottom:4px;">
                Dash<span> Sync</span>
              </h1>
              <p style="color:#a0a0a0; font-size:1rem; margin-top:0;">
                Painel de Performance & Operacional
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Entrar com Google", use_container_width=True):
            st.login()
    st.stop()

user_email = st.user.email
user_name = getattr(st.user, "name", user_email)

if not _is_allowed(user_email):
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.error(
            f"❌ O e-mail **{user_email}** não tem permissão de acesso.\n\n"
            "Entre em contato com o administrador."
        )
        if st.button("↩️  Sair", use_container_width=True):
            st.logout()
    st.stop()

with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        st.logout()

st.switch_page("pages/1_Painel_Performance.py")
