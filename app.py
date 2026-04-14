import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from serpapi import GoogleSearch
import io
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO ---
idiomas = {
    "Brasil 🇧🇷": {
        "id": "BR", "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil",
        "titulo": "Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key", "btn_confirmar": "Confirmar Chave",
        "ajuda_header": "Situação", "ajuda_corpo": "✅ Vencendo\n⚠️ Caro\n🟥 Burn",
        "trend_header": "Tendência", "trend_corpo": "📈 Ascendente\n➡️ Flat\n📉 Decrescente",
        "termos_header": "Termos de Uso e Isenção", "termos_check": "Eu aceito os Termos de Uso do Brasil.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Subir planilha",
        "mapeamento": "Mapeamento Sugerido:", "btn_analisar": "Iniciar Análise Real", 
        "grafico_opcoes": ["Status (Risco)", "Marketplace", "Linha (Categoria)", "Volume", "Matriz"],
        "download_btn": "Baixar Planilha", "hist_titulo": "📜 Histórico de Consultas"
    },
    "Portugal 🇵🇹": {
        "id": "PT", "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal",
        "titulo": "Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "help_chave": "Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "ajuda_header": "Situação", "ajuda_corpo": "✅ A Vencer\n⚠️ Caro\n🟥 Crítico",
        "trend_header": "Tendência", "trend_corpo": "📈 Ascendente\n➡️ Flat\n📉 Decrescente",
        "termos_header": "Termos de Utilização", "termos_check": "Aceito os Termos de Utilização de Portugal.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Carregar folha de cálculo",
        "mapeamento": "Mapeamento Sugerido:", "btn_analisar": "Analisar Mercado Ibérico/UE", 
        "grafico_opcoes": ["Status (Risco)", "Marketplace", "Linha (Categoria)", "Stock", "Matriz"],
        "download_btn": "Descarregar Folha", "hist_titulo": "📜 Histórico de Consultas"
    },
    "USA 🇺🇸": {
        "id": "US", "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States",
        "titulo": "USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "btn_confirmar": "Confirm Key",
        "ajuda_header": "Risk Status", "ajuda_corpo": "✅ Winning\n⚠️ Expensive\n🟥 Alert",
        "trend_header": "Trend", "trend_corpo": "📈 Rising\n➡️ Flat\n📉 Falling",
        "termos_header": "Terms of Use", "termos_check": "I accept the USA Terms.",
        "header_dados": "Product Upload", "btn_excel": "Upload Spreadsheet",
        "mapeamento": "Suggested Mapping:", "btn_analisar": "Start Market Analysis", 
        "grafico_opcoes": ["Status (Risk)", "Marketplace", "Line (Category)", "Units", "Matrix"],
        "download_btn": "Download Sheet", "hist_titulo": "📜 Search History"
    }
}
# --- FUNÇÕES ---
def identificar_coluna(lista_colunas, chaves):
    for c in lista_colunas:
        if any(k in str(c).lower().strip() for k in chaves): return lista_colunas.index(c)
    return 0

def enviar_email_log(n, e, m):
    dest = "contato@vembrincarcomagente.com"
    try:
        origem, senha = st.secrets["EMAIL_ORIGEM"], st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, dest, f"[SUPORTE] - {n}"
        msg.attach(MIMEText(f"Contato: {n}\nEmail: {e}\n\nMsg: {m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- CONTROLE DE SESSÃO ---
if "api_key" not in st.session_state: st.session_state.api_key = None
if "historico_global" not in st.session_state: st.session_state.historico_global = pd.DataFrame()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Região / Region")
    pais_sel = st.selectbox("Região:", list(idiomas.keys()), key="pais_main")
    
    if "pais_anterior" not in st.session_state: st.session_state.pais_anterior = pais_sel
    if st.session_state.pais_anterior != pais_sel:
        if "df_final" in st.session_state: del st.session_state.df_final
        st.session_state.pais_anterior = pais_sel
        st.rerun()

    t = idiomas[pais_sel]
    st.divider()
    api_key_input = st.text_input(t["label_chave"], type="password", value=st.session_state.api_key or "")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success("OK!")
    
    scope_pt = "Apenas Portugal"
    if "Portugal" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])
    
    st.divider()
    st.header(t["ajuda_header"])
    st.info(t["ajuda_corpo"])
    
    # LEGENDA DE TENDÊNCIA LIMPA
    st.header(t["trend_header"])
    st.info(t["trend_corpo"])
    
    st.divider()
    st.header("Suporte")
    user_q = st.text_input("Dúvida:")
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            sn, se, sm = st.text_input("Nome"), st.text_input("Email"), st.text_area("Mensagem", value=user_q)
            if st.form_submit_button("Enviar"):
                if enviar_email_log(sn, se, sm): st.success("✅ Enviado")

# --- CORPO PRINCIPAL ---
st.title(t["titulo"])
st.subheader(t["termos_header"])
aceite_regiao = st.checkbox(t["termos_check"], key=f"aceite_{pais_sel}")

if not aceite_regiao:
    st.warning("Aguardando aceite...")
    st.stop()

if not st.session_state.api_key:
    st.warning("⚠️ Insira a SerpApi Key na lateral.")
