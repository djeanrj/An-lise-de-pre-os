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
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")

# --- DICIONÁRIO DE TRADUÇÃO TOTALMENTE ISOLADO ---
idiomas = {
    "Brasil 🇧🇷": {
        "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br", "gl": "br", "loc": "Brazil",
        "titulo": "Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key", "help_chave": "Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "aviso_chave": "⚠️ Confirme sua SerpApi Key na barra lateral.",
        "bling_token": "Token API Bling V3",
        "ajuda_header": "Legenda de Situação", "ajuda_corpo": "✅ Vencendo\n⚠️ Caro\n🟥 Burn",
        "suporte_header": "💬 Suporte ao Cliente", "suporte_label": "Como podemos ajudar?",
        "termos_header": "Termos de Uso e Isenção", "termos_check": "Eu aceito os Termos de Uso.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Subir arquivo Excel",
        "mapeamento": "Mapeamento Sugerido (Confira as Colunas):", 
        "header_analise": "Estratégia e Análise", "btn_analisar": "Iniciar Análise Real", 
        "invest": "Investimento em Estoque", "lucro": "Lucro Total Projetado", "margem": "Margem s/ Sugerido",
        "grafico_label": "Ver Gráfico por:",
        "grafico_opcoes": ["Status (Risco)", "Marketplace (Concorrentes)", "Linha (Categoria)", "Volume de Unidades"],
        "help_margem": "Baseado no Preço Sugerido.",
        "download_btn": "Baixar Excel", "sinc_btn": "Sincronizar com Bling"
    },
    "Portugal 🇵🇹": {
        "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal",
        "titulo": "Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "help_chave": "Obtenha em SerpApi.com.",
        "btn_confirmar": "Confirmar Chave", "msg_ativado": "Sistema Ativado!",
        "aviso_chave": "⚠️ Confirme a sua Chave SerpApi na barra lateral.",
        "ajuda_header": "Legenda de Situação", "ajuda_corpo": "✅ A Vencer\n⚠️ Caro\n🟥 Crítico",
        "suporte_header": "💬 Suporte ao Utilizador", "suporte_label": "Como podemos ajudar?",
        "termos_header": "Termos de Utilização", "termos_check": "Aceito os Termos de Utilização.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Carregar ficheiro Excel",
        "mapeamento": "Sugestão de Colunas (Valide abaixo):",
        "header_analise": "Estratégia e Análise", "btn_analisar": "Iniciar Análise de Mercado", 
        "invest": "Investimento em Stock", "lucro": "Lucro Total Projetado", "margem": "Margem s/ Sugerido",
        "grafico_label": "Ver Gráfico por:",
        "grafico_opcoes": ["Status (Risco)", "Marketplace (Lojas)", "Linha (Categoria)", "Volume de Stock"],
        "help_margem": "Baseado no Preço Sugerido.",
        "download_btn": "Descarregar Excel"
    },
    "USA 🇺🇸": {
        "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States",
        "titulo": "USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "help_chave": "Search code from SerpApi.com.",
        "btn_confirmar": "Confirm Key", "msg_ativado": "Activated!",
        "aviso_chave": "⚠️ Confirm your SerpApi Key in the sidebar.",
        "ajuda_header": "Legend", "ajuda_corpo": "✅ Winning\n⚠️ Expensive\n🟥 Alert",
        "suporte_header": "💬 Support", "suporte_label": "How can we help?",
        "termos_header": "Terms of Use", "termos_check": "I accept the Terms.",
        "header_dados": "Product Upload", "btn_excel": "Upload Excel file",
        "mapeamento": "Suggested Mapping (Please Verify):",
        "header_analise": "Strategy & Analysis", "btn_analisar": "Start Market Analysis", 
        "invest": "Inventory Investment", "lucro": "Projected Profit", "margem": "Avg Margin",
        "grafico_label": "View Chart by:",
        "grafico_opcoes": ["Status (Risk)", "Marketplace (Stores)", "Line (Category)", "Unit Volume"],
        "help_margem": "Based on Suggested Price.",
        "download_btn": "Download Excel"
    }
}

# --- FUNÇÃO DE MAPEAMENTO INTELIGENTE ---
def identificar_coluna(lista_colunas, chaves_desejadas):
    for c in lista_colunas:
        nome_limpo = str(c).lower().strip()
        if any(chave in nome_limpo for chave in chaves_desejadas):
            return lista_colunas.index(c)
    return 0

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

