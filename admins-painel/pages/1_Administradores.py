"""
pages/1_Administradores.py
Quem tem acesso ao painel de controle, ordenado pelo último login. Filtro por Código Local / Denominação.
"""
import streamlit as st

st.set_page_config(page_title="Admins do Painel | InChurch", page_icon="🛡️", layout="wide")

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
        "**Último login** = última data com login no canal *control_panel* "
        "(`view_user_login_log`). Só guarda o dia, sem hora.\n\n"
        "**Administrador** (`view_basicuser.user_type`) = Admin, Admin de equipe e Regional; "
        "Membro de equipe só se tiver registro em `view_admin_access`.\n\n"
        "**Nível** = maior nível do usuário em `view_admin_access` (— se não tiver registro).\n\n"
        "**Código Local** = `tertiarygroup_id` · **Denominação** = `subgroup_id`."
    )

st.markdown("<h1>Administradores do <span>Painel</span></h1>", unsafe_allow_html=True)

with st.spinner("Carregando dados..."):
    admins = load_admins()
    igrejas = load_igrejas()

admins = admins.merge(igrejas[["cod_local", "igreja"]].drop_duplicates("cod_local"), on="cod_local", how="left")

c1, c2, c3 = st.columns([1, 1, 2])
cod_local = c1.text_input("Código Local", placeholder="Ex.: 32187", key="filtro_local")
cod_denom = c2.text_input("Código de Denominação", placeholder="Ex.: 3987", key="filtro_denom")
niveis = sorted(admins["nivel"].dropna().unique())
sel = c3.multiselect("Nível de acesso", niveis, placeholder="Todos")

df = filtrar_codigos(admins, cod_local, cod_denom)
if sel:
    df = df[df["nivel"].isin(sel)]
df = df.sort_values("ultimo_login", ascending=False, na_position="last")

total = len(df)
com_login = int(df["ultimo_login"].notna().sum())
m1, m2, m3 = st.columns(3)
m1.metric("Administradores", f"{total:,}".replace(",", "."))
m2.metric("Já logaram no painel", f"{com_login:,}".replace(",", "."))
m3.metric("Nunca logaram", f"{total - com_login:,}".replace(",", "."))

st.dataframe(
    df[["nome", "email", "tipo", "nivel", "ultimo_login", "cod_local", "igreja", "cod_denominacao"]],
    use_container_width=True,
    hide_index=True,
    height=620,
    column_config={
        "nome": "Nome",
        "email": "E-mail",
        "tipo": "Tipo",
        "nivel": "Nível de acesso",
        "ultimo_login": st.column_config.DateColumn("Último login no painel", format="DD/MM/YYYY"),
        "cod_local": st.column_config.NumberColumn("Cód. Local", format="%d"),
        "igreja": "Igreja",
        "cod_denominacao": st.column_config.NumberColumn("Cód. Denominação", format="%d"),
    },
)
