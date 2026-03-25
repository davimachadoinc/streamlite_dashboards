import streamlit as st

st.set_page_config(
    page_title="Gerenciamento de Férias",
    page_icon="🏖️",
    layout="centered"
)

if st.user.is_logged_in:
    st.switch_page("pages/Gestao_de_Ferias.py")

st.image(
    "https://inchurch.com.br/wp-content/uploads/2024/09/inchurch-logo-svg.svg",
    width=240
)
st.title("Gerenciamento de Férias")
st.markdown("---")
st.write("Faça login com sua conta Google **@inchurch.com.br** para acessar o sistema.")
st.login()
