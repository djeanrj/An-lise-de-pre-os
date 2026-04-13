import streamlit as st
import pandas as pd
import requests
from serpapi import GoogleSearch
import io
import re
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="Global Price Intelligence", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO TOTALMENTE ISOLADO ---
idiomas = {
    "PT": {
        "bandeira": "🇵🇹",
        "titulo": "🚀 Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi",
        "help_chave": "A SerpApi Key permite pesquisar preços reais no Google Shopping. Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave",
        "ajuda_header": "📖 Legenda",
        "ajuda_corpo": "✅ **A Vencer**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Crítico**: Abaixo do custo.",
        "suporte_header": "💬 Suporte",
        "suporte_label": "Como podemos ajudar?",
        "termos_header": "### ⚖️ Termos de Utilização",
        "termos_check": "Aceito os Termos de Utilização.",
        "termos_aviso": "👉 Aceite os termos para continuar.",
        "passo1": "1️⃣ Carregamento de Produtos",
        "btn_excel": "Carregar Ficheiro Excel",
        "mapeamento": "Identifique as colunas do seu ficheiro:",
        "passo2": "2️⃣ Estratégia e Análise",
        "label_imposto": "IVA (%)",
        "label_markup": "Margem de Aumento (%)",
        "btn_analisar": "🚀 INICIAR ANÁLISE DE MERCADO",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Descarregar Excel",
        "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal"
    },
    "BR": {
        "bandeira": "🇧🇷",
        "titulo": "🚀 Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key",
        "help_chave": "Código para pesquisar preços reais no Google Shopping. Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave",
        "ajuda_header": "📖 Legenda",
        "ajuda_corpo": "✅ **Vencendo**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Abaixo do custo.",
        "suporte_header": "💬 Suporte",
        "suporte_label": "Como podemos ajudar?",
        "termos_header": "### ⚖️ Termos de Uso",
        "termos_check": "Eu aceito os Termos de Uso.",
        "termos_aviso": "👉 Aceite os termos para prosseguir.",
        "passo1": "1️⃣ Carregamento de Produtos",
        "btn_excel": "Subir Arquivo Excel",
        "mapeamento": "Mapeie as colunas do seu arquivo:",
        "passo2": "2️⃣ Estratégia e Análise",
        "label_imposto": "Imposto (%)",
        "label_markup": "Aumento Padrão (%)",
        "btn_analisar": "🚀 INICIAR ANÁLISE REAL",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Baixar Excel",
        "sinc_btn": "Aceitar sugestões de preço para o bling",
        "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil"
    },
    "US": {
        "bandeira": "🇺🇸",
        "titulo": "🚀 USA Marketplace Intelligence",
        "label_chave": "SerpApi Key",
        "help_chave": "Code for real-time prices. Get it at SerpApi.com.",
        "btn_confirmar": "Confirm Key",
        "ajuda_header": "📖 Legend",
        "ajuda_corpo": "✅ **Winning**: Best price.\n\n⚠️ **Expensive**: Above market.\n\n🟥 **Alert**: Below cost.",
        "suporte_header": "💬 Support",
        "suporte_label": "How can we help?",
        "termos_header": "### ⚖️ Terms of Use",
        "termos_check": "I accept the Terms.",
        "termos_aviso": "👉 Accept terms to unlock.",
        "passo1": "1️⃣ Data Upload",
        "btn_excel": "Upload Excel file",
        "mapeamento": "Map your columns:",
        "passo2": "2️⃣ Strategy & Analysis",
        "label_imposto": "Tax (%)",
        "label_markup": "Markup (%)",
        "btn_analisar": "🚀 START MARKET ANALYSIS",
        "invest": "Investment", "lucro": "Projected Profit", "margem": "Avg Margin",
        "download_btn": "Download Excel",
        "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States"
    }
}

# --- DETECÇÃO REAL DE PAÍS POR IP ---
if "pais_key" not in st.session_state:
    try:
        res = requests.get("https://ipapi.co", timeout=3).json()
        cc = res.get("country_code", "BR")
        st.session_state.pais_key = cc if cc in idiomas else "BR"
    except:
        st.session_state.pais_key = "BR"

