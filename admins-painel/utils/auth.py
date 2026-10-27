"""
utils/auth.py
Checagem de acesso compartilhada por app.py e por todas as páginas.
Autorizado = e-mail em app_config.allowed_emails OU domínio em app_config.allowed_domains (opcional).
"""
import streamlit as st


def check_allowed(email: str) -> bool:
    cfg = st.secrets.get("app_config", {})
    email = (email or "").strip().lower()
    emails = [e.strip().lower() for e in cfg.get("allowed_emails", [])]
    dominios = [d.strip().lower().lstrip("@") for d in cfg.get("allowed_domains", [])]
    return email in emails or email.split("@")[-1] in dominios


def require_access() -> None:
    """Chamar no topo de cada página (após set_page_config). Interrompe se não logado ou não autorizado."""
    if not st.user.is_logged_in:
        st.error("⛔ Acesso não autorizado. Faça login na página inicial.")
        st.stop()
    if not check_allowed(st.user.email):
        st.error(f"❌ O e-mail **{st.user.email}** não tem permissão de acesso.")
        st.stop()
