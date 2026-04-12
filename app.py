import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA Marketplace Pro BR", layout="wide", page_icon="🇧🇷")

st.title("🚀 Inteligência de Mercado Brasil: Monitor de Preços Real")

# --- SIDEBAR: CONFIGURAÇÕES E AJUDA ---
with st.sidebar:
    st.header("🎯 Filtros de Mercado")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy", "Americanas", "Casas Bahia", "Ponto", "Extra"]
    mkt_filter = st.multiselect("Considerar apenas estas lojas:", mkt_options, default="Todos")
    
    st.divider()
    
    st.header("📖 Central de Ajuda")
    st.info("""
    **Dicionário de Colunas:**
    *   **Seu Preço:** Custo + seu aumento (%) escolhido.
    *   **Concorrência:** Menor preço real encontrado no Brasil (R$).
    *   **Preço Sugerido:** Valor ideal para vencer o mercado (-2%).
    *   **Margem Real %:** Lucro líquido após imposto e custo.
    
    **Status de Situação:**
    *   ✅ **Vencendo:** Seu preço já é o menor.
    *   ⚠️ **Caro:** Acima da concorrência (ajuste necessário).
    *   🟥 **Burn:** Concorrência vende abaixo do seu custo.
    """)

# --- PASSO 1: ATIVAÇÃO ---
st.markdown("### 1️⃣ Ativação do Sistema")
with st.expander("🔑 COMO GERAR SUA CHAVE GRATUITA", expanded=False):
    st.markdown("""
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)**.
    2. Crie uma conta e confirme o seu e-mail.
    3. No seu Dashboard, copie o código chamado **'API Key'**.
    4. Cole no campo abaixo e clique no botão de ativar.
    """)

api_key_input = st.text_input("Insira sua SerpApi Key aqui:", type="password")
ativado = st.button("Confirmar Chave e Ativar")

if not ativado and "api_key" not in st.session_state:
    st.warning("⚠️ O sistema está bloqueado. Insira a chave para continuar.")
    st.stop()

if ativado:
    st.session_state.api_key = api_key_input
    st.success("✅ Sistema Ativado!")

st.divider()

# --- PASSO 2: PREPARAÇÃO DO ARQUIVO ---
st.markdown("### 2️⃣ Preparação do Arquivo")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.info("""
    **Instruções de Formato:**
    *   Sua planilha deve conter: **Nome, Custo e Quantidade**.
    *   Opcional: **EAN** (para buscas exatas) e **Categoria**.
    *   O sistema filtra moedas estrangeiras e anúncios de acessórios.
    """)

with col_inst2:
    buffer = io.BytesIO()
    exemplo_df = pd.DataFrame({
        "Nome do Produto": ["LEGO Star Wars", "LEGO Ferrari"],
        "Custo": [308.19, 1200.00],
        "Quantidade": [5, 2],
        "Linha": ["Star Wars", "Technic"],
        "EAN": ["673419340526", "673419358514"]
    })
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        exemplo_df.to_excel(writer, index=False)
    st.download_button(label="📥 Baixar Planilha Modelo", data=buffer.getvalue(), file_name="modelo_vendas_brasil.xlsx")

