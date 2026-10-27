"""
pages/3_Novos_Cadastros.py
Administradores do painel de controle cadastrados recentemente, do mais novo para o mais antigo.
"""
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Novos Cadastros | Admins do Painel", page_icon="🛡️", layout="wide")

from utils.auth import require_access

require_access()

from utils.style import inject_css
from utils.data import load_admins, load_igrejas, filtrar_codigos

inject_css()

with st.sidebar:
    st.markdown("---")
    if st.button("🔄 Limpar cache", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "**Data de criação** = `view_basicuser.created_at` (data e hora do cadastro).\n\n"
        "**Administrador** (`view_basicuser.user_type`) = Admin, Admin de equipe e Regional; "
        "Membro de equipe só se tiver registro em `view_admin_access`.\n\n"
        "Igreja e denominação vêm do cadastro do usuário (`tertiarygroup_id` / `subgroup_id`)."
    )

st.markdown("<h1>Novos <span>Cadastros</span></h1>", unsafe_allow_html=True)

with st.spinner("Carregando dados..."):
    admins = load_admins()
    igrejas = load_igrejas()

locais = igrejas[["cod_local", "igreja"]].drop_duplicates("cod_local")
denoms = igrejas[["cod_denominacao", "denominacao"]].drop_duplicates("cod_denominacao")
df = admins.merge(locais, on="cod_local", how="left").merge(denoms, on="cod_denominacao", how="left")

c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
cod_local = c1.text_input("Código Local", placeholder="Ex.: 32187", key="novos_local")
cod_denom = c2.text_input("Código de Denominação", placeholder="Ex.: 3987", key="novos_denom")
periodo = c3.selectbox("Criados nos últimos", ["30 dias", "7 dias", "90 dias", "Todos"])
tipos = sorted(df["tipo"].dropna().unique())
sel = c4.multiselect("Tipo", tipos, placeholder="Todos")

df = filtrar_codigos(df, cod_local, cod_denom)
if sel:
    df = df[df["tipo"].isin(sel)]
if periodo != "Todos":
    dias = int(periodo.split()[0])
    df = df[df["criado_em"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=dias - 1)]
df = df.sort_values("criado_em", ascending=False)

st.metric("Novos administradores", f"{len(df):,}".replace(",", "."))

st.dataframe(
    df[["criado_em", "nome", "email", "tipo", "nivel", "cod_local", "igreja", "cod_denominacao", "denominacao"]],
    use_container_width=True,
    hide_index=True,
    height=620,
    column_config={
        "criado_em": st.column_config.DatetimeColumn("Criado em", format="DD/MM/YYYY HH:mm"),
        "nome": "Nome",
        "email": "E-mail",
        "tipo": "Tipo",
        "nivel": "Nível de acesso",
        "cod_local": st.column_config.NumberColumn("Cód. Local", format="%d"),
        "igreja": "Igreja local",
        "cod_denominacao": st.column_config.NumberColumn("Cód. Denominação", format="%d"),
        "denominacao": "Denominação",
    },
)
