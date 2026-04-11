import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# --- PASSO 1: ATIVAÇÃO ---
st.markdown("### 1️⃣ Ativação do Sistema")
with st.expander("🔑 COMO GERAR SUA CHAVE GRATUITA", expanded=True):
    st.markdown("""
    1. Acesse [SerpApi.com](https://serpapi.com) e crie uma conta.
    2. No Dashboard, copie a **'API Key'** e cole abaixo.
    """)

api_key = st.text_input("Cole sua API Key aqui:", type="password")

if not api_key:
    st.warning("⚠️ O sistema está bloqueado. Insira a chave acima.")
    st.stop()

st.divider()

# --- PASSO 2: PREPARAÇÃO ---
st.markdown("### 2️⃣ Preparação e Modelo")
col_inst1, col_inst2 = st.columns(2)
with col_inst1:
    st.info("""
    **Transparência de Mercado:**
    * O sistema mostrará o **menor preço real** e a **loja** que o pratica.
    * Se o preço estiver abaixo do seu custo, o sistema marcará como 🟥 **Preço Crítico**.
    """)
with col_inst2:
    buffer = io.BytesIO()
    exemplo_df = pd.DataFrame({"Nome": ["LEGO 10280"], "Custo": [308.19], "EAN": ["673419340526"]})
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        exemplo_df.to_excel(writer, index=False)
    st.download_button(label="📥 Baixar Planilha Exemplo", data=buffer.getvalue(), file_name="modelo.xlsx")

st.divider()

# --- PASSO 3: UPLOAD E ANÁLISE ---
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    c_map1, c_map2, c_map3 = st.columns(3)
    with c_map1:
        col_nome = st.selectbox("Coluna de NOME:", colunas)
        imposto = st.number_input("Imposto de Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Coluna de CUSTO:", colunas)
        markup_percentual = st.number_input("Seu aumento padrão (%)", 0, 500, 70)
    with c_map3:
        col_ean = st.selectbox("Coluna de EAN:", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO"):
        with st.spinner('Consultando lojas e validando preços...'):
            df = df_raw.copy()
            res_mercado, res_loja = [], []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                search = GoogleSearch({
                    "engine": "google_shopping", "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br", "hl": "pt-br", "gl": "br", "api_key": api_key
                })
                results = search.get_dict()

                melhor_oferta = {"preco": row[col_custo] * 2, "loja": "Não encontrado"}
                
                if "shopping_results" in results:
                    ofertas_validas = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        # Filtro apenas para remover acessórios/peças (sujeira pesada)
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'caixa vazia']): continue
                        
                        p_raw = item.get('price') or item.get('price_raw')
                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor = float(p_limpo)
                                ofertas_validas.append({"preco": valor, "loja": item.get('source', 'Desconhecida')})
                            except: continue
                    
                    if ofertas_validas:
                        # Pega a oferta com o menor preço real encontrado
                        melhor_oferta = min(ofertas_validas, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            df['Preço Concorrência'] = res_mercado
            df['Loja Concorrente'] = res_loja
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            
            # ANÁLISE DE SAÚDE DO PREÇO
            def analisar_situacao(row):
                if row['Preço Concorrência'] < row[col_custo]:
                    return "🟥 Preço Crítico (Abaixo do Custo)"
                if row['Seu Preço'] > row['Preço Concorrência']:
                    return "⚠️ Caro"
                return "✅ Vencendo"

            df['Situação'] = df.apply(analisar_situacao, axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço']) * 100

            st.success("Análise Finalizada!")
            
            # Exibe a tabela com as novas colunas de confirmação
            st.subheader("📋 Relatório de Verificação")
            st.dataframe(df[[col_nome, col_custo, 'Seu Preço', 'Preço Concorrência', 'Loja Concorrente', 'Situação', 'Margem Líquida %']])
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise_Completa')
            st.download_button(label="📥 Baixar Relatório para Excel", data=output.getvalue(), file_name="verificacao_mercado.xlsx")