# --- SESSÃO ---
if "api_key" not in st.session_state: st.session_state.api_key = None
if "aceites" not in st.session_state: st.session_state.aceites = {k: False for k in idiomas.keys()}

with st.sidebar:
    st.header("Mercado")
    pais_sel = st.selectbox("Selecione:", list(idiomas.keys()))
    t = idiomas[pais_sel]
    st.divider()
    api_key_input = st.text_input(t["label_chave"], type="password", help=t["help_chave"])
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success(t["msg_ativado"])
    if "Portugal" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])
    st.divider()
    st.header(t["ajuda_header"])
    st.info(t["ajuda_corpo"])
    
    st.divider()
    st.header(t["suporte_header"])
    user_q = st.text_input(t["suporte_label"])
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            sn, se, sm = st.text_input("Nome"), st.text_input("Email"), st.text_area("Mensagem", value=user_q)
            if st.form_submit_button("Enviar"):
                if enviar_email_log(sn, se, sm): st.success("✅")

# --- CORPO PRINCIPAL ---
st.title(t["titulo"])
st.subheader(t["termos_header"])

if not st.session_state.aceites[pais_sel]:
    st.info(idiomas[pais_sel].get("termos_corpo", "A planilha deve conter Nome, Custo e Quantidade."))
    if st.checkbox(t["termos_check"], key=f"c_{pais_sel}"):
        st.session_state.aceites[pais_sel] = True
        st.rerun()
    st.stop()

st.divider()
st.subheader(t["header_dados"])

if not st.session_state.api_key:
    st.warning(t["aviso_chave"])