st.divider()

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
uploaded_file = st.file_uploader("Suba seu arquivo Excel completo", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.info("Identifique as colunas do seu arquivo:")
    c_map1, c_map2, c_map3 = st.columns(3)
    c_map4, c_map5 = st.columns(2)
    
    with c_map1:
        col_nome = st.selectbox("Coluna NOME:", colunas)
    with c_map2:
        col_custo = st.selectbox("Coluna CUSTO:", colunas)
    with c_map3:
        col_quant = st.selectbox("Coluna QUANTIDADE:", colunas)
    with c_map4:
        col_cat = st.selectbox("Coluna CATEGORIA (Opcional):", ["Nenhuma"] + colunas)
        markup_percentual = st.number_input("Seu aumento padrão (%)", 0, 500, 70)
    with c_map5:
        col_ean = st.selectbox("Coluna EAN (Opcional):", ["Não possuo"] + colunas)
        imposto = st.number_input("Imposto de Venda (%)", 0, 100, 4) / 100

    if st.button("🚀 INICIAR ANÁLISE COMPLETA"):
        with st.spinner('Consultando mercado brasileiro e calculando lucro do estoque...'):
            df = df_raw.copy()
            res_mercado, res_loja = [], []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_ref = row[col_custo]
                
                params = {
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br", "hl": "pt-br", "gl": "br",
                    "location": "Brazil", "api_key": st.session_state.api_key
                }
                search = GoogleSearch(params)
                results = search.get_dict()

                melhor_oferta = {"preco": custo_ref * 2.5, "loja": "Não encontrado no BR"}
                
                if "shopping_results" in results:
                    ofertas_validas = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        loja_nome = item.get('source', '')
                        loja_lower = loja_nome.lower()
                        p_raw = item.get('price') or item.get('price_raw')
                        
                        # FILTROS DE SEGURANÇA BRASIL
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'adesivo']): continue
                        bloqueio_int = ['aliexpress', 'ebay', 'tiendamia', 'international', 'china', 'importado']
                        if any(b in loja_lower for b in bloqueio_int): continue
                        if "R$" not in str(p_raw): continue

                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor = float(p_limpo)
                                if "Todos" not in mkt_filter:
                                    if not any(f.lower() in loja_lower for f in mkt_filter): continue
                                if valor > (custo_ref * 0.15): 
                                    ofertas_validas.append({"preco": valor, "loja": loja_nome})
                            except: continue
                    
                    if ofertas_validas: melhor_oferta = min(ofertas_validas, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            df['Concorrência'] = res_mercado
            df['Loja Líder'] = res_loja
            df['Qtde'] = df[col_quant]
            df['Categoria'] = df[col_cat] if col_cat != "Nenhuma" else "Geral"
            
            # CÁLCULOS
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            df['Preço Sugerido'] = df.apply(lambda x: x['Concorrência'] * 0.98 if x['Seu Preço'] > x['Concorrência'] else x['Seu Preço'], axis=1)
            df['Margem Real %'] = (((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Preço Sugerido']) * 100
            df['Lucro Total R$'] = ((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) * df['Qtde']
            df['Investimento'] = df[col_custo] * df['Qtde']

            def sit(row):
                if row['Concorrência'] < row[col_custo]: return "🟥 Burn (Abaixo Custo)"
                if row['Seu Preço'] > row['Concorrência']: return "⚠️ Caro"
                return "✅ Vencendo"
            df['Situação'] = df.apply(sit, axis=1)

            st.success("Análise Brasil Concluída!")
            
            # DASHBOARD
            categorias = df['Categoria'].unique().tolist()
            cat_sel = st.selectbox("🔍 Filtrar Dashboard por Categoria:", ["Todas"] + categorias)
            df_plot = df if cat_sel == "Todas" else df[df['Categoria'] == cat_sel]

            m1, m2, m3 = st.columns(3)
            m1.metric("Investimento Total", f"R$ {df_plot['Investimento'].sum():,.2f}")
            m2.metric("Lucro Líquido Total", f"R$ {df_plot['Lucro Total R$'].sum():,.2f}")
            m3.metric("Margem Média", f"{df_plot['Margem Real %'].mean():.1f}%")

            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.pie(df_plot, names='Situação', title="Status de Competitividade", color_discrete_map={'✅ Vencendo':'#2ecc71', '⚠️ Caro':'#f1c40f', '🟥 Burn (Abaixo Custo)':'#e74c3c'}), use_container_width=True)
            with c2: st.plotly_chart(px.bar(df_plot.sort_values('Lucro Total R$', ascending=False), x=col_nome, y='Lucro Total R$', color='Situação', title="Ranking de Lucro por Produto (R$)", color_discrete_map={'✅ Vencendo':'#2ecc71', '⚠️ Caro':'#f1c40f', '🟥 Burn (Abaixo Custo)':'#e74c3c'}), use_container_width=True)

            st.subheader("📋 Detalhes dos Itens")
            st.dataframe(df_plot[[col_nome, 'Categoria', 'Qtde', col_custo, 'Seu Preço', 'Concorrência', 'Loja Líder', 'Preço Sugerido', 'Margem Real %', 'Situação', 'Lucro Total R$']].style.map(lambda x: 'color: red' if isinstance(x, (int, float)) and x < 15 else 'color: green', subset=['Margem Real %']))

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Relatório Completo", data=output.getvalue(), file_name="analise_ia_brasil.xlsx")
