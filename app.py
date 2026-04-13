import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from serpapi import GoogleSearch
import io
import re
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="Global Marketplace Intelligence", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO COMPLETO ---
idiomas = {
    "Brasil 🇧🇷": {
        "titulo": "🚀 Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key",
        "help_chave": "A SerpApi Key é o código que permite ao sistema pesquisar preços reais no Google Shopping. Você a obtém gratuitamente criando uma conta em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave",
        "msg_ativado": "Sistema Ativado!",
        "bling_token": "Token API Bling V3:",
        "ajuda_header": "📖 Legenda",
        "ajuda_corpo": "✅ **Vencendo**: Seu preço é o menor.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Concorrência abaixo do custo.",
        "termos_header": "### ⚖️ Termos de Uso e Instruções",
        "termos_corpo": "A sua planilha deve conter: **Nome do Produto, Custo e Quantidade**. O EAN é recomendado.\n\n- Dados coletados em tempo real.\n- O usuário deve conferir os resultados antes de mudar preços.\n- Responsabilidade exclusiva do cliente.",
        "termos_check": "Eu aceito os Termos de Uso e a responsabilidade pelas decisões.",
        "termos_aviso": "👉 Aceite os termos para desbloquear o sistema.",
        "passo1": "1️⃣ Carregamento de Produtos",
        "btn_importar": "📥 Importar do Bling",
        "btn_excel": "Suba seu arquivo Excel",
        "passo2": "2️⃣ Estratégia e Análise",
        "btn_analisar": "🚀 INICIAR ANÁLISE REAL",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Baixar Resultados em Excel",
        "sinc_btn": "Aceitar sugestões de preço para o bling e atualizar na plataforma",
        "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil"
    },
    "Portugal 🇵🇹": {
        "titulo": "🚀 Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi",
        "help_chave": "A SerpApi Key é o código que permite ao sistema pesquisar preços reais no Google Shopping. Pode obter uma gratuitamente criando conta em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave",
        "msg_ativado": "Sistema Ativado!",
        "ajuda_header": "📖 Legenda",
        "ajuda_corpo": "✅ **A Vencer**: O seu preço é o mais baixo.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Crítico**: Preços abaixo do custo.",
        "termos_header": "### ⚖️ Termos de Utilização e Instruções",
        "termos_corpo": "A sua folha de cálculo deve conter: **Nome, Custo e Quantidade**.\n\n- Dados recolhidos em tempo real.\n- Obrigação de conferência dos resultados.\n- Responsabilidade exclusiva do cliente.",
        "termos_check": "Aceito os Termos de Utilização e a responsabilidade total.",
        "termos_aviso": "👉 Aceite os termos para desbloquear o sistema.",
        "passo1": "1️⃣ Carregamento de Produtos",
        "btn_excel": "Carregue o seu ficheiro Excel",
        "passo2": "2️⃣ Estratégia e Análise",
        "btn_analisar": "🚀 INICIAR ANÁLISE DE MERCADO",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Descarregar Resultados em Excel",
        "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal"
    },
    "USA 🇺🇸": {
        "titulo": "🚀 USA Marketplace Intelligence",
        "label_chave": "SerpApi Key",
        "help_chave": "The SerpApi Key is a code that allows the system to search real prices on Google Shopping. You can get one for free at SerpApi.com.",
        "btn_confirmar": "Confirm Key",
        "msg_ativado": "System Activated!",
        "ajuda_header": "📖 Legend",
        "ajuda_corpo": "✅ **Winning**: Your price is the lowest.\n\n⚠️ **Expensive**: Above market price.\n\n🟥 **Alert**: Market price below cost.",
        "termos_header": "### ⚖️ Terms of Use and Instructions",
        "termos_corpo": "Your spreadsheet must include: **Name, Cost, and Quantity**.\n\n- Real-time data collection.\n- User MUST validate results before any changes.\n- Full responsibility belongs to the client.",
        "termos_check": "I accept the Terms of Use and take full responsibility.",
        "termos_aviso": "👉 You must accept terms to unlock the system.",
        "passo1": "1️⃣ Product Upload",
        "btn_excel": "Upload your Excel file",
        "passo2": "2️⃣ Strategy & Analysis",
        "btn_analisar": "🚀 START MARKET ANALYSIS",
        "invest": "Total Investment", "lucro": "Projected Profit", "margem": "Avg Margin",
        "download_btn": "Download Results (Excel)",
        "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States"
    }
}

