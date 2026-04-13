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

# --- DICIONÁRIO DE TRADUÇÃO E CONFIGURAÇÃO ---
idiomas = {
    "Brasil 🇧🇷": {
        "titulo": "🚀 Inteligência de Mercado Brasil + Bling Sync",
        "instrucoes_chave": "1. Acesse SerpApi.com\n2. Crie conta gratuita\n3. Copie a 'API Key' no Dashboard.",
        "instrucoes_planilha": "Sua planilha deve conter: Nome, Custo e Quantidade. EAN é recomendado.",
        "moeda": "R$", "lang": "pt-BR", "vencendo": "Vencendo", "caro": "Caro", "burn": "Burn",
        "btn_analise": "🚀 INICIAR ANÁLISE REAL", "sinc_btn": "📤 Aceitar sugestões de preço para o bling",
        "sinc_msg": "Preços sincronizados no Bling!"
    },
    "Portugal 🇵🇹": {
        "titulo": "🚀 Inteligência de Mercado Portugal & UE",
        "instrucoes_chave": "1. Aceda a SerpApi.com\n2. Crie conta gratuita\n3. Copie a 'API Key' no Dashboard.",
        "instrucoes_planilha": "A folha deve conter: Nome, Custo e Quantidade. EAN é recomendado.",
        "moeda": "€", "lang": "pt-PT", "vencendo": "A Vencer", "caro": "Caro", "burn": "Preço Crítico",
        "btn_analise": "🚀 INICIAR ANÁLISE DE MERCADO", "sinc_btn": "N/A"
    },
    "USA 🇺🇸": {
        "titulo": "🚀 USA Marketplace Intelligence",
        "instrucoes_chave": "1. Go to SerpApi.com\n2. Create free account\n3. Copy 'API Key' from Dashboard.",
        "instrucoes_planilha": "Your sheet must have: Name, Cost, and Quantity. EAN is recommended.",
        "moeda": "$", "lang": "en", "vencendo": "Winning", "caro": "Expensive", "burn": "Price Alert",
        "btn_analise": "🚀 START MARKET ANALYSIS", "sinc_btn": "N/A"
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

# --- SIDEBAR E SELETOR DE PAÍS ---
with st.sidebar:
    st.header("🌎 Global Selection")
    pais_sel = st.selectbox("Select Country / Selecione o País:", list(idiomas.keys()))
    tx = idiomas[pais_sel] 
    
    st.divider()
    st.header("🔑 API Activation")
    with st.expander("How to get your key / Como obter a chave"):
        st.write(tx["instrucoes_chave"])
    
    api_key_input = st.text_input("SerpApi Key:", type="password")
    if st.button("Confirm Key / Confirmar"):
        st.session_state.api_key = api_key_input
        st.success("Activated!")

    if "Brasil" in pais_sel:
        st.divider()
        st.header("🔌 Bling Connection")
        bling_token = st.text_input("Token API Bling V3:", type="password")
    else: bling_token = None

    if "Portugal" in pais_sel:
        st.divider()
        st.subheader("🇪🇺 European Scope")
        scope_pt = st.radio("Search scope:", ["Apenas Portugal", "Toda a União Europeia"], index=0)
    
    st.divider()
    st.header("💬 Support / Suporte")
    user_q = st.text_input("Question / Dúvida?")
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            n, e, m = st.text_input("Name/Nome"), st.text_input("Email"), st.text_area("Message/Mensagem")
            if st.form_submit_button("Send/Enviar"):
                if enviar_email_log(n, e, m, "SUPORTE"): st.success("Sent/Enviado!")

# --- TÍTULO E TERMOS ---
st.title(tx["titulo"])
st.markdown(f"### ⚖️ Terms & Instructions")
termos_texto = f"""
{tx['instrucoes_planilha']}
- Data is collected from the internet in real-time.
- User MUST validate results before any price change.
- All decisions are the exclusive responsibility of the client.
"""
st.info(termos_texto)
aceite = st.checkbox("Accept Terms / Aceito os Termos")

if not aceite:
    st.warning("Accept terms to unlock system / Aceite os termos para desbloquear.")
    st.stop()

st.divider()

# --- PASSO 1: CARREGAMENTO ---
st.markdown(f"### 1️⃣ Data Upload")
if "Brasil" in pais_sel:
    fonte = st.radio("Source/Fonte:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)
else:
    fonte = "Excel (Manual)"

df_base = pd.DataFrame()
if fonte == "Bling (API V3)":
    if st.button("📥 Import Bling"):
        try:
            h = {"Authorization": f"Bearer {bling_token}"}
            r = requests.get("https://bling.com.br", headers=h)
            if r.status_code == 200:
                df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                st.success("Imported!")
        except: st.error("Error")
else:
    uploaded_file = st.file_uploader("Upload Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        st.write("Map Columns / Mapeie as Colunas:")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NAME/NOME:", cols)
        with c2: col_c = st.selectbox("COST/CUSTO:", cols)
        with c3: col_q = st.selectbox("QTY/QTDE:", cols)
        with c4: col_l = st.selectbox("LINE/LINHA:", ["N/A"] + cols)
        with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "N/A" else "General"
        df_base['ID'] = 0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown(f"### 2️⃣ Strategy & Analysis")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("Tax/Imposto (%)", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("Markup (%)", 0, 500, 70) / 100
    
    if st.button(tx["btn_analise"]):
        if "api_key" not in st.session_state: st.error("Key missing!")
        else:
            with st.spinner('Scanning market...'):
                df = df_base.copy(); res_m, res_l = [], []
                search_cfg = {
                    "Brasil 🇧🇷": {"domain": "google.com.br", "gl": "br", "loc": "Brazil"},
                    "Portugal 🇵🇹": {"domain": "google.pt", "gl": "pt", "loc": "Portugal" if scope_pt == "Apenas Portugal" else "Western Europe"},
                    "USA 🇺🇸": {"domain": "google.com", "gl": "us", "loc": "United States"}
                }
                cfg = search_cfg[pais_sel]

                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}",
                                           "google_domain": cfg["domain"], "hl": tx["lang"][:2], "gl": cfg["gl"], 
                                           "location": cfg["loc"], "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "N/A"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            if any(t in it.get('title','').lower() for t in ['peça','manual','spare']): continue
                            if tx["moeda"] not in str(it.get('price','')): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.15): validos.append({"p": round(v,2), "l":it.get('source')})
                            except: continue
                        if validos:
                            b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                
                df['Mercado'], df['Loja Líder'] = res_m, res_l
                df['Seu Preço'] = round(df['Custo'] * (1 + markup_padrao), 2)
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = round((((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100, 2)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Situação'] = df.apply(lambda x: f"🟥 {tx['burn']}" if x['Mercado'] < x['Custo'] else (f"⚠️ {tx['caro']}" if x['Seu Preço'] > x['Mercado'] else f"✅ {tx['vencendo']}"), axis=1)
                st.session_state.df_final = df

# --- PASSO 3: RESULTADOS ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader(tx["passo3"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Invest.", f"{tx['moeda']} {df['Custo'].sum():,.2f}")
    c2.metric("Profit", f"{tx['moeda']} {df['Lucro Total'].sum():,.2f}")
    c3.metric("Margin", f"{df['Margem %'].mean():.2f}%")
    
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({
        'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'
    }).map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem %']))

    st.download_button(label="📥 Download Excel", data=df.to_csv(index=False).encode('utf-8'), file_name="analysis.csv")

    if "Brasil" in pais_sel and fonte == "Bling (API V3)":
        st.divider(); st.subheader("🔄 Bling Sync")
        if st.button(tx["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success(tx["sinc_msg"])