else:
    df_base = pd.DataFrame()
    if "Brasil" in pais_sel:
        fonte = st.radio("Fonte:", ["Bling (API V3)", "Excel"], horizontal=True)
        if fonte == "Bling (API V3)":
            c_bl, _ = st.columns([0.3, 0.7])
            with c_bl: bling_token = st.text_input(t["bling_token"], type="password")
            if st.button("📥 Importar Dados"):
                try:
                    h = {"Authorization": f"Bearer {bling_token}"}
                    r = requests.get("https://bling.com.br", headers=h)
                    if r.status_code == 200:
                        df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": i.get('categoria',{}).get('nome','Geral')} for i in r.json().get('data', [])])
                        st.success("OK!")
                except: st.error("Erro")
        else:
            uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
            if uploaded_file:
                df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
                st.write(f"**{t['mapeamento']}**")
                
                # LOGICA DE SUGESTÃO DE COLUNAS
                idx_n = identificar_coluna(cols, ['produto', 'nome', 'item', 'descri'])
                idx_c = identificar_coluna(cols, ['custo', 'compra', 'preço c', 'unitário'])
                idx_q = identificar_coluna(cols, ['qtd', 'quantidade', 'estoque', 'stock', 'saldo'])
                idx_l = identificar_coluna(cols, ['linha', 'categoria', 'grupo', 'tipo'])
                idx_e = identificar_coluna(cols, ['ean', 'barra', 'gtin', 'codigo'])

                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: col_n = st.selectbox("NOME:", cols, index=idx_n)
                with c2: col_c = st.selectbox("CUSTO:", cols, index=idx_c)
                with c3: col_q = st.selectbox("QTDE:", cols, index=idx_q)
                with c4: col_l = st.selectbox("LINHA:", ["Nenhuma"] + cols, index=idx_l+1 if idx_l > 0 else 0)
                with c5: col_e = st.selectbox("EAN:", ["Não possuo"] + cols, index=idx_e+1 if idx_e > 0 else 0)
                
                df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
                df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""
                df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"
                df_base['ID'] = 0
    else:
        uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "xls"])
        if uploaded_file:
            df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
            st.write(f"**{t['mapeamento']}**")
            
            idx_n = identificar_coluna(cols, ['name', 'product', 'item'])
            idx_c = identificar_coluna(cols, ['cost', 'price', 'buy'])
            idx_q = identificar_coluna(cols, ['qty', 'stock', 'quantity'])
            idx_l = identificar_coluna(cols, ['line', 'category', 'group'])
            idx_e = identificar_coluna(cols, ['ean', 'code', 'barcode', 'upc'])

            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: col_n = st.selectbox("NAME:", cols, index=idx_n)
            with c2: col_c = st.selectbox("COST:", cols, index=idx_c)
            with c3: col_q = st.selectbox("QTY:", cols, index=idx_q)
            with c4: col_l = st.selectbox("LINE:", ["None"] + cols, index=idx_l+1 if idx_l > 0 else 0)
            with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols, index=idx_e+1 if idx_e > 0 else 0)
            
            df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
            df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""
            df_base['Linha'] = df_raw[col_l] if col_l != "None" else "General"
            df_base['ID'] = 0

    if not df_base.empty:
        st.divider(); st.subheader(t["header_analise"])
        cp1, cp2 = st.columns(2)
        with cp1: imposto = st.number_input("% Tax", 0, 100, 4) / 100
        with cp2: markup_padrao = st.number_input("% Markup", 0, 500, 70) / 100
        if st.button(t["btn_analisar"]):
            with st.spinner('Processando análise...'):
                df = df_base.copy(); res_m, res_l = [], []
                loc_f = t["loc"]; blacklist = ['ebay', 'kidiin', 'kidinn', 'tradeinn', 'fruugo', 'desertcart', 'ubuy', 'vendiloshop', 'grandado', 'aliexpress', 'temu']
                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": t["domain"], "hl": t["lang"][:2], "gl": t["gl"], "location": loc_f, "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "N/A"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            source = it.get('source', '').lower(); link = it.get('link', '').lower()
                            if any(b in source for b in blacklist) or any(b in link for b in blacklist): continue
                            if t["moeda"] not in str(it.get('price','')): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.15): validos.append({"p": round(v,2), "l": it.get('source')})
                            except: continue
                        if validos: b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                
                df['Mercado'], df['Loja Líder'] = res_m, res_l
                df['Seu Preço'] = round(df['Custo'] * (1 + markup_padrao), 2)
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = round((((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100, 2)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Status'] = df.apply(lambda x: "🟥" if x['Mercado'] < x['Custo'] else ("⚠️" if x['Seu Preço'] > x['Mercado'] else "✅"), axis=1)
                st.session_state.df_final = df

    if "df_final" in st.session_state:
        df = st.session_state.df_final
        st.divider()
        c_f1, c_f2 = st.columns(2)
        with c_f1: lojas_sel = st.multiselect("Filtrar Concorrentes:", options=df['Loja Líder'].unique(), default=df['Loja Líder'].unique())
        with c_f2: categorias_sel = st.multiselect("Filtrar Linhas:", options=df['Linha'].unique(), default=df['Linha'].unique())
        df_view = df[(df['Loja Líder'].isin(lojas_sel)) & (df['Linha'].isin(categorias_sel))]
        
        m1, m2, m3 = st.columns(3)
        m1.metric(t["invest"], f"{t['moeda']} {(df_view['Custo'] * df_view['Qtde']).sum():,.2f}")
        m2.metric(t["lucro"], f"{t['moeda']} {df_view['Lucro Total'].sum():,.2f}")
        m3.metric(t["margem"], f"{df_view['Margem %'].mean():.2f}%")

        st.write("---")
        c_sel, _ = st.columns([0.3, 0.7])
        with c_sel: modo = st.selectbox(t["grafico_label"], t["grafico_opcoes"])
        
        if "Status" in modo:
            fig = px.pie(df_view, names='Status', hole=0.4, color='Status', color_discrete_map={'✅': '#2ecc71', '⚠️': '#f1c40f', '🟥': '#e74c3c'})
        elif "Marketplace" in modo:
            fig = px.bar(df_view.groupby('Loja Líder')['Lucro Total'].sum().reset_index(), x='Loja Líder', y='Lucro Total', title="Lucro por Lojista")
        elif "Linha" in modo:
            fig = px.pie(df_view, names='Linha', values='Lucro Total', hole=0.4, title="Lucro por Categoria")
        else:
            fig = px.bar(df_view, x='Nome', y='Qtde', color='Status', color_discrete_map={'✅': '#2ecc71', '⚠️': '#f1c40f', '🟥': '#e74c3c'}, title="Volume")
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(df_view[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Status', 'Lucro Total']].style.format({'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'}))
        
        st.divider()
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df_view.to_excel(wr, index=False)
        st.download_button(label=t["download_btn"], data=out.getvalue(), file_name="analise.xlsx")

        if "Brasil" in pais_sel and fonte == "Bling (API V3)":
            if st.button(t["sinc_btn"]):
                h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
                for i, row in df_view.iterrows():
                    requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
                st.success("Sincronizado!")
