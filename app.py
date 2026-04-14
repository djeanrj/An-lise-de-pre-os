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
        "legenda_html": "<div style='font-size: 0.9rem;'><b>Situação</b><br>✅ Vencendo<br>⚠️ Caro<br>🟥 Burn<br><br><b>Tendência</b><br>📈 Ascendente<br>➡️ Flat<br>📉 Decrescente</div>",
        "termos_header": "Termos de Uso e Isenção", "termos_check": "Eu aceito os Termos de Uso do Brasil.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Subir planilha",
        "mapeamento": "Mapeamento Sugerido:", "btn_analisar": "Iniciar Análise Real", 
        "grafico_opcoes": ["Status (Risco)", "Marketplace (Lucro por Loja)", "Linha (Lucro por Categoria)", "Procura de Mercado (Volume)", "Matriz de Investimento"],
        "download_btn": "Baixar Planilha", "hist_titulo": "📜 Histórico de Consultas"
    },
    "Portugal 🇵🇹": {
        "id": "PT", "moeda": "€", "lang": "pt-PT", "domain": "google.pt", "gl": "pt", "loc": "Portugal",
        "titulo": "Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "btn_confirmar": "Confirmar Chave",
        "legenda_html": "<div style='font-size: 0.9rem;'><b>Situação</b><br>✅ A Vencer<br>⚠️ Caro<br>🟥 Crítico<br><br><b>Tendência</b><br>📈 Ascendente<br>➡️ Flat<br>📉 Decrescente</div>",
        "termos_header": "Termos de Utilização", "termos_check": "Aceito os Termos de Utilização de Portugal.",
        "header_dados": "Carregamento de Produtos", "btn_excel": "Carregar folha de cálculo",
        "mapeamento": "Mapeamento Sugerido:", "btn_analisar": "Analisar Mercado Ibérico/UE", 
        "grafico_opcoes": ["Status (Risco)", "Marketplace", "Linha (Categoria)", "Volume de Procura", "Matriz"],
        "download_btn": "Descarregar Folha", "hist_titulo": "📜 Histórico de Consultas"
    },
    "USA 🇺🇸": {
        "id": "US", "moeda": "$", "lang": "en", "domain": "google.com", "gl": "us", "loc": "United States",
        "titulo": "USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "btn_confirmar": "Confirm Key",
        "legenda_html": "<div style='font-size: 0.9rem;'><b>Risk Status</b><br>✅ Winning<br>⚠️ Expensive<br>🟥 Alert<br><br><b>Trend</b><br>📈 Rising<br>➡️ Flat<br>📉 Falling</div>",
        "termos_header": "Terms of Use", "termos_check": "I accept the USA Terms.",
        "header_dados": "Product Upload", "btn_excel": "Upload Spreadsheet",
        "mapeamento": "Suggested Mapping:", "btn_analisar": "Start Market Analysis", 
        "grafico_opcoes": ["Status (Risk)", "Marketplace", "Line (Category)", "Market Demand", "Matrix"],
        "download_btn": "Download Sheet", "hist_titulo": "📜 Search History"
    }
}
# --- FUNÇÕES ---
def identificar_coluna(lista, chaves):
    for c in lista:
        if any(k in str(c).lower().strip() for k in chaves): return lista.index(c)
    return 0

