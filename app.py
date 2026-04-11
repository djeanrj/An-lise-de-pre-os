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
    
    *Nota: A conta gratuita permite 100 pesquisas mensais.*
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
    **Regras de Localização e Filtros:**
    * Busca restrita ao **Mercado Brasileiro** (Google Shopping BR).
    * Filtro obrigatório de moeda **R$**.
    * **Bloqueio Internacional:** Ignora eBay, Shopee International e similares.
    * **Lojas .com:** Aceita domínios .com que operem no Brasil em Reais.
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
    
    st.download_button(
        label="📥 Baixar Planilha Modelo",
        data=buffer.getvalue(),
        file_name="modelo_brasil.xlsx",
        mime="application/vnd.ms-excel"
    )

st.divider()

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
st.markdown("### 3️⃣ Upload e Análise")
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.success("Arquivo recebido!")
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
        with st.spinner('Varrendo e-commerces brasileiros e filtrando anúncios...'):
            
            df = df_raw.copy()
            res_mercado = []
            res_loja = []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_ref = row[col_custo]
                
                # PARÂMETROS DE BUSCA RESTRITOS AO BRASIL
                params = {
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br",
                    "hl": "pt-br",
                    "gl": "br",
                    "location": "Brazil",
                    "api_key": api_key
                }
                search = GoogleSearch(params)
                results = search.get_dict()

                melhor_oferta = {"preco": custo_ref * 2, "loja": "Não encontrado no BR"}
                
                if "shopping_results" in results:
                    ofertas_br = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        loja = item.get('source', '').lower()
                        p_raw = item.get('price') or item.get('price_raw')
                        
                        # FILTROS DE SEGURANÇA
                        # 1. Ignora acessórios e ruídos
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'caixa vazia', 'minifigura']): continue
                        
                        # 2. Bloqueio de sites internacionais (eBay incluso)
                        if any(b in loja for b in ['ebay', 'shopee international', 'tiendamia', 'aliexpress', 'china']): continue
                        
                        # 3. Garante moeda em R$
                        if "R$" not in str(p_raw): continue

                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            
                            try:
                                valor = float(p_limpo)
                                # Ignora apenas se for menos de 10% do custo (erro de sistema), 
                                # mas aceita ver Burn de estoque abaixo do custo.
                                if valor > (custo_ref * 0.1):
                                    ofertas_br.append({"preco": valor, "loja": item.get('source', 'Varejo BR')})
                            except: continue
                    
                    if ofertas_br:
                        melhor_oferta = min(ofertas_br, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            df['Preço Concorrência'] = res_mercado
            df['Loja Concorrente'] = res_loja
            
            # CÁLCULOS FINAIS
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            
            def analisar_situacao(row):
                if row['Preço Concorrência'] < row[col_custo]: return "🟥 Burn de Estoque (Abaixo do Custo)"
                if row['Seu Preço'] > row['Preço Concorrência']: return "⚠️ Caro"
                return "✅ Vencendo"

            df['Situação'] = df.apply(analisar_situacao, axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço']) * 100

            st.success("Análise Brasil Concluída!")
            
            # EXIBIÇÃO NA TELA
            def color_margin(val):
                color = 'red' if val < 15 else 'green'
                return f'color: {color}'

            st.subheader("📋 Relatório de Verificação Brasil")
            st.dataframe(df[[col_nome, col_custo, 'Seu Preço', 'Preço Concorrência', 'Loja Concorrente', 'Situação', 'Margem Líquida %']].style.map(color_margin, subset=['Margem Líquida %']))
            
            # DOWNLOAD
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Resultados_BR')
            st.download_button(label="📥 Baixar Planilha Final BR", data=output.getvalue(), file_name="analise_mercado_brasil.xlsx")

