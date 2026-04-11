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
    **Novidades nesta versão:**
    * **Resumo Financeiro:** Veja o lucro total estimado da sua operação.
    * **Filtro de Marketplaces:** No menu lateral, escolha quais lojas comparar.
    * **Gráficos de Performance:** Análise visual de margens e preços.
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
st.markdown("### 3️⃣ Upload e Configuração")
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.sidebar.header("🎯 Filtros de Comparação")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy", "Americanas", "Casas Bahia", "Ponto", "Extra"]
    mkt_filter = st.sidebar.multiselect("Considerar apenas estas lojas:", mkt_options, default="Todos")

    st.info("Ajuste os parâmetros abaixo:")
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
        with st.spinner('Consultando mercado e processando inteligência financeira...'):
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

                melhor_oferta = {"preco": custo_ref * 2.5, "loja": "Não encontrado"}
                
                if "shopping_results" in results:
                    ofertas_validas = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        loja_nome = item.get('source', '')
                        loja_lower = loja_nome.lower()
                        p_raw = item.get('price') or item.get('price_raw')
                        
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'usado', 'caixa vazia']): continue
                        if any(b in loja_lower for b in ['ebay', 'shopee international', 'tiendamia', 'aliexpress']): continue
                        if "R$" not in str(p_raw): continue

                        if "Todos" not in mkt_filter:
                            if not any(f.lower() in loja_lower for f in mkt_filter): continue

                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor = float(p_limpo)
                                if valor > (custo_ref * 0.1):
                                    ofertas_validas.append({"preco": valor, "loja": loja_nome})
                            except: continue
                    
                    if ofertas_validas:
                        melhor_oferta = min(ofertas_validas, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            # CÁLCULOS
            df['Concorrência'] = res_mercado
            df['Loja Líder'] = res_loja
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            df['Preço Sugerido'] = df.apply(lambda x: x['Concorrência'] * 0.98 if x['Seu Preço'] > x['Concorrência'] else x['Seu Preço'], axis=1)
            df['Margem Real %'] = (((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Preço Sugerido']) * 100
            df['Lucro Líquido Unitário'] = (df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]
            
            def situacao(row):
                if row['Concorrência'] < row[col_custo]: return "🟥 Burn (Abaixo do Custo)"
                if row['Seu Preço'] > row['Concorrência']: return "⚠️ Caro"
                return "✅ Vencendo"
            df['Situação'] = df.apply(situacao, axis=1)

            st.success("Análise Concluída!")
            
            # --- GRÁFICOS ---
            c1, c2 = st.columns(2)
            with c1:
                fig_pie = px.pie(df, names='Situação', title="Competitividade Geral", color_discrete_map={'✅ Vencendo':'#2ecc71', '⚠️ Caro':'#f1c40f', '🟥 Burn (Abaixo do Custo)':'#e74c3c'})
                st.plotly_chart(fig_pie, use_container_width=True)
            with c2:
                fig_bar = px.bar(df, x=col_nome, y='Margem Real %', color='Situação', title="Margem Realista por Produto")
                st.plotly_chart(fig_bar, use_container_width=True)

            # --- RESUMO FINANCEIRO ---
            st.subheader("💰 Resumo Financeiro da Operação")
            f1, f2, f3 = st.columns(3)
            f1.metric("Custo Total de Estoque", f"R$ {df[col_custo].sum():,.2f}")
            f2.metric("Faturamento Líquido Estimado", f"R$ {(df['Preço Sugerido']*(1-imposto)).sum():,.2f}")
            f3.metric("Lucro Líquido Total", f"R$ {df['Lucro Líquido Unitário'].sum():,.2f}", delta=f"{df['Margem Real %'].mean():.1f}% (Margem Médio)")

            # TABELA
            def color_margin(val):
                color = 'red' if val < 15 else 'green'
                return f'color: {color}'

            st.subheader("📋 Relatório Final Detalhado")
            st.dataframe(df[[col_nome, col_custo, 'Seu Preço', 'Concorrência', 'Loja Líder', 'Preço Sugerido', 'Margem Real %', 'Situação']].style.map(color_margin, subset=['Margem Real %']))
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Planilha Final", data=output.getvalue(), file_name="precificacao_completa.xlsx")
