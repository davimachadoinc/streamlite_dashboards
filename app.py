"""
app.py
Autenticação nativa Streamlit via Google OIDC (st.login / st.user).
allowed_emails lido de [app_config] para não conflitar com [auth].
"""
import streamlit as st
from utils.style import inject_css

st.set_page_config(
    page_title="InChurch Dashboard",
    page_icon="⛪",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()


def check_allowed(email: str) -> bool:
    # Lê de [app_config] — seção separada do [auth] nativo do Streamlit
    allowed = st.secrets.get("app_config", {}).get("allowed_emails", [])
    return email in allowed


# ─────────────────────────────────────────────
# AUTENTICAÇÃO
# ─────────────────────────────────────────────
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
                Dashboard de Negócios
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button("🔐  Entrar com Google", use_container_width=True, on_click=st.login)
    st.stop()

# ── Verifica permissão após login ─────────────
user_email = st.user.email
user_name  = getattr(st.user, "name", user_email)

if not check_allowed(user_email):
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.error(
            f"❌ O e-mail **{user_email}** não tem permissão de acesso.\n\n"
            "Entre em contato com o administrador."
        )
        st.button("↩️  Sair", use_container_width=True, on_click=st.logout)
    st.stop()

# ── Sidebar ───────────────────────────────────
with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    st.button("🚪 Sair", use_container_width=True, on_click=st.logout)

st.switch_page("pages/1_📊_Cobranca.py")