else:
    df_base = pd.DataFrame()
    fonte = st.radio("Fonte:", ["Planilha", "Bling (API V3)"] if "Brasil" in pais_sel else ["Spreadsheet"], horizontal=True)

    if "Bling" in fonte:
        c_bl, _ = st.columns([0.3, 0.7])
        with c_bl:
            token_bl = st.text_input("Token Bling:", type="password")
        if st.button("📥 Importar"):
            try:
                r = requests.get("https://bling.com.br", headers={"Authorization": f"Bearer {token_bl}"})
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": i.get('categoria',{}).get('nome','Geral')} for i in r.json().get('data', [])])
                    st.success("OK!")
            except: st.error("Erro")
    else:
        uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls", "csv"])
        if uploaded_file:
            df_raw = pd.read_excel(uploaded_file) if not uploaded_file.name.endswith('.csv') else pd.read_csv(uploaded_file)
            cols = df_raw.columns.tolist()
            st.write(f"**{t['mapeamento']}**")
            
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                idx_n = identificar_coluna(cols, ['produto', 'nome', 'item', 'name'])
                col_n = st.selectbox("PRODUTO:", cols, index=idx_n)
            with c2:
                idx_c = identificar_coluna(cols, ['custo', 'compra', 'cost', 'price'])
                col_c = st.selectbox("CUSTO:", cols, index=idx_c)
            with c3:
                idx_q = identificar_coluna(cols, ['qtd', 'quantidade', 'stock', 'qty'])
                col_q = st.selectbox("QTDE:", cols, index=idx_q)
            with c4:
                idx_l = identificar_coluna(cols, ['linha', 'categoria', 'category'])
                col_l = st.selectbox("LINHA:", ["Geral"] + cols, index=identificar_coluna(cols, ['linha', 'categoria'])+1 if identificar_coluna(cols, ['linha', 'categoria']) >= 0 else 0)
            with c5:
                idx_e = identificar_coluna(cols, ['ean', 'barra', 'upc'])
                col_e = st.selectbox("EAN:", ["N/A"] + cols, index=identificar_coluna(cols, ['ean', 'barra'])+1 if identificar_coluna(cols, ['ean', 'barra']) >= 0 else 0)
            
            df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
            df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""
            df_base['Linha'] = df_raw[col_l] if col_l != "Geral" else "Geral"

    if not df_base.empty:
        st.divider()
        cp1, cp2 = st.columns(2)
        with cp1:
            imposto = st.number_input("% Tax", 0, 100, 4) / 100
        with cp2:
            markup_v = st.number_input("% Markup", 0, 500, 70) / 100
            
        if st.button(t["btn_analisar"]):
            with st.spinner('Analisando...'):
                df = df_base.copy(); res_m, res_l, res_trend, res_vol = [], [], [], []
                
                if "Brasil" in pais_sel:
                    blacklist = ['ebay', 'kidiin', 'kidinn', 'tradeinn', 'vendiloshop', 'aliexpress', 'temu', 'fruugo', 'desertcart']
                elif "Portugal" in pais_sel:
                    blacklist = ['aliexpress', 'temu', 'ebay', 'amazon.com', 'wish']
                else:
                    blacklist = ['aliexpress', 'temu', 'wish']

                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": t["domain"], "hl": t["lang"][:2], "gl": t["gl"], "location": t["loc"], "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.2, 2), "N/A"
                    trend, vol = "➡️ Flat", "Baixa"
                    
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            source, link = it.get('source','').lower(), it.get('link', '').lower()
                            if any(b in source for b in blacklist) or any(b in link for b in blacklist) or t["moeda"] not in str(it.get('price','')): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.1): validos.append({"p": round(v,2), "l": it.get('source', 'N/A'), "rev": it.get('reviews', 0)})
                            except: continue
                        if validos:
                            b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                            vol = "Alta" if sum(v['rev'] for v in validos) > 30 else "Média"
                            trend = "📈 Ascendente" if any("sale" in str(it).lower() for it in results['shopping_results']) else "➡️ Flat"
                    
                    res_m.append(best_p); res_l.append(best_l); res_trend.append(trend); res_vol.append(vol)
                
                df['Mercado'], df['Loja Líder'], df['Tendência'], df['Procura'] = res_m, res_l, res_trend, res_vol
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if (x['Custo']*(1+markup_v)) > x['Mercado'] else round(x['Custo']*(1+markup_v), 2), axis=1)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Status'] = df.apply(lambda x: "🟥" if x['Mercado'] < x['Custo'] else ("⚠️" if (x['Custo']*(1+markup_v)) > x['Mercado'] else "✅"), axis=1)
                st.session_state.df_final = df
                st.session_state.historico_global = pd.concat([st.session_state.historico_global, df]).drop_duplicates(subset=['Nome', 'Mercado'])

    if "df_final" in st.session_state:
        df_v = st.session_state.df_final
        m1, m2, m3 = st.columns(3)
        m1.metric("Investimento", f"{t['moeda']} {(df_v['Custo'] * df_v['Qtde']).sum():,.2f}")
        m2.metric("Lucro Sugerido", f"{t['moeda']} {df_v['Lucro Total'].sum():,.2f}")
        m3.metric("Margem Média", f"{( ( (df_v['Preço Sugerido']*(1-imposto)) - df_v['Custo'] ) / df_v['Preço Sugerido'] ).mean()*100:.1f}%")
        
        modo = st.selectbox("Gráfico:", t["grafico_opcoes"])
        color_map = {'✅':'#2ecc71', '⚠️':'#f1c40f', '🟥':'#e74c3c'}
        if "Status" in modo:
            fig = px.pie(df_v, names='Status', hole=0.4, color='Status', color_discrete_map=color_map)
        elif "Matriz" in modo:
            fig = px.scatter(df_v, x='Mercado', y='Lucro Total', size='Qtde', color='Status', hover_name='Nome', color_discrete_map=color_map)
        else:
            fig = px.bar(df_v, x='Nome', y='Lucro Total', color='Status', color_discrete_map=color_map)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_v[['Nome', 'Linha', 'Qtde', 'Custo', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Status', 'Tendência', 'Procura']])
        
        out = io.BytesIO(); wr = pd.ExcelWriter(out, engine='xlsxwriter'); df_v.to_excel(wr, index=False); wr.close()
        st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analise.xlsx")
