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
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO TOTALMENTE ISOLADO ---
idiomas = {
    "Brasil": {
        "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil",
        "titulo": "Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key", "help_chave": "Código de pesquisa real obtido em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "bling_token": "Token API Bling V3",
        "ajuda_header": "Legenda", "ajuda_corpo": "✅ Vencendo\n⚠️ Caro\n🟥 Burn",
        "suporte_header": "Suporte", "suporte_label": "Como podemos ajudar?",
        "termos_header": "Termos de Uso e Isenção",
        "termos_corpo": "A planilha deve conter: Nome, Custo e Quantidade.",
        "termos_check": "Eu aceito os Termos de Uso do Brasil.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Subir Arquivo Excel",
        "mapeamento": "Mapeie as colunas:", "header_analise": "Estratégia e Análise",
        "btn_analisar": "Iniciar Análise Real", "invest": "Investimento",
        "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Baixar Excel", "sinc_btn": "Aceitar sugestões de preço para o bling"
    },
    "Portugal": {
        "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal",
        "titulo": "Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "help_chave": "Código de pesquisa real obtido em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "ajuda_header": "Legenda", "ajuda_corpo": "✅ A Vencer\n⚠️ Caro\n🟥 Crítico",
        "suporte_header": "Suporte", "suporte_label": "Como podemos ajudar?",
        "termos_header": "Termos de Utilização",
        "termos_corpo": "A folha deve conter: Nome, Custo e Quantidade.",
        "termos_check": "Aceito os Termos de Utilização de Portugal.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Carregar Ficheiro Excel",
        "mapeamento": "Identifique as colunas:", "header_analise": "Estratégia e Análise",
        "btn_analisar": "Iniciar Análise de Mercado", "invest": "Investimento",
        "lucro": "Lucro Projetado", "margem": "Margem Média",
        "download_btn": "Descarregar Excel"
    },
    "USA": {
        "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States",
        "titulo": "USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "help_chave": "Search code from SerpApi.com.",
        "btn_confirmar": "Confirm Key", "msg_ativado": "Activated!",
        "ajuda_header": "Legend", "ajuda_corpo": "✅ Winning\n⚠️ Expensive\n🟥 Alert",
        "suporte_header": "Support", "suporte_label": "How can we help?",
        "termos_header": "Terms of Use",
        "termos_corpo": "Sheet required: Name, Cost, and Quantity.",
        "termos_check": "I accept the USA Terms of Use.",
        "header_dados": "Product Upload", "btn_excel": "Upload Excel File",
        "mapeamento": "Map Columns:", "header_analise": "Strategy & Analysis",
        "btn_analisar": "Start Market Analysis", "invest": "Investment",
        "lucro": "Profit", "margem": "Avg Margin",
        "download_btn": "Download Excel"
    }
}

# --- CONTROLE DE SESSÃO ---
if "aceites" not in st.session_state:
    st.session_state.aceites = {k: False for k in idiomas.keys()}

# --- FUNÇÃO DE E-MAIL ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    dest = "contato@vembrincarcomagente.com"
    try:
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, dest, f"[{tipo}] - {n}"
        msg.attach(MIMEText(f"Contato: {n}\nEmail: {e}\n\nMsg: {m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- SIDEBAR ---
with st.sidebar:
    st.header("Região / Region")
    pais_sel = st.selectbox("Mercado:", list(idiomas.keys()))
    t = idiomas[pais_sel]
    
    st.divider()
    st.header("Configuração")
    api_key_input = st.text_input(t["label_chave"], type="password", help=t["help_chave"])
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success(t["msg_ativado"])

    if pais_sel == "Portugal":
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])
    
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
st.subheader(t["termos_header"])

if not st.session_state.aceites[pais_sel]:
    st.info(t["termos_corpo"])
    if st.checkbox(t["termos_check"], key=f"c_{pais_sel}"):
        st.session_state.aceites[pais_sel] = True
        st.rerun()
    st.stop()

st.divider()
st.subheader(t["header_dados"])
df_base = pd.DataFrame()

if pais_sel == "Brasil":
    fonte = st.radio("Fonte:", ["Bling (API V3)", "Excel"], horizontal=True)
    if fonte == "Bling (API V3)":
        c_bl, _ = st.columns([0.5, 0.5])
        with c_bl:
            bling_token = st.text_input(t["bling_token"], type="password")
        if st.button("📥 Importar Dados"):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                    st.success("Sucesso!")
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
    st.divider(); st.subheader(t["header_analise"])
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("%", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("Markup %", 0, 500, 70) / 100
    if st.button(t["btn_analisar"]):
        if "api_key" not in st.session_state: st.error("Key?")
        else:
            with st.spinner('...'):
                df = df_base.copy(); res_m, res_l = [], []
                loc_f = t["loc"]
                if pais_sel == "Portugal" and scope_pt == "União Europeia": loc_f = "Western Europe"
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
                df['Situação'] = df.apply(lambda x: "🟥" if x['Mercado'] < x['Custo'] else ("⚠️" if x['Seu Preço'] > x['Mercado'] else "✅"), axis=1)
                st.session_state.df_final = df

if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader("Dash")
    c1, c2, c3 = st.columns(3)
    c1.metric(t["invest"], f"{t['moeda']} {df['Custo'].sum():,.2f}")
    c2.metric(t["lucro"], f"{t['moeda']} {df['Lucro Total'].sum():,.2f}")
    c3.metric(t["margem"], f"{df['Margem %'].mean():.2f}%")
    st.dataframe(df[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'}))
    
    st.divider()
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df.to_excel(wr, index=False)
    st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analise.xlsx")

    if pais_sel == "Brasil" and fonte == "Bling (API V3)":
        if st.button(t["sinc_btn"]):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("Sincronizado!")
