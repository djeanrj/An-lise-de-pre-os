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

# --- DICIONÁRIO DE TRADUÇÃO E REGRAS DE MERCADO ---
idiomas = {
    "Brasil 🇧🇷": {
        "titulo": "🚀 Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "Cole sua SerpApi Key aqui:",
        "btn_confirmar": "Confirmar Chave",
        "msg_ativado": "Sistema Ativado!",
        "ajuda_corpo": "✅ **Vencendo**: Seu preço é o menor.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Concorrência abaixo do custo.",
        "termos_check": "Eu aceito os Termos de Uso e a responsabilidade total pelas minhas decisões.",
        "btn_analisar": "🚀 INICIAR ANÁLISE REAL",
        "download_btn": "Baixar Resultados em Excel",
        "sinc_btn": "Aceitar sugestões de preço para o bling e atualizar na plataforma",
        "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil"
    },
    "Portugal 🇵🇹": {
        "titulo": "🚀 Inteligência de Mercado Portugal & UE",
        "label_chave": "Insira a sua SerpApi Key:",
        "btn_confirmar": "Confirmar Chave",
        "msg_ativado": "Sistema Ativado!",
        "ajuda_corpo": "✅ **A Vencer**: O seu preço é o mais baixo.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Crítico**: Mercado abaixo do custo.",
        "termos_check": "Aceito os Termos de Utilização e a responsabilidade total pelas minhas decisões.",
        "btn_analisar": "🚀 INICIAR ANÁLISE DE MERCADO",
        "download_btn": "Descarregar Resultados em Excel",
        "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal"
    },
    "USA 🇺🇸": {
        "titulo": "🚀 USA Marketplace Intelligence",
        "label_chave": "Paste your SerpApi Key here:",
        "btn_confirmar": "Confirm Key",
        "msg_ativado": "System Activated!",
        "ajuda_corpo": "✅ **Winning**: Your price is the lowest.\n\n⚠️ **Expensive**: Above market.\n\n🟥 **Alert**: Below cost.",
        "termos_check": "I accept the Terms of Use and take full responsibility.",
        "btn_analisar": "🚀 START MARKET ANALYSIS",
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

# --- SIDEBAR ---
with st.sidebar:
    st.header("🌍 Global Selection")
    pais_sel = st.selectbox("Select Country:", list(idiomas.keys()))
    t = idiomas[pais_sel]
    
    st.divider()
    if "Brasil" in pais_sel:
        bling_token = st.text_input("Token API Bling V3:", type="password")
    
    api_key_input = st.text_input(t["label_chave"], type="password")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success(t["msg_ativado"])

    if "Portugal" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "Toda a União Europeia"])
    
    st.divider()
    st.header("📖 Help")
    st.info(t["ajuda_corpo"])

# --- TERMOS ---
st.title(t["titulo"])
aceite = st.checkbox(t["termos_check"])
if not aceite:
    st.warning("👉 Aceite os termos para prosseguir.")
    st.stop()

# --- CARREGAMENTO ---
df_base = pd.DataFrame()
fonte = st.radio("Fonte:", ["Importar Bling", "Excel"] if "Brasil" in pais_sel else ["Excel"], horizontal=True)

if fonte == "Importar Bling":
    if st.button("📥 Importar"):
        try:
            h = {"Authorization": f"Bearer {bling_token}"}
            r = requests.get("https://bling.com.br", headers=h)
            if r.status_code == 200:
                df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                st.success("OK!")
        except: st.error("Error/Erro")
else:
    uploaded_file = st.file_uploader("Upload Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NOME:", cols)
        with c2: col_c = st.selectbox("CUSTO:", cols)
        with c3: col_q = st.selectbox("QTDE:", cols)
        with c4: col_l = st.selectbox("LINHA:", ["Nenhuma"] + cols)
        with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"; df_base['ID'] = 0

# --- ANÁLISE ---
if not df_base.empty:
    imposto = st.number_input("Imposto (%)", 0, 100, 4) / 100
    markup_padrao = st.number_input("Markup (%)", 0, 500, 70) / 100
    
    if st.button(t["btn_analisar"]):
        if "api_key" not in st.session_state: st.error("Key?")
        else:
            with st.spinner('Analysing...'):
                df = df_base.copy(); res_m, res_l = [], []
                loc_final = t["loc"]
                if "Portugal" in pais_sel and scope_pt == "Toda a União Europeia": loc_final = "Western Europe"

                for idx, row in df.iterrows():
                    search = GoogleSearch({
                        "engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}",
                        "google_domain": t["domain"], "hl": t["lang"][:2], "gl": t["gl"], 
                        "location": loc_final, "api_key": st.session_state.api_key
                    })
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "N/A"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            loja = it.get('source', '').lower()
                            p_text = str(it.get('price', ''))
                            
                            # --- LÓGICA DE VALIDAÇÃO NACIONAL APERFEIÇOADA ---
                            # 1. BLOQUEIO APENAS DE GIGANTES INTERNACIONAIS CONHECIDOS
                            if any(x in loja for x in ['aliexpress', 'ebay', 'tiendamia', 'international shipping', 'china']): 
                                continue
                            
                            # 2. VALIDAÇÃO POR MOEDA (O símbolo da moeda local DEVE estar no anúncio do Google)
                            # Se o Google Brasil exibe R$ no preço, o comerciante está em território BR ou cobrando em BR.
                            if t["moeda"] in p_text:
                                try:
                                    v = float(re.sub(r'[^\d,.]','',p_text).replace('.','').replace(',','.'))
                                    # Filtro de sanidade para evitar acessórios/peças (mínimo 20% do custo)
                                    if v > (row['Custo']*0.20): 
                                        validos.append({"p": round(v,2), "l":it.get('source')})
                                except: continue
                        
                        if validos:
                            b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                
                df['Mercado'], df['Loja Líder'] = res_m, res_l
                df['Seu Preço'] = round(df['Custo'] * (1 + markup_padrao), 2)
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = round((((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100, 2)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Situação'] = df.apply(lambda x: f"🟥 Burn" if x['Mercado'] < x['Custo'] else (f"⚠️ Caro" if x['Seu Preço'] > x['Mercado'] else f"✅ Vencendo"), axis=1)
                st.session_state.df_final = df

# --- EXIBIÇÃO ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'}).map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem %']))
    
    st.download_button(label=t["download_btn"], data=df.to_csv(index=False).encode('utf-8'), file_name="analysis.csv")
    if "Brasil" in pais_sel and fonte == "Importar Bling":
        if st.button(t["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("Bling Updated!")
