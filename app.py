import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from serpapi import GoogleSearch
import io
import re
import time

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA Marketplace + Bling Sync", layout="wide", page_icon="🇧🇷")

st.title("🚀 Inteligência de Mercado Brasil + Bling Sync")

# --- SIDEBAR: CONEXÕES E AJUDA ---
with st.sidebar:
    st.header("🔌 Conexões")
    bling_token = st.text_input("Token API Bling V3:", type="password")
    api_key_input = st.text_input("Sua SerpApi Key:", type="password")
    ativar_api = st.button("Confirmar Chaves")
    
    if ativar_api:
        st.session_state.api_key = api_key_input
        st.success("Conexões salvas!")

    st.divider()
    st.header("🎯 Filtros de Mercado")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy", "Americanas"]
    mkt_filter = st.multiselect("Comparar com:", mkt_options, default="Todos")
    
    st.divider()
    st.header("📖 Help & Legenda")
    st.info("""
    *   **✅ Vencendo:** Seu preço já é o menor.
    *   **⚠️ Caro:** Precisa baixar para o sugerido.
    *   **🟥 Burn:** Mercado vende abaixo do seu custo.
    *   **🚨 Margem:** Vermelho se lucro líquido < 15%.
    """)

# --- PASSO 1: FONTE DE DADOS ---
st.markdown("### 1️⃣ Carregamento de Produtos")
fonte = st.radio("Escolha como carregar os dados:", ["Importar do Bling (API V3)", "Subir Excel (Manual)"], horizontal=True)

df_base = pd.DataFrame()

if fonte == "Importar do Bling (API V3)":
    if not bling_token:
        st.warning("Insira o Token do Bling na barra lateral.")
    else:
        if st.button("📥 Buscar Produtos no Bling"):
            try:
                url = "https://bling.com.br"
                headers = {"Authorization": f"Bearer {bling_token}"}
                res = requests.get(url, headers=headers)
                if res.status_code == 200:
                    dados = res.json().get('data', [])
                    lista = []
                    for item in dados:
                        lista.append({
                            "ID": item['id'],
                            "Nome": item['nome'],
                            "Custo": float(item.get('precoCusto', 0)),
                            "Preço Atual": float(item.get('preco', 0)),
                            "Qtde": float(item.get('estoque', {}).get('quantidade', 1) or 1),
                            "EAN": item.get('codigoBarra', ''),
                            "Categoria": "Bling"
                        })
                    df_base = pd.DataFrame(lista)
                    st.success(f"{len(df_base)} produtos carregados com sucesso!")
                else: st.error("Erro na API Bling. Verifique se o Token é V3.")
            except Exception as e: st.error(f"Erro: {e}")

else:
    uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])
    if uploaded_file:
        df_raw = pd.read_excel(uploaded_file)
        colunas = df_raw.columns.tolist()
        st.info("Mapeie as colunas do seu Excel:")
        c1, c2, c3, c4 = st.columns(4)
        with c1: col_n = st.selectbox("NOME:", colunas)
        with c2: col_c = st.selectbox("CUSTO:", colunas)
        with c3: col_q = st.selectbox("QTDE:", colunas)
        with c4: col_e = st.selectbox("EAN:", ["Não possuo"] + colunas)
        
        df_base = df_raw.copy()
        df_base.rename(columns={col_n: 'Nome', col_c: 'Custo', col_q: 'Qtde'}, inplace=True)
        df_base['EAN'] = df_raw[col_e] if col_e != "Não possuo" else ""
        df_base['Preço Atual'] = 0.0
        df_base['ID'] = 0

