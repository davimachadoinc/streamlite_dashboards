"""
app.py
Ponto de entrada do dashboard InChurch.
Autenticação via Google OAuth com streamlit-google-auth.
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


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def is_authenticated() -> bool:
    return st.session_state.get("authenticated", False)


def check_allowed(email: str) -> bool:
    allowed = st.secrets.get("auth", {}).get("allowed_emails", [])
    return email in allowed


def render_login_card(message: str = None, error: str = None):
    """Renderiza o card central de login."""
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
        if message:
            st.info(message)
        if error:
            st.error(error)


# ─────────────────────────────────────────────
# FLUXO DE LOGIN — Google OAuth
# ─────────────────────────────────────────────
def login_page():
    try:
        from streamlit_google_auth import Authenticate

        authenticator = Authenticate(
            secret_credentials_path=None,
            cookie_name="inchurch_auth",
            cookie_key=st.secrets["google_oauth"]["client_secret"],
            redirect_uri=st.secrets["google_oauth"]["redirect_uri"],
            client_id=st.secrets["google_oauth"]["client_id"],
            client_secret=st.secrets["google_oauth"]["client_secret"],
        )

        # Verifica se já há cookie de sessão válido
        authenticator.check_authentification()

        if not st.session_state.get("connected"):
            # Ainda não autenticado — exibe botão de login
            render_login_card(message="Faça login com sua conta Google corporativa.")
            _, col, _ = st.columns([1, 2, 1])
            with col:
                authenticator.login()

        else:
            # Autenticado pelo Google — valida se e-mail é permitido
            user_info  = st.session_state.get("user_info", {})
            user_email = user_info.get("email", "")
            user_name  = user_info.get("name", user_email)

            if check_allowed(user_email):
                st.session_state["authenticated"] = True
                st.session_state["user_email"]    = user_email
                st.session_state["user_name"]     = user_name
                st.rerun()
            else:
                render_login_card(
                    error=f"❌ O e-mail **{user_email}** não tem permissão de acesso.\n\n"
                          "Entre em contato com o administrador."
                )

    except ImportError:
        # Fallback para desenvolvimento local sem a lib instalada
        render_login_card(message="Login simplificado (desenvolvimento local)")
        _, col, _ = st.columns([1, 2, 1])
        with col:
            email = st.text_input("E-mail corporativo", placeholder="email@inchurch.com.br")
            if st.button("Entrar", use_container_width=True):
                if check_allowed(email):
                    st.session_state["authenticated"] = True
                    st.session_state["user_email"]    = email
                    st.session_state["user_name"]     = email.split("@")[0].title()
                    st.rerun()
                else:
                    st.error("E-mail não autorizado.")


# ─────────────────────────────────────────────
# ROTEAMENTO PRINCIPAL
# ─────────────────────────────────────────────
if not is_authenticated():
    login_page()
    st.stop()

# ── Sidebar — usuário autenticado ─────────────
with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:4px;'>👤 "
        f"{st.session_state.get('user_name', '')}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>"
        f"{st.session_state.get('user_email', '')}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        for key in ["authenticated", "user_email", "user_name", "connected", "user_info"]:
            st.session_state.pop(key, None)
        st.rerun()

st.switch_page("pages/1_📊_Cobranca.py")