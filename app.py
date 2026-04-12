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

# --- FUNÇÃO DE LOG E E-MAIL (USANDO SECRETS) ---
def enviar_email_log(n, e, m, tipo="SUPORTE"):
    # Destinatário fixo da sua empresa
    dest = "contato@vembrincarcomagente.com"
    
    try:
        # Puxa credenciais seguras dos Secrets do Streamlit
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"]
        
        msg = MIMEMultipart()
        msg['From'], msg['To'] = origem, dest
        msg['Subject'] = f"[{tipo}] - Usuário: {n}"
        corpo = f"Contato: {n}\nEmail do Cliente: {e}\n\nConteúdo:\n{m}"
        msg.attach(MIMEText(corpo, 'plain'))
        
        s = smtplib.SMTP("://gmail.com", 587)
        s.starttls()
        s.login(origem, senha)
        s.sendmail(origem, dest, msg.as_string())
        s.quit()
        return True
    except Exception as err:
        print(f"Erro de e-mail: {err}")
        return False

# --- SIDEBAR: CONEXÕES, FILTROS E CHAT IA ---
with st.sidebar:
    st.header("🎯 Filtros de Mercado")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy", "Americanas", "Casas Bahia"]
    mkt_filter = st.multiselect("Comparar apenas com:", mkt_options, default="Todos")
    
    st.divider()
    st.header("🔌 Conexões")
    bling_token = st.text_input("Token API Bling V3:", type="password")
    api_key_input = st.text_input("Sua SerpApi Key:", type="password")
    if st.button("Confirmar Chaves"):
        st.session_state.api_key = api_key_input
        st.success("Conexões salvas!")

    st.divider()
    st.header("💬 Assistente Virtual")
    user_q = st.text_input("Dúvida sobre o sistema?")
    if user_q:
        if any(w in user_q.lower() for w in ["como usar", "ajuda", "passo"]): 
            st.info("🤖: Aceite os termos, carregue os dados e inicie a análise.")
        else:
            with st.form("suporte_form", clear_on_submit=True):
                n, e, m = st.text_input("Nome"), st.text_input("Seu Email"), st.text_area("Mensagem")
                if st.form_submit_button("Enviar para Suporte"):
                    if enviar_email_log(n, e, m, "SUPORTE"): st.success("✅ Enviado!")
                    else: st.error("❌ Erro ao enviar.")

    st.divider()
    st.header("📖 Help & Legenda")
    st.info("✅ **Vencendo**: Preço ideal.\n\n⚠️ **Caro**: Acima do mercado.\n\n🟥 **Burn**: Preço abaixo do seu custo.")

# --- TÍTULO PRINCIPAL ---
st.title("🚀 Inteligência de Mercado Brasil + Bling Sync")

# --- TERMOS DE USO E ISENÇÃO ---
st.markdown("### ⚖️ Termos de Uso e Isenção de Responsabilidade")
termos_texto = """
AVISO IMPORTANTE AOS UTILIZADORES:
1. ORIGEM DOS DADOS: Os dados de preços são coletados automaticamente da internet via Google Shopping e podem variar.
2. OBRIGAÇÃO DE CONFERÊNCIA: O utilizador tem a OBRIGAÇÃO de checar os resultados antes de qualquer alteração de preço.
3. RESPONSABILIDADE EXCLUSIVA: Decisões efetuadas sobre os dados são de responsabilidade única e exclusiva do cliente.
4. LIMITAÇÃO DE DANOS: Não assumimos responsabilidade por perdas financeiras ou decisões geradas sobre os dados.
"""
st.text_area("Leia atentamente:", termos_texto, height=150)
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
    if not bling_token: st.warning("Insira o Token do Bling na lateral.")
    else:
        if st.button("📥 Importar do Bling"):
            try:
                h = {"Authorization": f"Bearer {bling_token}"}
                r = requests.get("https://bling.com.br", headers=h)
                if r.status_code == 200:
                    df_base = pd.DataFrame([{"ID": i['id'], "Nome": i['nome'], "Custo": round(float(i.get('precoCusto',0)), 2), "Preço Atual": round(float(i.get('preco',0)), 2), "Qtde": float(i.get('estoque',{}).get('quantidade',1) or 1), "EAN": i.get('codigoBarra',''), "Linha": "Bling"} for i in r.json().get('data', [])])
                    st.success("Produtos carregados!")
            except: st.error("Erro na conexão com Bling.")