# --- FUNÇÃO DE E-MAIL ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    dest = "contato@vembrincarcomagente.com"
    try:
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, dest, f"[{tipo}] - {n}"
        msg.attach(MIMEText(f"User: {n}\nEmail: {e}\n\nMessage:\n{m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- SIDEBAR DINÂMICA ---
with st.sidebar:
    st.header("🌍 Selection / Seleção")
    pais_sel = st.selectbox("Market / Mercado:", list(idiomas.keys()))
    t = idiomas[pais_sel] 
    
    st.divider()
    st.header("🔑 Activation / Ativação")
    
    # CAMPO COM A INTERROGAÇÃO DE AJUDA SOLICITADA
    api_key_input = st.text_input(t["label_chave"], type="password", help=t["help_chave"])
    
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success(t["msg_ativado"])

    if "Brasil" in pais_sel:
        st.divider()
        st.header("🔌 Bling V3")
        bling_token = st.text_input(t["bling_token"], type="password")
    else: bling_token = None

    if "Portugal" in pais_sel:
        st.divider()
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "Toda a União Europeia"])
    
    st.divider()
    st.header("💬 Support / Suporte")
    user_q = st.text_input("?")
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            n, e, m = st.text_input("Name/Nome"), st.text_input("Email"), st.text_area("Message/Mensagem")
            if st.form_submit_button("Send/Enviar"):
                if enviar_email_log(n, e, m, "SUPORTE"): st.success("OK!")

# --- CORPO PRINCIPAL ---
st.title(t["titulo"])
st.markdown(t["termos_header"])
st.info(t["termos_corpo"])
aceite = st.checkbox(t["termos_check"])

if not aceite:
    st.warning(t["termos_aviso"])
    st.stop()

st.divider()

# --- PASSO 1: CARREGAMENTO ---
st.markdown(f"### {t['passo1']}")
df_base = pd.DataFrame()

if "Brasil" in pais_sel:
    fonte = st.radio("Fonte:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)
    if fonte == "Bling (API V3)":
        if st.button(t["btn_importar"]):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                    st.success("OK!")
            except: st.error("Error")
    else:
        uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
        if uploaded_file:
            df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: col_n = st.selectbox("NOME:", cols); with c2: col_c = st.selectbox("CUSTO:", cols); with c3: col_q = st.selectbox("QTDE:", cols); with c4: col_l = st.selectbox("LINHA:", ["Nenhuma"] + cols); with c5: col_e = st.selectbox("EAN:", ["Não possuo"] + cols)
            df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
            df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"; df_base['ID'] = 0
else:
    uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NAME:", cols); with c2: col_c = st.selectbox("COST:", cols); with c3: col_q = st.selectbox("QTY:", cols); with c4: col_l = st.selectbox("LINE:", ["None"] + cols); with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "None" else "General"; df_base['ID'] = 0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown(f"### {t['passo2']}")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("% Tax", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("% Markup", 0, 500, 70) / 100
    
    if st.button(t["btn_analisar"]):
        if "api_key" not in st.session_state: st.error("API Key!")
        else:
            with st.spinner('...'):
                df = df_base.copy(); res_m, res_l = [], []
                loc_f = t["loc"]
                if "Portugal" in pais_sel and scope_pt == "Toda a União Europeia": loc_f = "Western Europe"

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

# --- PASSO 3: RESULTADOS ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader(t["passo3"])
    
    c1, c2, c3 = st.columns(3)
    c1.metric(t["invest"], f"{t['moeda']} {df['Custo'].sum():,.2f}")
    c2.metric(t["lucro"], f"{t['moeda']} {df['Lucro Total'].sum():,.2f}")
    c3.metric(t["margem"], f"{df['Margem %'].mean():.2f}%")
    
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({
        'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'
    }))

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df.to_excel(wr, index=False)
    st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analysis.xlsx")

    if "Brasil" in pais_sel and fonte == "Bling (API V3)":
        st.divider()
        if st.button(t["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("OK!")
