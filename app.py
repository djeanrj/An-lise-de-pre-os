import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA Marketplace Pro BR", layout="wide", page_icon="🇧🇷")

st.title("🚀 Inteligência de Mercado Brasil: Monitor de Preços Real")

# --- PASSO 1: ATIVAÇÃO (CHAVE) ---
st.markdown("### 1️⃣ Ativação do Sistema")
with st.expander("🔑 COMO GERAR SUA CHAVE GRATUITA", expanded=True):
    st.markdown("""
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta.
    2. No seu Dashboard, copie o código chamado **'API Key'**.
    3. Cole o código no campo abaixo e clique no botão de ativar.
    """)

api_key_input = st.text_input("Insira sua SerpApi Key aqui:", type="password")
ativado = st.button("Confirmar Chave e Ativar Sistema")

if not ativado and "api_key" not in st.session_state:
    st.warning("⚠️ Insira a chave e clique no botão para desbloquear.")
    st.stop()

if ativado:
    st.session_state.api_key = api_key_input
    st.success("✅ Sistema Ativado!")

st.divider()

# --- PASSO 2: PREPARAÇÃO DA PLANILHA ---
st.markdown("### 2️⃣ Preparação do Arquivo")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.info("""
    **Instruções de Formato:**
    *   Sua planilha deve conter: **Nome, Custo e Quantidade**.
    *   Opcional: **EAN** (para buscas exatas) e **Linha/Categoria**.
    *   O sistema filtra automaticamente anúncios internacionais e acessórios.
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
        exemplo_df.to_excel(writer, index=False, sheet_name='Modelo')
    st.download_button(label="📥 Baixar Planilha Modelo", data=buffer.getvalue(), file_name="modelo_vendas_br.xlsx")

st.divider()

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
uploaded_file = st.file_uploader("Suba seu arquivo Excel completo", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.sidebar.header("🎯 Filtros e Ajustes")
    mkt_options = ["Todos", "Amazon", "Mercado Livre", "Magalu", "Shopee", "RiHappy", "Americanas", "Casas Bahia"]
    mkt_filter = st.sidebar.multiselect("Considerar apenas estas lojas:", mkt_options, default="Todos")
    
    # MAPEAMENTO DE CAMPOS
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
        col_cat = st.selectbox("Coluna CATEGORIA / LINHA (Opcional):", ["Nenhuma"] + colunas)
        markup_percentual = st.number_input("Seu aumento padrão (%)", 0, 500, 70)
    with c_map5:
        col_ean = st.selectbox("Coluna EAN (Opcional):", ["Não possuo"] + colunas)
        imposto = st.number_input("Imposto de Venda (%)", 0, 100, 4) / 100

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO E ESTOQUE"):
        with st.spinner('Varrendo e-commerces e calculando lucro do estoque...'):
            df = df_raw.copy()
            res_mercado, res_loja = [], []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_ref = row[col_custo]
                
                params = {
                    "engine": "google_shopping", "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br", "hl": "pt-br", "gl": "br",
                    "location": "Brazil", "api_key": st.session_state.api_key
                }
                search = GoogleSearch(params)
                results = search.get_dict()

                melhor_oferta = {"preco": custo_ref * 2.5, "loja": "Não encontrado"}
                
                if "shopping_results" in results:
                    ofertas_br = []
                    for item in results['shopping_results']:
                        titulo = item.get('title', '').lower()
                        loja = item.get('source', '').lower()
                        p_raw = item.get('price') or item.get('price_raw')
                        
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'caixa vazia']): continue
                        if any(b in loja for b in ['ebay', 'shopee international', 'tiendamia']): continue
                        if "R$" not in str(p_raw): continue

                        if "Todos" not in mkt_filter:
                            if not any(f.lower() in loja for f in mkt_filter): continue

                        if p_raw:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_raw))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor = float(p_limpo)
                                if valor > (custo_ref * 0.2): ofertas_br.append({"preco": valor, "loja": item.get('source', 'Varejo BR')})
                            except: continue
                    
                    if ofertas_br: melhor_oferta = min(ofertas_br, key=lambda x: x['preco'])

                res_mercado.append(melhor_oferta['preco'])
                res_loja.append(melhor_oferta['loja'])

            df['Concorrência'] = res_mercado
            df['Loja Líder'] = res_loja
            df['Qtde'] = df[col_quant]
            df['Categoria'] = df[col_cat] if col_cat != "Nenhuma" else "Geral"
            
            # CÁLCULOS FINANCEIROS
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            df['Preço Sugerido'] = df.apply(lambda x: x['Concorrência'] * 0.98 if x['Seu Preço'] > x['Concorrência'] else x['Seu Preço'], axis=1)
            df['Margem Real %'] = (((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Preço Sugerido']) * 100
            df['Lucro Total R$'] = ((df['Preço Sugerido'] * (1 - imposto)) - df[col_custo]) * df['Qtde']
            df['Investimento Estoque'] = df[col_custo] * df['Qtde']

            # FILTRO DE CATEGORIA NO DASHBOARD
            categorias_unicas = df['Categoria'].unique().tolist()
            cat_selecionada = st.selectbox("🔍 Filtrar Dashboard por Categoria:", ["Todas"] + categorias_unicas)
            
            df_plot = df if cat_selecionada == "Todas" else df[df['Categoria'] == cat_selecionada]

            # MÉTRICAS
            st.subheader(f"📊 Resumo Financeiro: {cat_selecionada}")
            m1, m2, m3 = st.columns(3)
            m1.metric("Investimento Total", f"R$ {df_plot['Investimento Estoque'].sum():,.2f}")
            m2.metric("Lucro Líquido Projetado", f"R$ {df_plot['Lucro Total R$'].sum():,.2f}")
            m3.metric("Margem Média", f"{df_plot['Margem Real %'].mean():.1f}%")

            # GRÁFICOS
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(px.pie(df_plot, names='Loja Líder', title="Quem domina os preços?"), use_container_width=True)
            with c2:
                # DESTAQUE: Produtos mais valiosos em R$ no gráfico de barras
                st.plotly_chart(px.bar(df_plot.sort_values('Lucro Total R$', ascending=False), 
                                       x=col_nome, y='Lucro Total R$', color='Categoria',
                                       title="Ranking: Produtos mais lucrativos do Estoque (R$)"), use_container_width=True)

            # TABELA FINAL
            st.subheader("📋 Detalhes dos Itens")
            st.dataframe(df_plot[[col_nome, 'Categoria', 'Qtde', col_custo, 'Seu Preço', 'Concorrência', 'Loja Líder', 'Preço Sugerido', 'Margem Real %', 'Lucro Total R$']])

            # DOWNLOAD
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise_Completa')
            st.download_button(label="📥 Baixar Relatório Estratégico", data=output.getvalue(), file_name="analise_ia_lego_estoque.xlsx")
