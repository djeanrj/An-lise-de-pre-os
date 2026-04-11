import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# 2. SEÇÃO DE INSTRUÇÕES E MODELO
st.markdown("### 1️⃣ Prepare seu Arquivo")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.info("""
    **O sistema precisa de 3 informações básicas:**
    *   **Nome do Produto:** Ex: LEGO Star Wars.
    *   **Custo:** O valor que você pagou (ICMS 4%).
    *   **EAN (Opcional):** Código de barras para precisão total.
    
    *O robô ignora automaticamente anúncios de peças, manuais e preços irreais.*
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
        file_name="modelo_produtos.xlsx",
        mime="application/vnd.ms-excel"
    )

st.divider()

# 3. ATIVAÇÃO POR CHAVE
st.markdown("### 2️⃣ Ativação do Sistema")
api_key = st.text_input("Cole sua SerpApi Key aqui (obtenha em serpapi.com):", type="password")

if not api_key:
    st.warning("⚠️ Insira a chave para desbloquear as funcionalidades.")
    st.stop()

# 4. UPLOAD E MAPEAMENTO
st.divider()
st.markdown("### 3️⃣ Envio e Configuração")
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.success("Arquivo recebido!")
    c_map1, c_map2, c_map3 = st.columns(3)
    
    with c_map1:
        col_nome = st.selectbox("Coluna de NOME:", colunas)
        imposto = st.number_input("Imposto sobre Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Coluna de CUSTO:", colunas)
        markup_min = st.slider("Markup de Segurança (Mínimo)", 1.1, 2.0, 1.3)
    with c_map3:
        col_ean = st.selectbox("Coluna de EAN (Opcional):", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO REAL"):
        with st.spinner('Limpando ruídos e consultando grandes players...'):
            
            df = df_raw.copy()
            res_mercado = []
            res_popularidade = []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_unitario = row[col_custo]
                
                search = GoogleSearch({
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br",
                    "hl": "pt-br", "gl": "br",
                    "api_key": api_key
                })
                results = search.get_dict()

                precos_validos = []

                if "shopping_results" in results:
                    for item in results['shopping_results']:
                        p_text = item.get('price') or item.get('price_raw')
                        titulo = item.get('title', '').lower()
                        
                        # FILTRO 1: Ignorar acessórios e peças
                        termos_sujeira = ['peça', 'manual', 'led', 'luz', 'compatível', 'similar', 'minifigura', 'acessório', 'expositor']
                        if any(termo in titulo for termo in termos_sujeira):
                            continue

                        if p_text:
                            # Limpeza de moeda e formatação
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_text))
                            if ',' in p_limpo and '.' in p_limpo:
                                p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo:
                                p_limpo = p_limpo.replace(',', '.')
                                
                            try:
                                valor_num = float(p_limpo)
                                # FILTRO 2: Sanidade Financeira (Preço mercado deve ser > 80% do seu custo)
                                # Isso remove o erro de achar anúncios de R$ 35 para itens de R$ 300
                                if valor_num >= (custo_unitario * 0.8):
                                    precos_validos.append(valor_num)
                            except:
                                continue
                
                if precos_validos:
                    menor_mercado = min(precos_validos)
                    pop = "🔥 Alta Saída" if len(precos_validos) > 8 else "👍 Estável"
                else:
                    # Se não achar nada real, assume que é raro e sugere margem cheia
                    menor_mercado = custo_unitario * 1.75
                    pop = "💎 Raro / Sem Concorrência Direta"
                
                res_mercado.append(menor_mercado)
                res_popularidade.append(pop)

            df['Preço Concorrência'] = res_mercado
            df['Potencial de Saída'] = res_popularidade
            
            # LÓGICA DE PRECIFICAÇÃO IA
            def precificar(preco_m, custo, pop):
                # Tenta ser 3% mais barato que a média baixa do mercado
                markup_alvo = (preco_m * 0.97) / custo
                if pop == "💎 Raro / Sem Concorrência Direta": return 1.9
                return max(markup_alvo, markup_min)

            df['Markup Sugerido'] = df.apply(lambda x: precificar(x['Preço Concorrência'], x[col_custo], x['Potencial de Saída']), axis=1)
            df['Seu Preço Sugerido'] = df[col_custo] * df['Markup Sugerido']
            df['Status'] = df.apply(lambda x: "✅ Vencendo" if x['Seu Preço Sugerido'] < x['Preço Concorrência'] else "🟡 Risco", axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço Sugerido']) * 100

            st.success("Análise Finalizada!")
            
            # Dashboards rápidos
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(df, names='Status', title="Competitividade Geral", color_discrete_sequence=['#2ecc71', '#f1c40f']))
            c2.plotly_chart(px.bar(df, x=col_nome, y='Margem Líquida %', color='Potencial de Saída', title="Margem Estimada"))

            st.subheader("📋 Tabela de Resultados")
            st.dataframe(df)

            # DOWNLOAD
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise_IA')
            st.download_button(label="📥 Baixar Planilha Finalizada", data=output.getvalue(), file_name="precificacao_ia_lego.xlsx")