def enviar_email_log(n, e, m):
    try:
        origem, senha = st.secrets["EMAIL_ORIGEM"], st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, "contato@vembrincarcomagente.com", f"[SUPORTE] - {n}"
        msg.attach(MIMEText(f"Contato: {n}\nEmail: {e}\n\nMsg: {m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10); s.starttls(); s.login(origem, senha); s.sendmail(origem, "contato@vembrincarcomagente.com", msg.as_string()); s.quit()
        return True
    except: return False

# --- CONTROLE DE SESSÃO ---
if "api_key" not in st.session_state: st.session_state.api_key = None
if "df_final" not in st.session_state: st.session_state.df_final = None
if "historico_global" not in st.session_state: st.session_state.historico_global = pd.DataFrame()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Região")
    pais_sel = st.selectbox("Selecione:", list(idiomas.keys()), key="pais_main")
    if "pais_anterior" not in st.session_state: st.session_state.pais_anterior = pais_sel
    if st.session_state.pais_anterior != pais_sel:
        st.session_state.df_final = None
        st.session_state.pais_anterior = pais_sel
        st.rerun()

    t = idiomas[pais_sel]
    api_key_input = st.text_input(t["label_chave"], type="password", value=st.session_state.api_key or "")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input
        st.success("Ativado!")
    
    scope_pt = "Apenas Portugal"
    if "Portugal" in pais_sel: scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])
    
    st.divider(); st.markdown(t["legenda_html"], unsafe_allow_html=True)
    st.divider(); st.header("Suporte")
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
    # CARREGAMENTO (PERSISTENTE)
    if st.session_state.df_final is None:
        fonte = st.radio("Fonte:", ["Planilha", "Bling (API V3)"] if "Brasil" in pais_sel else ["Spreadsheet"], horizontal=True)
        df_base = pd.DataFrame()

        if "Bling" in fonte:
            token_bl = st.text_input("Token Bling:", type="password")
            if st.button("📥 Importar"):
                try:
                    r = requests.get("https://bling.com.br", headers={"Authorization": f"Bearer {token_bl}"})
                    if r.status_code == 200:
                        df_base = pd.DataFrame([{"Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": i.get('categoria',{}).get('nome','Geral'), "ID": i['id']} for i in r.json().get('data', [])])
                except: st.error("Erro API Bling")
        else:
            uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "csv"])
            if uploaded_file:
                df_raw = pd.read_excel(uploaded_file) if not uploaded_file.name.endswith('.csv') else pd.read_csv(uploaded_file)
                cols = df_raw.columns.tolist()
                st.write(f"**{t['mapeamento']}**")
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: col_n = st.selectbox("PRODUTO:", cols, index=identificar_coluna(cols, ['produto', 'nome', 'item', 'name']))
                with c2: col_c = st.selectbox("CUSTO:", cols, index=identificar_coluna(cols, ['custo', 'compra', 'cost', 'price']))
                with c3: col_q = st.selectbox("QTDE:", cols, index=identificar_coluna(cols, ['qtd', 'quantidade', 'stock', 'qty']))
                with c4: col_l = st.selectbox("LINHA:", ["Geral"] + cols, index=identificar_coluna(cols, ['linha', 'categoria'])+1 if identificar_coluna(cols, ['linha', 'categoria']) >= 0 else 0)
                with c5: col_e = st.selectbox("EAN:", ["N/A"] + cols, index=identificar_coluna(cols, ['ean', 'barra', 'upc'])+1 if identificar_coluna(cols, ['ean', 'barra']) >= 0 else 0)
                df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
                df_base['EAN'] = df_raw[col_e] if col_e != "N/A" else ""
                df_base['Linha'] = df_raw[col_l] if col_l != "Geral" else "Geral"
                df_base['ID'] = 0

        if not df_base.empty:
            st.divider()
            ca1, ca2 = st.columns(2)
            with ca1: imposto = st.number_input("% Imposto", 0, 100, 4) / 100
            with ca2: markup = st.number_input("% Markup", 0, 500, 70) / 100
            if st.button(t["btn_analisar"]):
                with st.spinner('Processando...'):
                    res_m, res_l, res_trend, res_vol = [], [], [], []
                    base_bl = ['tiendamia', 'fishpond', 'grandado', 'fruugo', 'desertcart', 'ubuy']
                    if "Brasil" in pais_sel: blacklist = base_bl + ['ebay', 'kidiin', 'kidinn', 'tradeinn', 'vendiloshop', 'aliexpress', 'temu']
                    elif "Portugal" in pais_sel: blacklist = base_bl + (['ebay', 'aliexpress', 'temu'] if scope_pt == "União Europeia" else ['ebay', 'kidiin', 'kidinn', 'tradeinn', 'vendiloshop', 'aliexpress', 'temu'])
                    else: blacklist = base_bl + ['aliexpress', 'temu', 'wish']
                    
                    for idx, row in df_base.iterrows():
                        search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": t["domain"], "hl": t["lang"][:2], "gl": t["gl"], "location": t["loc"], "api_key": st.session_state.api_key})
                        results = search.get_dict(); best_p, best_l, trend, vol = round(row['Custo']*2.2, 2), "N/A", "➡️ Flat", "Baixa"
                        if "shopping_results" in results:
                            validos = [it for it in results['shopping_results'] if not any(b in it.get('source','').lower() or b in it.get('link','').lower() for b in blacklist) and t["moeda"] in str(it.get('price',''))]
                            if validos:
                                b = min(validos, key=lambda x: float(re.sub(r'[^\d,.]','',str(x['price'])).replace('.','').replace(',','.')))
                                best_p, best_l = float(re.sub(r'[^\d,.]','',str(b['price'])).replace('.','').replace(',','.')), b.get('source')
                                vol = "Alta" if sum(v.get('reviews', 0) for v in validos) > 20 else "Média"
                                trend = "📈 Ascendente" if any("sale" in str(it).lower() for it in validos) else "➡️ Flat"
                        res_m.append(best_p); res_l.append(best_l); res_trend.append(trend); res_vol.append(vol)
                    
                    df_base['Mercado'], df_base['Loja Líder'], df_base['Tendência'], df_base['Procura'] = res_m, res_l, res_trend, res_vol
                    df_base['Preço Sugerido'] = df_base.apply(lambda x: round(x['Mercado']*0.98, 2) if (x['Custo']*(1+markup)) > x['Mercado'] else round(x['Custo']*(1+markup), 2), axis=1)
                    df_base['Lucro Total'] = round(((df_base['Preço Sugerido']*(1-imposto)) - df_base['Custo']) * df_base['Qtde'], 2)
                    df_base['Status'] = df_base.apply(lambda x: "🟥" if x['Mercado'] < x['Custo'] else ("⚠️" if (x['Custo']*(1+markup)) > x['Mercado'] else "✅"), axis=1)
                    st.session_state.df_final = df_base
                    st.rerun()

    # EXIBIÇÃO DOS RESULTADOS (DADOS CACHEADOS)
    if st.session_state.df_final is not None:
        df = st.session_state.df_final
        st.divider()
        cf1, cf2 = st.columns(2)
        with cf1: sel_lojas = st.multiselect("Filtrar Marketplaces:", options=df['Loja Líder'].unique(), default=df['Loja Líder'].unique())
        with cf2: sel_linhas = st.multiselect("Filtrar Linhas:", options=df['Linha'].unique(), default=df['Linha'].unique())
        
        df_v = df[(df['Loja Líder'].isin(sel_lojas)) & (df['Linha'].isin(sel_linhas))]
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Investimento", f"{t['moeda']} {(df_v['Custo'] * df_v['Qtde']).sum():,.2f}")
        m2.metric("Lucro Projetado", f"{t['moeda']} {df_v['Lucro Total'].sum():,.2f}")
        m3.metric("Margem", f"{( ( (df_v['Preço Sugerido']*(1-0.04)) - df_v['Custo'] ) / df_v['Preço Sugerido'] ).mean()*100:.1f}%")
        
        st.write("---")
        c_sel, _ = st.columns([0.3, 0.7])
        with c_sel: modo = st.selectbox("Análise Visual:", t["grafico_opcoes"])
        
        color_map = {'✅':'#2ecc71','⚠️':'#f1c40f','🟥':'#e74c3c'}
        if "Status" in modo: fig = px.pie(df_v, names='Status', hole=0.4, color='Status', color_discrete_map=color_map)
        elif "Marketplace" in modo: fig = px.bar(df_v.groupby('Loja Líder')['Lucro Total'].sum().reset_index(), x='Loja Líder', y='Lucro Total', color='Loja Líder', title="Lucro por Marketplace Selecionado")
        elif "Linha" in modo: fig = px.pie(df_v, names='Linha', values='Lucro Total', hole=0.4, title="Lucro por Categoria Selecionada")
        elif "Procura" in modo: fig = px.bar(df_v, x='Nome', y='Qtde', color='Procura', title="Volume de Vendas vs Seu Estoque")
        else: fig = px.scatter(df_v, x='Mercado', y='Lucro Total', size='Qtde', color='Status', color_discrete_map=color_map, hover_name='Nome')
        
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_v[['Nome', 'Linha', 'Qtde', 'Custo', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Status', 'Tendência', 'Procura']])
        if st.button("🗑️ Limpar Análise"): 
            st.session_state.df_final = None
            st.rerun()