else:
    uploaded_file = st.file_uploader("Suba seu Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file); cols = df_raw.columns.tolist()
        st.info("Mapeie as colunas do seu arquivo:")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: col_n = st.selectbox("NOME:", cols)
        with c2: col_c = st.selectbox("CUSTO:", cols)
        with c3: col_q = st.selectbox("QTDE:", cols)
        with c4: col_l = st.selectbox("LINHA/CAT:", ["Nenhuma"] + cols)
        with c5: col_e = st.selectbox("EAN:", ["Não possuo"] + cols)
        
        df_base = df_raw.copy().rename(columns={col_n:'Nome', col_c:'Custo', col_q:'Qtde'})
        df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""
        df_base['Linha'] = df_raw[col_l] if col_l != "Nenhuma" else "Geral"
        df_base['ID'] = 0
        df_base['Preço Atual'] = 0.0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider(); st.markdown("### 2️⃣ Estratégia de Preços")
    cp1, cp2 = st.columns(2)
    with cp1: imposto = st.number_input("Imposto (%)", 0, 100, 4) / 100
    with cp2: markup_padrao = st.number_input("Aumento Padrão (%)", 0, 500, 70) / 100
    
    if st.button("🚀 INICIAR ANÁLISE REAL"):
        if "api_key" not in st.session_state: st.error("Confirme a SerpApi Key na lateral.")
        else:
            with st.spinner('Consultando mercado brasileiro (R$)...'):
                df = df_base.copy(); res_m, res_l = [], []
                for idx, row in df.iterrows():
                    search = GoogleSearch({"engine": "google_shopping", "q": f"{row['Nome']} {row['EAN']}", "google_domain": "google.com.br", "hl": "pt-br", "gl": "br", "api_key": st.session_state.api_key})
                    results = search.get_dict(); best_p, best_l = round(row['Custo']*2.5, 2), "Não encontrado"
                    if "shopping_results" in results:
                        validos = []
                        for it in results['shopping_results']:
                            loja = it.get('source','').lower()
                            if any(t in it.get('title','').lower() for t in ['peça','manual','led']) or any(b in loja for b in ['ebay','aliexpress','international']) or "R$" not in str(it.get('price','')): continue
                            if "Todos" not in mkt_filter and not any(f.lower() in loja for f in mkt_filter): continue
                            try:
                                v = float(re.sub(r'[^\d,.]','',str(it.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo']*0.15): validos.append({"p": round(v,2), "l":it.get('source')})
                            except: continue
                        if validos:
                            b = min(validos, key=lambda x:x['p']); best_p, best_l = b['p'], b['l']
                    res_m.append(best_p); res_l.append(best_l)
                
                df['Mercado'] = res_m; df['Loja Líder'] = res_l
                df['Seu Preço'] = round(df['Custo'] * (1 + markup_padrao), 2)
                df['Preço Sugerido'] = df.apply(lambda x: round(x['Mercado']*0.98, 2) if x['Seu Preço'] > x['Mercado'] else x['Seu Preço'], axis=1)
                df['Margem %'] = round((((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100, 2)
                df['Lucro Total'] = round(((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde'], 2)
                df['Situação'] = df.apply(lambda x: "🟥 Burn" if x['Mercado'] < x['Custo'] else ("⚠️ Caro" if x['Seu Preço'] > x['Mercado'] else "✅ Vencendo"), axis=1)
                st.session_state.df_final = df
                
                log_msg = f"Análise concluída: {len(df)} itens. Lucro Projetado: R$ {df['Lucro Total'].sum():.2f}"
                enviar_email_log("Sistema", "Automático", log_msg, "LOG_ATIVIDADE")

# --- PASSO 3: RESULTADOS ---
if "df_final" in st.session_state:
    df = st.session_state.df_final
    st.divider(); st.subheader("📊 Resultados Estratégicos")
    
    lin_sel = st.selectbox("🔍 Filtrar por Linha/Categoria:", ["Todas"] + df['Linha'].unique().tolist())
    df_plot = df if lin_sel == "Todas" else df[df['Linha'] == lin_sel]

    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento", f"R$ {(df_plot['Custo']*df_plot['Qtde']).sum():,.2f}")
    c2.metric("Lucro Projetado", f"R$ {df_plot['Lucro Total'].sum():,.2f}")
    c3.metric("Margem Média", f"{df_plot['Margem %'].mean():.2f}%")
    
    col_g1, col_g2 = st.columns(2)
    with col_g1: st.plotly_chart(px.pie(df_plot, names='Situação', title="Status de Competitividade", color_discrete_map={'✅ Vencendo':'#2ecc71','⚠️ Caro':'#f1c40f','🟥 Burn':'#e74c3c'}))
    with col_g2: st.plotly_chart(px.bar(df_plot.sort_values('Lucro Total', ascending=False), x='Nome', y='Lucro Total', color='Situação', title="Ranking de Lucro (R$)", color_discrete_map={'✅ Vencendo':'#2ecc71','⚠️ Caro':'#f1c40f','🟥 Burn':'#e74c3c'}))

    st.subheader("📋 Relatório Final")
    st.dataframe(df_plot[['Nome', 'Linha', 'Qtde', 'Custo', 'Seu Preço', 'Mercado', 'Loja Líder', 'Preço Sugerido', 'Margem %', 'Situação', 'Lucro Total']].style.format({
        'Custo': '{:.2f}', 'Seu Preço': '{:.2f}', 'Mercado': '{:.2f}', 'Preço Sugerido': '{:.2f}', 'Margem %': '{:.2f}', 'Lucro Total': '{:.2f}'
    }).map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem %']))

    st.divider()
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Analise_Final')
    st.download_button(label="📥 Baixar Planilha Excel", data=output.getvalue(), file_name="analise_precificacao.xlsx", mime="application/vnd.ms-excel")

    if fonte == "Bling (API V3)":
        if st.button("📤 Sincronizar Preços com Bling"):
            h = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            for i, (idx, row) in enumerate(df.iterrows()):
                requests.put(f"https://bling.com.br{row['ID']}", json={"preco": round(row['Preço Sugerido'], 2)}, headers=h)
            st.success("Preços sincronizados com sucesso!")