# --- PASSO 2: ANÁLISE ---
if not df_base.empty:
    st.divider()
    st.markdown("### 2️⃣ Estratégia de Preços")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        imposto = st.number_input("Imposto sobre Venda (%)", 0, 100, 4) / 100
    with col_p2:
        markup_alvo = st.number_input("Seu aumento padrão (%)", 0, 500, 70) / 100

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO REAL"):
        if "api_key" not in st.session_state:
            st.error("Por favor, confirme sua SerpApi Key na barra lateral.")
        else:
            with st.spinner('Consultando Amazon, ML e Magalu...'):
                df = df_base.copy()
                res_mercado, res_loja = [], []

                for idx, row in df.iterrows():
                    query = f"{row['Nome']} {row['EAN']}"
                    search = GoogleSearch({
                        "engine": "google_shopping", "q": query, "google_domain": "google.com.br",
                        "hl": "pt-br", "gl": "br", "location": "Brazil", "api_key": st.session_state.api_key
                    })
                    results = search.get_dict()
                    
                    melhor_p, melhor_l = row['Custo'] * 2.5, "Não encontrado"
                    if "shopping_results" in results:
                        ofertas = []
                        for item in results['shopping_results']:
                            loja = item.get('source', '')
                            # Filtros de Segurança
                            if any(t in item.get('title','').lower() for t in ['peça','manual','led','luz']): continue
                            if any(b in loja.lower() for b in ['ebay','aliexpress','international']): continue
                            if "R$" not in str(item.get('price','')): continue
                            if "Todos" not in mkt_filter and not any(f.lower() in loja.lower() for f in mkt_filter): continue
                            
                            try:
                                v = float(re.sub(r'[^\d,.]', '', str(item.get('price'))).replace('.','').replace(',','.'))
                                if v > (row['Custo'] * 0.15): ofertas.append({"p": v, "l": loja})
                            except: continue
                        if ofertas:
                            best = min(ofertas, key=lambda x: x['p'])
                            melhor_p, melhor_l = best['p'], best['l']
                    
                    res_mercado.append(melhor_p)
                    res_loja.append(melhor_l)

                df['Concorrência'] = res_mercado
                df['Loja Líder'] = res_loja
                df['Preço Sugerido'] = df.apply(lambda x: x['Concorrência'] * 0.98 if (x['Custo']*(1+markup_alvo)) > x['Concorrência'] else (x['Custo']*(1+markup_alvo)), axis=1)
                df['Margem Real %'] = (((df['Preço Sugerido']*(1-imposto)) - df['Custo']) / df['Preço Sugerido']) * 100
                df['Lucro Total R$'] = ((df['Preço Sugerido']*(1-imposto)) - df['Custo']) * df['Qtde']
                
                def situacao(row):
                    if row['Concorrência'] < row['Custo']: return "🟥 Burn"
                    if (row['Custo']*(1+markup_alvo)) > row['Concorrência']: return "⚠️ Caro"
                    return "✅ Vencendo"
                df['Situação'] = df.apply(situacao, axis=1)
                
                st.session_state.df_resultado = df

# --- PASSO 3: RESULTADOS E SYNC ---
if "df_resultado" in st.session_state:
    df = st.session_state.df_resultado
    
    st.divider()
    st.subheader("📊 Dashboard Financeiro")
    c1, c2, c3 = st.columns(3)
    c1.metric("Investimento Total", f"R$ {(df['Custo']*df['Qtde']).sum():,.2f}")
    c2.metric("Lucro Líquido Projetado", f"R$ {df['Lucro Total R$'].sum():,.2f}")
    c3.metric("Margem Média", f"{df['Margem Real %'].mean():.1f}%")

    st.plotly_chart(px.pie(df, names='Situação', title="Status de Competitividade", 
                           color_discrete_map={'✅ Vencendo':'#2ecc71', '⚠️ Caro':'#f1c40f', '🟥 Burn':'#e74c3c'}))

    st.subheader("📋 Relatório Final")
    st.dataframe(df[['Nome', 'Custo', 'Concorrência', 'Loja Líder', 'Preço Sugerido', 'Margem Real %', 'Situação', 'Lucro Total R$']].style.map(
        lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem Real %']))

    if fonte == "Importar do Bling (API V3)":
        st.divider()
        st.subheader("🔄 Bling Sync")
        if st.button("📤 Sincronizar Preços Sugeridos com o Bling agora"):
            headers = {"Authorization": f"Bearer {bling_token}", "Content-Type": "application/json"}
            sucesso = 0
            progresso = st.progress(0)
            for i, (idx, row) in enumerate(df.iterrows()):
                payload = {"preco": round(row['Preço Sugerido'], 2)}
                res_put = requests.put(f"https://bling.com.br{row['ID']}", json=payload, headers=headers)
                if res_put.status_code in [200, 204]: sucesso += 1
                progresso.progress((i + 1) / len(df))
            st.success(f"Sincronização concluída! {sucesso} de {len(df)} itens atualizados.")
