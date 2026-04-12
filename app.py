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
st.set_page_config(page_title="IA Marketplace + Bling Sync", layout="wide", page_icon="🚀")

# --- FUNÇÃO DE LOG E E-MAIL ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    dest = "contato@vembrincarcomagente.com"
    try:
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg['From'], msg['To'], msg['Subject'] = origem, dest, f"[{tipo}] - Usuário: {n}"
        msg.attach(MIMEText(f"Contato: {n}\nEmail: {e}\n\nMensagem:\n{m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587, timeout=10)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- SIDEBAR: CONEXÕES ---
with st.sidebar:
    st.header("🔌 Conexões")
    bling_token = st.text_input("Token API Bling V3:", type="password")
    api_key_input = st.text_input("Sua SerpApi Key:", type="password")
    if st.button("Confirmar Chaves"):
        st.session_state.api_key = api_key_input
        st.success("Conexões salvas!")

    st.divider()
    st.header("🎯 Filtros de Mercado")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy"]
    mkt_filter = st.multiselect("Comparar apenas com:", mkt_options, default="Todos")
    
    st.divider()
    st.header("📖 Help & Legenda")
    st.info("✅ **Vencendo**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Preço abaixo do seu custo.")
    
    st.divider()
    st.header("💬 Assistente Virtual")
    user_q = st.text_input("Dúvida?")
    if user_q:
        if any(w in user_q.lower() for w in ["como usar", "ajuda"]): st.info("🤖: Ative o sistema, carregue os dados e inicie a análise.")
        else:
            with st.form("suporte_form", clear_on_submit=True):
                n, e, m = st.text_input("Nome"), st.text_input("Email"), st.text_area("Mensagem")
                if st.form_submit_button("Enviar"):
                    if enviar_email_log(n, e, m, "SUPORTE"): st.success("✅ Enviado!")

# --- TÍTULO PRINCIPAL ---
st.title("🚀 Inteligência de Mercado Brasil + Bling Sync")

st.markdown("### ⚖️ Termos de Uso")
termos_texto = "Aviso: Dados coletados da internet. O usuário deve validar os resultados antes de alterar preços. Responsabilidade exclusiva do cliente."
st.text_area("Leia atentamente:", termos_texto, height=70)
aceite = st.checkbox("Eu aceito os Termos de Uso.")

if not aceite:
    st.warning("👉 Aceite os termos para prosseguir.")
    st.stop()

st.divider()

# --- PASSO 1: CARREGAMENTO ---
st.markdown("### 1️⃣ Carregamento de Produtos")
fonte = st.radio("Fonte de dados:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)

df_base = pd.DataFrame()
if fonte == "Bling (API V3)":
    if not bling_token: st.warning("Insira o Token do Bling.")
    else:
        if st.button("📥 Importar do Bling"):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Preço Atual": round(float(i.get('preco',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                    st.success("Produtos carregados!")
            except: st.error("Erro na conexão.")
else:
    uploaded_file = st.file_uploader("Suba seu Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        st.info("Mapeie as colunas:")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NOME:", cols)
        with c2: col_c = st.selectbox("CUSTO:", cols)
        with c3: col_q = st.selectbox("QTDE:", cols)
        with c4: col_l = st.selectbox("LINHA:", ["Nenhuma"] + cols)
        with c5: col_e = st.selectbox("EAN:", ["Não possuo"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""; df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"; df_base['ID'] = 0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown("### 2️⃣ Estratégia de Preços")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("Imposto (%)", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("Aumento Padrão (%)", 0, 500, 70) / 100
    if st.button("🚀 INICIAR ANÁLISE REAL"):
        if "api_key" not in st.session_state: st.error("Confirme a SerpApi Key.")
        else:
            with st.spinner('Analisando mercado brasileiro...'):
                df = df_base.copy(); res_m, res_l = [], []
                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": "google.com.br", "hl": "pt-br", "gl": "br", "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "Não encontrado"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            if any(t in it.get('title','').lower() for t in ['peça','manual','led']): continue
                            if "R$" not in str(it.get('price','')): continue
                            if "Todos" not in mkt_filter and not any(f.lower() in it.get('source','').lower() for f in mkt_filter): continue
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
                df['Situação'] = df.apply(lambda x: "🟥 Burn" if x['Mercado'] < x['Custo'] else ("⚠️ Caro" if x['Seu Preço'] > x['Mercado'] else "✅ Vencendo"), axis=1)
                st.session_state.df_final = df

# --- PASSO 3: RESULTADOS, DOWNLOAD E SYNC ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader("📊 Resultados Estratégicos")
    lin_sel = st.selectbox("🔍 Filtrar por Linha:", ["Todas"] + df['Linha'].unique().tolist())
    df_plot = df if lin_sel == "Todas" else df[df['Linha'] == lin_sel]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento", f"R$ {df_plot['Custo'].sum():,.2f}")
    c2.metric("Lucro Projetado", f"R$ {df_plot['Lucro Total'].sum():,.2f}")
    c3.metric("Margem Média", f"{df_plot['Margem %'].mean():.2f}%")
    
    st.plotly_chart(px.pie(df_plot, names='Situação', title="Competitividade", color_discrete_map={'✅ Vencendo':'#2ecc71','⚠️ Caro':'#f1c40f','🟥 Burn':'#e74c3c'}))
    st.dataframe(df_plot[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({
        'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'
    }).map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem %']))

    st.divider(); st.subheader("📥 Exportar Relatório")
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine='xlsxwriter') as wr: df.to_excel(wr, index=False)
    st.download_button(label="Baixar Excel", data=out.getvalue(), file_name="analise.xlsx")

    st.divider()
    if fonte == "Bling (API V3)":
        st.subheader("🔄 Bling Sync")
        cs1, cs2 = st.columns(2)
        with cs1: t_up = st.selectbox("Destino da atualização:", ["Preço Padrão (Geral)", "Preço de Loja Específica"])
        with cs2: id_l = st.text_input("ID da Loja (Se selecionado):")

        if st.button("Aceitar sugestões de preço para o bling e atualizar na plataforma"):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            sucesso, total = 0, len(df)
            barra = st.progress(0); status = st.empty()
            for i, (idx, row) in enumerate(df.iterrows()):
                try:
                    # Endpoint para Preço por Loja (Multiloja)
                    u = f"https://bling.com.br{row['ID']}/lojas/{id_l}" if t_up == "Preço de Loja Específica" and id_l else f"https://bling.com.br{row['ID']}"
                    requests.put(u, json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
                    sucesso += 1
                except: pass
                barra.progress((i+1)/total); status.text(f"Atualizando {i+1}/{total}")
            st.success(f"✅ Sincronizado: {sucesso} itens atualizados!")
