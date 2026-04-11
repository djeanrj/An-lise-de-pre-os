import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Brasil", layout="wide", page_icon="🇧🇷")

st.title("🚀 Inteligência de Mercado Brasil: Monitor de Preços Real")

# --- PASSO 1: ATIVAÇÃO (CHAVE) ---
st.markdown("### 1️⃣ Ativação do Sistema")
with st.expander("🔑 CLIQUE PARA VER COMO GERAR SUA CHAVE GRATUITA", expanded=True):
    st.markdown("""
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta gratuita.
    2. No seu Dashboard, copie o código chamado **'API Key'**.
    3. Cole esse código no campo abaixo para desbloquear o sistema.
    """)

api_key = st.text_input("Insira sua SerpApi Key aqui:", type="password")

if not api_key:
    st.warning("⚠️ Aguardando chave de ativação para prosseguir...")
    st.stop()

st.success("✅ Sistema Ativado!")
st.divider()

# --- PASSO 2: INSTRUÇÕES E MODELO ---
st.markdown("### 2️⃣ Preparação da Planilha")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.info("""
    **Novidade: Análise de Margem Realista**
    * O sistema agora calcula a margem que você teria caso precise baixar o preço para vencer a concorrência.
    * Bloqueio automático de eBay e lojas internacionais.
    """)

with col_inst2:
    buffer = io.BytesIO()
    exemplo_df = pd.DataFrame({
        "Nome do Produto": ["LEGO Star Wars", "LEGO Technic Ferrari"],
        "Custo": [308.19, 1200.00],
        "EAN": ["673419340526", "673419358514"]
    })
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        exemplo_df.to_excel(writer, index=False, sheet_name='Modelo')
    st.download_button(label="📥 Baixar Planilha Modelo", data=buffer.getvalue(), file_name="modelo_brasil.xlsx")

st.divider()

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
st.markdown("### 3️⃣ Upload e Análise")
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
        col_ean = st.selectbox("Coluna de EAN (Opcional):", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR BUSCA NO MERCADO BRASILEIRO"):
        with st.spinner('Consultando mercado brasileiro e calculando margens...'):
            df = df_raw.copy()
            res_mercado, res_loja = [], []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_ref = row[col_custo]
                
                params = {
                    "engine": "google_shopping", "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br", "hl": "pt-br", "gl": "br",
                    "location": "Brazil", "api_key": api_key
                }
                search = GoogleSearch(params)
                results = search.get_dict()

                melhor_oferta = {"preco": custo_ref * 2, "loja": "Não encontrado"}
                
                if "shopping_results" in results:
                    ofertas_br = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        loja = item.get('source', '').lower()
                        p_raw = item.get('price') or item.get('price_raw')
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'usado', 'minifigura']): continue
                        if any(b in loja for b in ['ebay', 'shopee international', 'tiendamia', 'aliexpress']): continue
                        if "R$" not in str(p_raw): continue

                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor = float(p_limpo)
                                if valor > (custo_ref * 0.5): # Filtro de segurança básico
                                    ofertas_br.append({"preco": valor, "loja": item.get('source', 'Varejo BR')})
                            except: continue
                    
                    if ofertas_br:
                        melhor_oferta = min(ofertas_br, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            df['Preço Concorrência'] = res_mercado
            df['Loja Concorrente'] = res_loja
            df['Seu Preço (Estratégico)'] = df[col_custo] * (1 + (markup_percentual / 100))
            
            # PREÇO SUGERIDO PARA VENCER (2% abaixo da concorrência)
            df['Preço Sugerido'] = df.apply(lambda x: x['Preço Concorrência'] * 0.98 if x['Seu Preço (Estratégico)'] > x['Preço Concorrência'] else x['Seu Preço (Estratégico)'], axis=1)

            # MARGEM LÍQUIDA REALISTA (Baseada no Preço Sugerido)
            # Agora a margem vai variar produto a produto!
            df['Margem Líquida Realista %'] = (((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Preço Sugerido']) * 100
            
            def situacao(row):
                if row['Preço Concorrência'] < row[col_custo]: return "🟥 Burn (Abaixo do Custo)"
                if row['Seu Preço (Estratégico)'] > row['Preço Concorrência']: return "⚠️ Caro"
                return "✅ Vencendo"

            df['Situação'] = df.apply(situacao, axis=1)

            st.success("Análise Concluída!")
            
            def color_margin(val):
                color = 'red' if val < 15 else 'green'
                return f'color: {color}'

            st.subheader("📋 Relatório Final de Precificação")
            # Exibição com foco na Margem Realista que agora varia
            st.dataframe(df[[col_nome, col_custo, 'Seu Preço (Estratégico)', 'Preço Concorrência', 'Loja Concorrente', 'Preço Sugerido', 'Margem Líquida Realista %', 'Situação']].style.map(color_margin, subset=['Margem Líquida Realista %']))
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Planilha Final", data=output.getvalue(), file_name="precificacao_final.xlsx")

