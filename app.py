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

# --- FUNÇÃO DE LOG E E-MAIL (OCULTA) ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    dest = "contato@vembrincarcomagente.com"
    origem = "seu-email-de-envio@gmail.com" 
    senha = "Brincar_01" 
    try:
        msg = MIMEMultipart()
        msg['From'], msg['To'] = origem, dest
        msg['Subject'] = f"[{tipo}] - Usuário: {n}"
        msg.attach(MIMEText(f"Contato: {n}\nEmail: {e}\n\nConteúdo:\n{m}", 'plain'))
        s = smtplib.SMTP("://gmail.com", 587)
        s.starttls(); s.login(origem, senha); s.sendmail(origem, dest, msg.as_string()); s.quit()
        return True
    except: return False

# --- SIDEBAR: CONEXÕES E CHAT IA ---
with st.sidebar:
    st.header("🔌 Conexões")
    bling_token = st.text_input("Token API Bling V3:", type="password")
    api_key_input = st.text_input("Sua SerpApi Key:", type="password")
    if st.button("Confirmar Chaves"):
        st.session_state.api_key = api_key_input
        st.success("Conexões salvas!")

    st.divider()
    st.header("💬 Assistente Virtual")
    user_q = st.text_input("Dúvida?")
    if user_q:
        if any(w in user_q.lower() for w in ["como usar", "ajuda"]): st.info("🤖: Aceite os termos, carregue os dados e inicie a análise.")
        else:
            with st.form("suporte_form", clear_on_submit=True):
                n, e, m = st.text_input("Nome"), st.text_input("Email"), st.text_area("Mensagem")
                if st.form_submit_button("Enviar"):
                    if enviar_email_log(n, e, m, "SUPORTE"): st.success("✅ Enviado!")

    st.divider()
    st.header("📖 Help & Legenda")
    st.info("✅ **Vencendo**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Preço abaixo do seu custo.")

# --- TÍTULO PRINCIPAL ---
st.title("🚀 Inteligência de Mercado Brasil + Bling Sync")

# --- TERMOS DE USO E ISENÇÃO ---
st.markdown("### ⚖️ Termos de Uso e Isenção de Responsabilidade")
termos_texto = """
AVISO IMPORTANTE AOS UTILIZADORES:
1. ORIGEM DOS DADOS: Dados coletados automaticamente da internet. Não garantimos precisão absoluta.
2. OBRIGAÇÃO DE CONFERÊNCIA: O utilizador DEVE checar os resultados antes de qualquer alteração.
3. RESPONSABILIDADE EXCLUSIVA: Decisões efetuadas baseadas nestes dados são de responsabilidade ÚNICA do utilizador.
4. LIMITAÇÃO DE DANOS: Não assumimos responsabilidade por perdas financeiras ou erros de precificação.
"""
st.text_area("Leia com atenção:", termos_texto, height=150)
aceite = st.checkbox("Eu compreendo que os dados vêm da internet e aceito a responsabilidade total pelas minhas decisões.")

if not aceite:
    st.warning("👉 Aceite os termos para desbloquear o sistema.")
    st.stop()

st.divider()

# --- PASSO 1: CARREGAMENTO ---
st.markdown("### 1️⃣ Carregamento de Produtos")
fonte = st.radio("Escolha a fonte:", ["Bling (API V3)", "Excel (Manual)"], horizontal=True)

df_base = pd.DataFrame()
if fonte == "Bling (API V3)":
    if not bling_token: st.warning("Insira o Token do Bling.")
    else:
        if st.button("📥 Importar do Bling"):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": float(i.get('precoCusto',0)), "Preço Atual": float(i.get('preco',0)), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra','')} for i in r.json().get('data', [])])
                    st.success("Produtos carregados!")
            except: st.error("Erro na conexão.")
else:
    uploaded_file = st.file_uploader("Suba seu Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        st.info("Mapeie as colunas:")
        c1, c2, c3, c4 = st.columns(4)
        with c1: col_n = st.selectbox("NOME:", cols)
        with c2: col_c = st.selectbox("CUSTO:", cols)
        with c3: col_q = st.selectbox("QTDE:", cols)
        with c4: col_e = st.selectbox("EAN:", ["Não possuo"] + cols)
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""; df_base['ID'] = 0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown("### 2️⃣ Estratégia de Preços")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("Imposto (%)", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("Aumento Padrão (%)", 0, 500, 70) / 100
    if st.button("🚀 INICIAR ANÁLISE REAL"):
        if "api_key" not in st.session_state: st.error("Confirme a SerpApi Key.")
        else:
            with st.spinner('Varrendo mercado brasileiro (Moeda R$)...'):
                df = df_base.copy(); res_m, res_l = [], []
                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": "google.com.br", "hl": "pt-br", "gl": "br", "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = row['Custo']*2.5, "Não encontrado"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            loja = it.get('source','').lower()
                            if any(t in it.get('title','').lower() for t in ['peça','manual','led']) or any(b in loja for b in ['ebay','aliexpress','international']) or "R$" not in str(it.get('price','')): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.15): validos.append({"p":v, "l":it.get('source')})
                            except: continue
                        if validos:
                            b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                df['Mercado'], df['Loja Líder'] = res_m, res_l
                df['Seu Preço'] = df['Custo'] * (1 + markup_padrao)
                df['Preço Sugerido'] = df.apply(lambda x: x['Mercado']*0.98 if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = (((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100
                df['Lucro Total'] = ((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde']
                df['Situação'] = df.apply(lambda x: "🟥 Burn" if x['Mercado'] < x['Custo'] else ("⚠️ Caro" if x['Seu Preço'] > x['Mercado'] else "✅ Vencendo"), axis=1)
                st.session_state.df_final = df
                
                # ENVIO SILENCIOSO DE LOG DE UTILIZAÇÃO
                log_msg = f"Análise concluída: {len(df)} itens. Lucro Projetado: R$ {df['Lucro Total'].sum():.2f}"
                enviar_email_log("Sistema", "Log Automático", log_msg, "LOG_ATIVIDADE")

# --- PASSO 3: RESULTADOS E SYNC ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader("📊 Resultados")
    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento", f"R$ {(df['Custo']*df['Qtde']).sum():,.2f}")
    c2.metric("Lucro Líquido", f"R$ {df['Lucro Total'].sum():,.2f}")
    c3.metric("Margem Média", f"{df['Margem %'].mean():.1f}%")
    st.plotly_chart(px.pie(df, names='Situação', title="Competitividade", color_discrete_map={'✅ Vencendo':'#2ecc71','⚠️ Caro':'#f1c40f','🟥 Burn':'#e74c3c'}))
    st.dataframe(df[['Nome', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem %']))
    if fonte == "Bling (API V3)":
        if st.button("📤 Sincronizar com Bling"):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("Bling Atualizado!")
