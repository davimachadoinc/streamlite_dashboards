import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

st.set_page_config(
    page_title="Gerenciamento de Férias",
    page_icon="🏖️",
    layout="wide"
)

# ── Auth ───────────────────────────────────────────────────────────────────────
if not st.user.is_logged_in:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.image(
            "https://inchurch.com.br/wp-content/uploads/2024/09/inchurch-logo-svg.svg",
            width=240
        )
        st.title("Gerenciamento de Férias")
        st.markdown("---")
        st.write("Faça login com sua conta Google **@inchurch.com.br** para acessar o sistema.")
        if st.button("🔐 Entrar com Google", use_container_width=True):
            st.login()
    st.stop()

user_email = st.user.email.lower().strip()
user_name  = getattr(st.user, "name", user_email)

# ── Google Sheets ──────────────────────────────────────────────────────────────
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '1n-VTjTz90GBmtmLU8cxYtBtmTwn234NZT7UKFkl6eqY'

try:
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    service = build('sheets', 'v4', credentials=creds)
except KeyError:
    st.error("❌ Chave 'gcp_service_account' não encontrada nos secrets.")
    st.stop()
except Exception as e:
    st.error(f"❌ Erro ao carregar credenciais do Google Sheets: {e}")
    st.stop()


def chats_people(message, email):
    url = 'https://backoffice-dot-operations-407517.rj.r.appspot.com/api/v1/chats/direct-message/'  # noqa
    headers = {'Content-Type': 'application/json'}
    data = {"email": email, "text": message}
    requests.post(url, headers=headers, json=data)


def chats_channel(message):
    url = 'https://chat.googleapis.com/v1/spaces/AAQALAab39o/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=yW5wgfP7tBz5e4n6yxfjkPwB9KGoCueM5dEO6rmElng'  # noqa
    headers = {'Content-Type': 'application/json'}
    data = {"text": message}
    requests.post(url, headers=headers, json=data)


def ler_dados(nome_aba, intervalo):
    try:
        resultado = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{nome_aba}!{intervalo}'
        ).execute()
        return resultado.get('values', [])
    except Exception as e:
        st.error(f"Erro ao ler dados: {e}")
        return []


def escrever_dados(nome_aba, intervalo, valores):
    try:
        body = {'values': valores}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{nome_aba}!{intervalo}',
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
    except Exception as e:
        st.error(f"Erro ao escrever dados: {e}")


# ── Carregar dados ─────────────────────────────────────────────────────────────
marcados = ler_dados("Marcações", "A1:P400")
if not marcados:
    st.error("Sem acesso à planilha. Verifique se a service account tem permissão de Editor.")
    st.stop()
marcacoes = pd.DataFrame(marcados[1:], columns=marcados[0])
marcacoes_validas = marcacoes[marcacoes["Validado por DP"] != "Reprovado"]
alteradas = marcacoes_validas[marcacoes_validas["Alteração"] != ""]
marcacoes_validas = marcacoes_validas[~marcacoes_validas["ID"].isin(alteradas["Alteração"])]
marcacoes_validas = marcacoes_validas[marcacoes_validas["ID"] != ""]

dados_principal = ler_dados('colaboradores', 'A1:L400')
if not dados_principal:
    st.error("Sem acesso à planilha. Verifique se a service account tem permissão de Editor.")
    st.stop()
principal = pd.DataFrame(dados_principal[1:], columns=dados_principal[0])
principal = principal[principal['Situação do Contrato'] == 'ATIVO']
principal["Email Corporativo"] = principal["Email Corporativo"].str.lower().str.strip()

# ── Interface principal ────────────────────────────────────────────────────────
st.logo("https://inchurch.com.br/wp-content/uploads/2024/09/inchurch-logo-svg.svg")
st.title("Gerenciamento de Férias")

email_input = user_email
emails = principal["Email Corporativo"].tolist()
if email_input not in emails:
    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.error(f"❌ O e-mail **{email_input}** não tem acesso a este app.\n\nEntre em contato com o DP.")
        if st.button("↩️ Sair", use_container_width=True):
            st.logout()
    st.stop()

