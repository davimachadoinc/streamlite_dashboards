"""
app.py
Ponto de entrada do dashboard InChurch.
Gerencia autenticação Google OAuth e roteamento para pages/.
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
# AUTENTICAÇÃO GOOGLE OAUTH
# ─────────────────────────────────────────────
def is_authenticated() -> bool:
    return st.session_state.get("authenticated", False)


def check_allowed(email: str) -> bool:
    allowed = st.secrets.get("auth", {}).get("allowed_emails", [])
    return email in allowed


def login_page() -> None:
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown(
            """
            <div style="text-align:center; padding: 60px 0 30px 0;">
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

        try:
            from streamlit_google_auth import Authenticate

            auth = Authenticate(
                secret_credentials_path=None,
                cookie_name="inchurch_auth",
                cookie_key=st.secrets["google_oauth"]["client_secret"],
                redirect_uri=st.secrets["google_oauth"]["redirect_uri"],
                client_id=st.secrets["google_oauth"]["client_id"],
                client_secret=st.secrets["google_oauth"]["client_secret"],
            )

            auth.check_authentification()

            if not st.session_state.get("connected"):
                st.markdown(
                    "<p style='text-align:center; color:#a0a0a0; margin-bottom:20px;'>"
                    "Faça login com sua conta Google corporativa.</p>",
                    unsafe_allow_html=True,
                )
                auth.login()
            else:
                user_email = st.session_state.get("user_info", {}).get("email", "")
                if check_allowed(user_email):
                    st.session_state["authenticated"] = True
                    st.session_state["user_email"] = user_email
                    st.session_state["user_name"] = (
                        st.session_state.get("user_info", {}).get("name", user_email)
                    )
                    st.rerun()
                else:
                    st.error(
                        f"❌ O e-mail **{user_email}** não tem permissão de acesso. "
                        "Entre em contato com o administrador."
                    )
                    st.stop()

        except ImportError:
            # Fallback para desenvolvimento local sem OAuth configurado
            st.warning(
                "⚠️ Biblioteca `streamlit-google-auth` não instalada. "
                "Usando login simplificado para desenvolvimento.",
                icon="⚠️",
            )
            dev_email = st.text_input("E-mail (desenvolvimento)", placeholder="email@inchurch.com.br")
            if st.button("Entrar", use_container_width=True):
                if check_allowed(dev_email):
                    st.session_state["authenticated"] = True
                    st.session_state["user_email"] = dev_email
                    st.session_state["user_name"] = dev_email.split("@")[0].title()
                    st.rerun()
                else:
                    st.error("E-mail não autorizado.")


# ─────────────────────────────────────────────
# ROTEAMENTO PRINCIPAL
# ─────────────────────────────────────────────
if not is_authenticated():
    login_page()
    st.stop()

# ── Usuário autenticado ───────────────────────
with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.8rem; margin-bottom:16px;'>"
        f"👤 {st.session_state.get('user_name', '')}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        for key in ["authenticated", "user_email", "user_name", "connected", "user_info"]:
            st.session_state.pop(key, None)
        st.rerun()

# Redireciona para a primeira página após login
st.switch_page("pages/1_📊_Cobranca.py")
