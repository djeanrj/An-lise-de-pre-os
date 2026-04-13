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
st.set_page_config(page_title="Global Marketplace Intelligence", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO E CONFIGURAÇÃO ---
idiomas = {
    "BR 🇧🇷": {
        "id": "BR", "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil",
        "titulo": "🚀 Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key", "help_chave": "Código para pesquisar preços reais no Google Shopping. Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "bling_token": "Token API Bling V3:",
        "ajuda_header": "📖 Legenda", "ajuda_corpo": "✅ **Vencendo**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Concorrência abaixo do custo.",
        "suporte_header": "💬 Suporte", "suporte_label": "Como podemos ajudar?",
        "termos_header": "### ⚖️ Termos de Uso e Isenção", "termos_check": "Eu aceito os Termos de Uso.",
        "termos_aviso": "👉 Aceite os termos para prosseguir.",
        "passo1": "1️⃣ Carregamento", "btn_excel": "Subir arquivo Excel", "mapeamento": "Mapeie as colunas do seu arquivo:",
        "passo2": "2️⃣ Estratégia", "btn_analisar": "🚀 INICIAR ANÁLISE REAL",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Baixar Excel", "sinc_btn": "Aceitar sugestões de preço para o bling"
    },
    "PT 🇵🇹": {
        "id": "PT", "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal",
        "titulo": "🚀 Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "help_chave": "Código para pesquisar preços reais no Google Shopping. Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "ajuda_header": "📖 Legenda", "ajuda_corpo": "✅ **A Vencer**: O seu preço é o mais baixo.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Crítico**: Preços abaixo do custo.",
        "suporte_header": "💬 Suporte", "suporte_label": "Como podemos ajudar?",
        "termos_header": "### ⚖️ Termos de Utilização", "termos_check": "Aceito os Termos de Utilização.",
        "termos_aviso": "👉 Aceite os termos para prosseguir.",
        "passo1": "1️⃣ Carregamento", "btn_excel": "Carregar ficheiro Excel", "mapeamento": "Identifique as colunas do seu ficheiro:",
        "passo2": "2️⃣ Estratégia", "btn_analisar": "🚀 INICIAR ANÁLISE DE MERCADO",
        "invest": "Investimento", "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Descarregar Excel"
    },
    "US 🇺🇸": {
        "id": "US", "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States",
        "titulo": "🚀 USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "help_chave": "Code for real-time prices. Get it at SerpApi.com.",
        "btn_confirmar": "Confirm Key", "msg_ativado": "System Activated!",
        "ajuda_header": "📖 Legend", "ajuda_corpo": "✅ **Winning**: Best price.\n\n⚠️ **Expensive**: Above market.\n\n🟥 **Alert**: Market below cost.",
        "suporte_header": "💬 Support", "suporte_label": "How can we help?",
        "termos_header": "### ⚖️ Terms of Use", "termos_check": "I accept the Terms.",
        "termos_aviso": "👉 Please accept terms to unlock.",
        "passo1": "1️⃣ Upload", "btn_excel": "Upload Excel file", "mapeamento": "Map your file columns:",
        "passo2": "2️⃣ Strategy", "btn_analisar": "🚀 START MARKET ANALYSIS",
        "invest": "Investment", "lucro": "Profit", "margem": "Avg Margin",
        "download_btn": "Download Excel"
    }
}

# --- DETECÇÃO REAL DE PAÍS POR IP (Lisboa = PT) ---
@st.cache_data(ttl=3600)
def detectar_pais():
    try:
        res = requests.get("https://ipapi.co", timeout=3).json()
        cc = res.get("country_code", "BR")
        if cc == "PT": return "PT 🇵🇹"
        if cc == "US": return "US 🇺🇸"
        return "BR 🇧🇷"
    except:
        return "BR 🇧🇷"

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("🌎 Market / Mercado")
    pais_padrao = detectar_pais()
    opcoes = sorted(list(idiomas.keys()))
    pais_sel = st.selectbox("Select:", opcoes, index=opcoes.index(pais_padrao))
    t = idiomas[pais_sel]
    
    st.divider()
    st.header("🔑 Activation")
    api_key_input = st.text_input(t["label_chave"], type="password", help=t["help_chave"])
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success(t["msg_ativado"])

    if "PT" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "Toda a União Europeia"])
    
    st.divider()
    st.header(t["ajuda_header"])
    st.info(t["ajuda_corpo"])

    st.divider()
    st.header(t["suporte_header"])
    user_q = st.text_input(t["suporte_label"])
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            n, e, m = st.text_input("Name/Nome"), st.text_input("Email"), st.text_area("Msg", value=user_q)
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

if "BR" in pais_sel:
    fonte = st.radio("Fonte:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)
    if fonte == "Bling (API V3)":
        bling_token = st.text_input(t["bling_token"], type="password")
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
            df_raw = pd.read_excel(uploaded_file)
            cols = df_raw.columns.tolist()
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
        df_raw = pd.read_excel(uploaded_file)
        cols = df_raw.columns.tolist()
        st.write(t["mapeamento"])
        # CORREÇÃO DO ERRO DE SINTAXE (Linhas separadas)
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            col_n = st.selectbox("NAME:", cols)
        with c2:
            col_c = st.selectbox("COST:", cols)
        with c3:
            col_q = st.selectbox("QTY:", cols)
        with c4:
            col_l = st.selectbox("LINE:", ["None"] + cols)
        with c5:
            col_e = st.selectbox("EAN:", ["N/A"] + cols)
            
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""
        df_base['Linha'] = df_raw[col_l] if col_l != "None" else "General"
        df_base['ID'] = 0

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
                if "PT" in pais_sel and scope_pt == "Toda a União Europeia": loc_f = "Western Europe"
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
    c3.metric(t["margem"], f"{df['Margem %'].mean():.1f}%")
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'}))
    
    st.divider()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df.to_excel(wr, index=False)
    st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analysis.xlsx")

    if "BR" in pais_sel and fonte == "Bling (API V3)":
        st.divider()
        if st.button(t["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("OK!")