nome_marcador = principal[principal["Email Corporativo"] == email_input]["Nome Completo"].values[0]

with st.sidebar:
    st.markdown(
        f"<p style='color:#a0a0a0; font-size:0.82rem; margin-bottom:2px;'>👤 {user_name}</p>"
        f"<p style='color:#4c4c4c; font-size:0.75rem; margin-bottom:16px;'>{user_email}</p>",
        unsafe_allow_html=True,
    )
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        st.logout()


def enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str):  # noqa
    chats_colaborador = email_colaborador
    chats_marcador = email_input
    chats_gestor = email_gestor

    try:
        chats_channel(f"{ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]} teve suas férias marcadas por {nome_marcador}.")  # noqa
        chats_people(f"Olá, {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}!\nVocê teve suas férias marcadas por {nome_marcador}.", chats_colaborador)  # noqa
        if p2_inicio_str is None:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str}.", chats_colaborador)
        elif p3_inicio_str is None:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str} e {p2_inicio_str} a {p2_fim_str}.", chats_colaborador)  # noqa
        else:
            chats_people(f"Período: {p1_inicio_str} a {p1_fim_str}, {p2_inicio_str} a {p2_fim_str} e {p3_inicio_str} a {p3_fim_str}.", chats_colaborador)  # noqa

        if chats_marcador == chats_gestor:
            chats_people(f"Olá, {ferias[ferias['Email Corporativo'] == email_colaborador]['GESTOR IMEDIATO'].values[0]}!\n{nome_marcador} marcou férias para {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_marcador)  # noqa
        else:
            chats_people(f"Olá, {nome_marcador}!\nVocê marcou férias para {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_marcador)  # noqa
            chats_people(f"Olá, {ferias[ferias['Email Corporativo'] == email_colaborador]['GESTOR IMEDIATO'].values[0]}!\n{nome_marcador} marcou férias para {ferias[ferias['Email Corporativo'] == email_colaborador]['Nome Completo'].values[0]}.", chats_gestor)  # noqa
    except Exception as e:
        st.error(f"Erro ao enviar mensagem no Chats: {e}")
        chats_channel(f"Erro ao enviar mensagem no Chats: {e}.\nEmail do colaborador: {email_colaborador}.\nNome de quem marcou: {nome_marcador}")  # noqa


def marcar_ferias():
    if email_colaborador != 'Todos':
        contrato_colaborador = ferias[ferias["Email Corporativo"] == email_colaborador]["Contrato"].values[0]  # noqa

        if contrato_colaborador == 'PJ':
            dias_abono = None
            abono = 'SEM abono'
            saldo = int(principal[principal["Email Corporativo"] == email_colaborador]["Saldo de dias"].values[0])  # noqa
            st.info(f"Saldo de dias para férias: {saldo} dias.")
            st.info("Para PJ, as férias poderão durar de 5 a 30 dias.")
            janelas = st.radio("Escolha a janela de férias:", ["janela única", "janela dupla", "janela tripla"])  # noqa

            if janelas == "janela única":
                p1_inicio = st.date_input("Início das férias P1:")
                p1_duração = st.selectbox("Duração das férias P1:", list(range(5, 31)))
                p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = p2_fim = p3_inicio = p3_fim = None
                saldo -= p1_duração

            elif janelas == "janela dupla":
                p1_inicio = st.date_input("Início das férias P1:")
                p1_duração = st.selectbox("Duração das férias P1:", list(range(5, 26)))
                p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = st.date_input("Início das férias P2:")
                p2_duração = st.selectbox("Duração das férias P2:", list(range(5, 31 - p1_duração)))
                p2_fim = p2_inicio + pd.Timedelta(days=p2_duração - 1)  # type: ignore
                st.warning(f"Duração P2: {p2_duração} dias.")
                st.success(f"Último dia das férias P2: {p2_fim}")
                p3_inicio = p3_fim = None
                saldo -= (p1_duração + p2_duração)

            else:
                p1_inicio = st.date_input("Início das férias P1:")
                p1_duração = st.selectbox("Duração das férias P1:", list(range(5, 21)))
                p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P1: {p1_fim}")
                p2_inicio = st.date_input("Início das férias P2:")
                p2_duração = st.selectbox("Duração das férias P2:", list(range(5, 26 - p1_duração)))
                p2_fim = p2_inicio + pd.Timedelta(days=p2_duração - 1)  # type: ignore
                st.success(f"Último dia das férias P2: {p2_fim}")
                p3_inicio = st.date_input("Início das férias P3:")
                p3_duração = st.selectbox("Duração das férias P3:", list(range(5, 31 - p1_duração - p2_duração)))
                p3_fim = p3_inicio + pd.Timedelta(days=p3_duração - 1)  # type: ignore
                st.warning(f"Duração P3: {p3_duração} dias.")
                st.success(f"Último dia das férias P3: {p3_fim}")
                saldo -= (p1_duração + p2_duração + p3_duração)

            if saldo < 0:
                st.warning(f"Saldo após férias: {saldo} dias. ATENÇÃO: saldo negativo. Favor verificar com DP.")
            else:
                st.success(f"Saldo após férias: {saldo} dias.")

        else:
            fim_pa1 = principal[principal["Email Corporativo"] == email_colaborador]["Fim PA1"].values[0]  # noqa
            fim_pa1_raw = pd.to_datetime(fim_pa1, errors='coerce', dayfirst=True)
            if pd.isna(fim_pa1_raw):
                fim_pa1 = None
            elif fim_pa1_raw.tzinfo is not None:
                fim_pa1 = fim_pa1_raw.tz_convert(None)
            else:
                fim_pa1 = fim_pa1_raw.tz_localize(None)

            if fim_pa1 is not None and pd.Timestamp.now().tz_localize(None) < fim_pa1:
                st.warning(f"Você não pode marcar férias para este colaborador. O período atual ainda não está completo. A marcação poderá ser feita a partir de: {fim_pa1 + pd.Timedelta(days=1)}. Para mais informações, entre em contato com DP.")  # noqa
            else:
                abono = st.radio("Escolha o ABONO (abono é a conversão de um terço das férias em dinheiro):", ["COM abono", "SEM abono"])  # noqa

                if abono == "COM abono":
                    st.info("Para férias com abono, a duração total deve ser 20 ou 25 dias.")
                    janelas = st.radio("Escolha a janela de férias:", ["janela única", "janela dupla"])
                    dias_abono = st.selectbox("Escolha a quantidade de dias para abono:", [5, 10])

                    if janelas == "janela única":
                        p1_inicio = st.date_input("Início das férias P1:")
                        p1_duração = 30 - dias_abono
                        p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = p2_fim = p3_inicio = p3_fim = None
                    else:
                        p1_inicio = st.date_input("Início das férias P1:")
                        opcoes_p1 = list(range(5, 21 - dias_abono)) if dias_abono == 5 else [4, 5, 14, 15]
                        p1_duração = st.selectbox("Duração das férias P1:", opcoes_p1)
                        p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = st.date_input("Início das férias P2:")
                        p2_duração = 30 - p1_duração - dias_abono
                        p2_fim = p2_inicio + pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.warning(f"Duração P2: {p2_duração} dias.")
                        st.success(f"Último dia das férias P2: {p2_fim}")
                        p3_inicio = p3_fim = None

                else:
                    dias_abono = None
                    st.info("Para férias sem abono, a duração total deve ser 30 dias.")
                    janelas = st.radio("Escolha a janela de férias:", ["janela única", "janela dupla", "janela tripla"])  # noqa

                    if janelas == "janela única":
                        p1_inicio = st.date_input("Início das férias P1:")
                        p1_duração = 30
                        p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = p2_fim = p3_inicio = p3_fim = None
                    elif janelas == "janela dupla":
                        p1_inicio = st.date_input("Início das férias P1:")
                        p1_duração = st.selectbox("Duração das férias P1:", list(range(5, 26)))
                        p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = st.date_input("Início das férias P2:")
                        p2_duração = 30 - p1_duração
                        p2_fim = p2_inicio + pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.warning(f"Duração P2: {p2_duração} dias.")
                        st.success(f"Último dia das férias P2: {p2_fim}")
                        p3_inicio = p3_fim = None
                    else:
                        p1_inicio = st.date_input("Início das férias P1:")
                        p1_duração = st.selectbox("Duração das férias P1:", list(range(5, 21)))
                        p1_fim = p1_inicio + pd.Timedelta(days=p1_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P1: {p1_fim}")
                        p2_inicio = st.date_input("Início das férias P2:")
                        p2_duração = st.selectbox("Duração das férias P2:", list(range(5, 26 - p1_duração)))
                        p2_fim = p2_inicio + pd.Timedelta(days=p2_duração - 1)  # type: ignore
                        st.success(f"Último dia das férias P2: {p2_fim}")
                        p3_inicio = st.date_input("Início das férias P3:")
                        p3_duração = 30 - p1_duração - p2_duração
                        p3_fim = p3_inicio + pd.Timedelta(days=p3_duração - 1)  # type: ignore
                        st.warning(f"Duração P3: {p3_duração} dias.")
                        st.success(f"Último dia das férias P3: {p3_fim}")

        if st.button("Marcar Férias"):
            data_marcacao = pd.Timestamp.now().strftime("%d/%m/%Y")
            tamanho = marcacoes["ID"].tolist()
            id = len(tamanho)
            try:
                p1_inicio_str = p1_inicio.strftime("%d/%m/%Y")  # type: ignore
                p1_fim_str = p1_fim.strftime("%d/%m/%Y")  # type: ignore
                p2_inicio_str = p2_inicio.strftime("%d/%m/%Y") if p2_inicio else None  # type: ignore
                p2_fim_str = p2_fim.strftime("%d/%m/%Y") if p2_fim else None  # type: ignore
                p3_inicio_str = p3_inicio.strftime("%d/%m/%Y") if p3_inicio else None  # type: ignore
                p3_fim_str = p3_fim.strftime("%d/%m/%Y") if p3_fim else None  # type: ignore

                dados_marcacao = [
                    id, data_marcacao, email_input, email_colaborador,
                    ferias[ferias["Email Corporativo"] == email_colaborador]["Nome Completo"].values[0],
                    ferias[ferias["Email Corporativo"] == email_colaborador]["Time"].values[0],
                    abono, dias_abono,
                    p1_inicio_str, p1_fim_str,
                    p2_inicio_str, p2_fim_str,
                    p3_inicio_str, p3_fim_str,
                    alteracao
                ]
                num_linhas_existentes = len(tamanho) + 1
                intervalo = f"A{num_linhas_existentes + 1}:N{num_linhas_existentes + 1}"
                escrever_dados("Marcações", intervalo, [dados_marcacao])
                st.success("Férias marcadas com sucesso!")
                enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str)  # noqa
            except Exception as e:
                st.error(f"Erro ao marcar férias: {e}.")
                chats_channel(f"Erro ao marcar férias: {e}. Marcador {email_input}")


# ── UI ─────────────────────────────────────────────────────────────────────────
opcao = st.radio("O que você deseja fazer?", [
    "Consultar Férias", "Marcar Novas Férias ou Alterar Férias Marcadas"])

if opcao == "Consultar Férias":
    times = ['Todos'] + list(marcacoes_validas["Time"].unique())
    time = st.selectbox("Selecione o time:", times, index=0)
    ferias = marcacoes_validas[marcacoes_validas["Time"] == time] if time != 'Todos' else marcacoes_validas
    colaboradores = ['Todos'] + list(ferias["Email do colaborador"].unique())
    email = st.selectbox("Selecione o Email do colaborador:", colaboradores, index=0)
    if email != 'Todos':
        ferias = ferias[ferias["Email do colaborador"] == email]
    st.dataframe(ferias.drop(columns=["Email do colaborador", "Alteração"]))

if opcao == "Marcar Novas Férias ou Alterar Férias Marcadas":
    alteracao = None
    dias_abono = None
    times = ['Todos'] + list(principal["Time"].unique())
    time = st.selectbox("Selecione o time:", times, index=0)
    ferias = principal[principal["Time"] == time] if time != 'Todos' else principal

    colaboradores = ['Todos'] + list(ferias["Email Corporativo"].unique())
    email_colaborador = st.selectbox("Selecione o Email do colaborador:", colaboradores, index=0)

    if email_colaborador != 'Todos':
        nome_gestor = ferias[ferias["Email Corporativo"] == email_colaborador]["GESTOR IMEDIATO"].values[0]  # noqa
        email_gestor = principal[principal["Nome Completo"] == nome_gestor]["Email Corporativo"].values[0]  # noqa
    else:
        nome_gestor = email_gestor = None

    if nome_gestor is not None and nome_gestor != nome_marcador:
        resposta = st.selectbox(
            "Você não é o gestor imediato deste colaborador. Tem certeza que deseja continuar?",
            ["Não", "Sim"]
        )
        continuar = resposta == "Sim"
        if continuar:
            st.info("Ok, você marcará férias de um colaborador sem ser o gestor dele.")
    else:
        continuar = True

    if not continuar:
        st.info("Selecione outro colaborador.")
    else:
        if email_colaborador in marcacoes_validas["Email do colaborador"].values:
            st.warning("Este colaborador já tem férias marcadas. Deseja alterá-las ou marcar novas?")
            alterar = st.radio("Escolha uma opção:", ["Alterar", "Marcar Novas"])

            if alterar == "Marcar Novas":
                alteracao = None
                marcar_ferias()
            else:
                st.dataframe(marcacoes_validas[marcacoes_validas["Email do colaborador"] == email_colaborador])  # noqa
                alteracao = st.selectbox(
                    "Selecione o ID da marcação que deseja alterar:",
                    marcacoes_validas[marcacoes_validas["Email do colaborador"] == email_colaborador]["ID"].tolist()  # noqa
                )
                alterar_df = marcacoes_validas[marcacoes_validas["ID"] == alteracao]

                abono = alterar_df["Abono"].values[0]
                if abono == "COM abono":
                    periodo = st.radio("Qual período deseja alterar?", ["P1", "P2"])
                    agora = pd.Timestamp.now().tz_localize(None)
                    data_inicio = pd.to_datetime(alterar_df[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True).tz_localize(None)  # noqa

                    if agora > data_inicio:
                        st.warning("Você não pode alterar férias que já começaram.")
                    else:
                        inicio = st.date_input(f"Início das férias {periodo}:")
                        duracao = pd.to_datetime(alterar_df[f"Fim {periodo}"].values[0], errors='coerce', dayfirst=True) - pd.to_datetime(alterar_df[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True)  # noqa
                        fim = inicio + pd.Timedelta(duracao)  # type: ignore
                        st.success(f"Duração: {duracao.days + 1} dias. Último dia: {fim}")
                        if periodo == "P1":
                            p1_inicio, p1_fim = inicio, fim
                            p2_inicio = pd.to_datetime(alterar_df["Início P2"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P2"].values[0] != "" else None  # noqa
                            p2_fim = pd.to_datetime(alterar_df["Fim P2"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P2"].values[0] != "" else None  # noqa
                            p3_inicio = p3_fim = None
                        else:
                            p1_inicio = pd.to_datetime(alterar_df["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar_df["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio, p2_fim = inicio, fim
                            p3_inicio = p3_fim = None
                else:
                    st.info("Para férias sem abono, a duração total deve ser 30 dias.")
                    periodo = st.radio("Qual período deseja alterar?", ["P1", "P2", "P3"])

                    if pd.Timestamp.now() > pd.to_datetime(alterar_df[f"Início {periodo}"].values[0], errors='coerce', dayfirst=True):  # noqa
                        st.warning("Você não pode alterar férias que já começaram.")
                    else:
                        inicio = st.date_input(f"Início das férias {periodo}:")
                        duracao = st.selectbox(f"Duração das férias {periodo}:", list(range(5, 31)))
                        fim = inicio + pd.Timedelta(days=duracao - 1)  # type: ignore
                        st.success(f"Último dia das férias {periodo}: {fim}")
                        if periodo == "P1":
                            p1_inicio, p1_fim = inicio, fim
                            p2_inicio = pd.to_datetime(alterar_df["Início P2"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P2"].values[0] != "" else None  # noqa
                            p2_fim = pd.to_datetime(alterar_df["Fim P2"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P2"].values[0] != "" else None  # noqa
                            p3_inicio = pd.to_datetime(alterar_df["Início P3"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P3"].values[0] != "" else None  # noqa
                            p3_fim = pd.to_datetime(alterar_df["Fim P3"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P3"].values[0] != "" else None  # noqa
                        elif periodo == "P2":
                            p1_inicio = pd.to_datetime(alterar_df["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar_df["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio, p2_fim = inicio, fim
                            p3_inicio = pd.to_datetime(alterar_df["Início P3"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P3"].values[0] != "" else None  # noqa
                            p3_fim = pd.to_datetime(alterar_df["Fim P3"].values[0], errors='coerce', dayfirst=True) if alterar_df["Início P3"].values[0] != "" else None  # noqa
                        else:
                            p1_inicio = pd.to_datetime(alterar_df["Início P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p1_fim = pd.to_datetime(alterar_df["Fim P1"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_inicio = pd.to_datetime(alterar_df["Início P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p2_fim = pd.to_datetime(alterar_df["Fim P2"].values[0], errors='coerce', dayfirst=True)  # noqa
                            p3_inicio, p3_fim = inicio, fim

                if st.button("Salvar Alteração"):
                    data_marcacao = pd.Timestamp.now().strftime("%d/%m/%Y")
                    tamanho = marcacoes["ID"].tolist()
                    id = len(tamanho)
                    try:
                        p1_inicio_str = p1_inicio.strftime("%d/%m/%Y")  # type: ignore
                        p1_fim_str = p1_fim.strftime("%d/%m/%Y")  # type: ignore
                        p2_inicio_str = p2_inicio.strftime("%d/%m/%Y") if p2_inicio else None  # type: ignore
                        p2_fim_str = p2_fim.strftime("%d/%m/%Y") if p2_fim else None  # type: ignore
                        p3_inicio_str = p3_inicio.strftime("%d/%m/%Y") if p3_inicio else None  # type: ignore
                        p3_fim_str = p3_fim.strftime("%d/%m/%Y") if p3_fim else None  # type: ignore

                        dados_marcacao = [
                            id, data_marcacao, email_input, email_colaborador,
                            ferias[ferias["Email Corporativo"] == email_colaborador]["Nome Completo"].values[0],
                            ferias[ferias["Email Corporativo"] == email_colaborador]["Time"].values[0],
                            abono, dias_abono,
                            p1_inicio_str, p1_fim_str,
                            p2_inicio_str, p2_fim_str,
                            p3_inicio_str, p3_fim_str,
                            alteracao
                        ]
                        num_linhas_existentes = len(tamanho) + 1
                        intervalo = f"A{num_linhas_existentes + 1}:N{num_linhas_existentes + 1}"
                        escrever_dados("Marcações", intervalo, [dados_marcacao])
                        st.success("Alteração salva com sucesso!")
                        enviar_chats(p1_inicio_str, p1_fim_str, p2_inicio_str, p2_fim_str, p3_inicio_str, p3_fim_str)  # noqa
                    except Exception as e:
                        st.error(f"Erro ao salvar alteração: {e}.")
                        chats_channel(f"Erro ao salvar alteração: {e}. Marcador {email_input}")
        else:
            marcar_ferias()
