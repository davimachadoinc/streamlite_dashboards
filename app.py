"""
app.py
Ponto de entrada do dashboard InChurch.
Login simplificado por e-mail (sem OAuth externo).
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
# AUTENTICAÇÃO SIMPLES POR E-MAIL
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

        email = st.text_input("E-mail corporativo", placeholder="email@inchurch.com.br")

        if st.button("Entrar", use_container_width=True):
            if check_allowed(email):
                st.session_state["authenticated"] = True
                st.session_state["user_email"] = email
                st.session_state["user_name"] = email.split("@")[0].title()
                st.rerun()
            else:
                st.error("E-mail não autorizado. Entre em contato com o administrador.")


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
        for key in ["authenticated", "user_email", "user_name"]:
            st.session_state.pop(key, None)
        st.rerun()

st.switch_page("pages/1_📊_Cobranca.py")