# --- FUNÇÃO DE E-MAIL ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    dest = "contato@vembrincarcomagente.com"
    try:
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, dest, f"[{tipo}] - {n}"
        msg.attach(MIMEText(f"Nome: {n}\nEmail: {e}\n\nMsg: {m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- SIDEBAR: SELETOR VISUAL POR BOTÕES ---
with st.sidebar:
    st.header("🌎 Market / Mercado")
    
    # Criando botões lado a lado para as bandeiras aparecerem grandes e claras
    col_b1, col_b2, col_b3 = st.columns(3)
    if col_b1.button("🇧🇷", help="Brasil"): st.session_state.pais_key = "BR"
    if col_b2.button("🇵🇹", help="Portugal"): st.session_state.pais_key = "PT"
    if col_b3.button("🇺🇸", help="USA"): st.session_state.pais_key = "US"
    
    t = idiomas[st.session_state.pais_key]
    st.write(f"**{t['bandeira']} {st.session_state.pais_key}**")
    
    st.divider()
    st.header("🔑 Activation")
    api_key_input = st.text_input(t["label_chave"], type="password", help=t["help_chave"])
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success("OK!")

    if st.session_state.pais_key == "PT":
        st.divider()
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "Toda a União Europeia"])
    
    st.divider()
    st.header(t["ajuda_header"])
    st.info(t["ajuda_corpo"])

    st.divider()
    st.header(t["suporte_header"])
    user_q = st.text_input(t["suporte_label"])
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            n, e, m = st.text_input("Nome"), st.text_input("Email"), st.text_area("Mensagem", value=user_q)
            if st.form_submit_button("Enviar"):
                if enviar_email_log(n, e, m, "SUPORTE"): st.success("✅")

# --- CORPO PRINCIPAL ---
st.title(t["titulo"])
st.markdown(t["termos_header"])
aceite = st.checkbox(t["termos_check"])

if not aceite:
    st.warning(t["termos_aviso"])
    st.stop()

st.divider()
st.markdown(f"### {t['passo1']}")
df_base = pd.DataFrame()

if st.session_state.pais_key == "BR":
    fonte = st.radio("Fonte:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)
    if fonte == "Bling (API V3)":
        bling_token = st.text_input("Bling Token:", type="password")
        if st.button("📥 Importar"):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                    st.success("OK!")
            except: st.error("Erro")
    else:
        uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
        if uploaded_file:
            df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
            st.write(t["mapeamento"])
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: col_n = st.selectbox("NOME:", cols)
            with c2: col_c = st.selectbox("CUSTO:", cols)
            with c3: col_q = st.selectbox("QTDE:", cols)
            with c4: col_l = st.selectbox("LINHA:", ["Nenhuma"] + cols)
            with c5: col_e = st.selectbox("EAN:", ["Não possuo"] + cols)
            df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
            df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"; df_base['ID'] = 0
else:
    uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        st.write(t["mapeamento"])
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NAME:", cols)
        with c2: col_c = st.selectbox("COST:", cols)
        with c3: col_q = st.selectbox("QTY:", cols)
        with c4: col_l = st.selectbox("LINE:", ["None"] + cols)
        with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "None" else "General"; df_base['ID'] = 0

# --- ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown(f"### {t['passo2']}")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input(t["label_imposto"], 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input(t["label_markup"], 0, 500, 70) / 100
    if st.button(t["btn_analisar"]):
        if "api_key" not in st.session_state: st.error("Key!")
        else:
            with st.spinner('...'):
                df = df_base.copy(); res_m, res_l = [], []
                loc_f = t["loc"]
                if st.session_state.pais_key == "PT" and scope_pt == "Toda a União Europeia": loc_f = "Western Europe"
                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": t["domain"], "hl": t["lang"][:2], "gl": t["gl"], "location": loc_f, "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "N/A"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            if any(x in it.get('title','').lower() for x in ['peça','manual','spare']): continue
                            if t["moeda"] not in str(it.get('price','')): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.15): validos.append({"p": round(v,2), "l":it.get('source')})
                            except: continue
                        if validos: b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                df['Mercado'], df['Loja Líder'] = res_m, res_l
                df['Seu Preço'] = round(df['Custo'] * (1 + markup_padrao), 2)
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = round((((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100, 2)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Situação'] = df.apply(lambda x: f"🟥" if x['Mercado'] < x['Custo'] else (f"⚠️" if x['Seu Preço'] > x['Mercado'] else f"✅"), axis=1)
                st.session_state.df_final = df

if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader(t["passo3"])
    c1, c2, c3 = st.columns(3)
    c1.metric(t["invest"], f"{t['moeda']} {df['Custo'].sum():,.2f}")
    c2.metric(t["lucro"], f"{t['moeda']} {df['Lucro Total'].sum():,.2f}")
    c3.metric(t["margem"], f"{df['Margem %'].mean():.2f}%")
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'}))
    
    st.divider()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df.to_excel(wr, index=False)
    st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analysis.xlsx")

    if st.session_state.pais_key == "BR" and fonte == "Bling (API V3)":
        if st.button(t["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("OK!")
