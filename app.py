import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# 2. SEÇÃO DE INSTRUÇÕES E MODELO
st.markdown("### 1️⃣ Prepare seu Arquivo")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.info("""
    **O sistema precisa de 3 informações básicas:**
    *   **Nome do Produto:** Para a busca no Google/Amazon/ML.
    *   **Custo:** O valor que você pagou (para calcular sua margem).
    *   **EAN (Opcional):** O código de barras garante o preço exato.
    
    *Dica: Você pode usar qualquer nome nas colunas do seu Excel.*
    """)

with col_inst2:
    # CRIAR MODELO PARA DOWNLOAD
    buffer = io.BytesIO()
    exemplo_df = pd.DataFrame({
        "Nome do Produto": ["LEGO Star Wars", "LEGO Technic Ferrari"],
        "Custo": [450.00, 1200.00],
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
with st.expander("🔑 Como obter sua chave gratuita (Obrigatório)", expanded=False):
    st.markdown("""
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta.
    2. No seu Dashboard, copie o código **'API Key'**.
    3. Cole no campo abaixo. A conta gratuita permite 100 buscas mensais.
    """)

api_key = st.text_input("Cole sua SerpApi Key aqui:", type="password")

if not api_key:
    st.warning("⚠️ O sistema está desativado. Insira a chave para continuar.")
    st.stop()

st.success("✅ Sistema Ativado!")

# 4. UPLOAD E MAPEAMENTO
st.divider()
st.markdown("### 3️⃣ Envio e Configuração")
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.success("Arquivo recebido! Mapeie os dados abaixo:")
    c_map1, c_map2, c_map3 = st.columns(3)
    
    with c_map1:
        col_nome = st.selectbox("Selecione a coluna de NOME:", colunas)
        imposto = st.number_input("Imposto sobre Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Selecione a coluna de CUSTO:", colunas)
        markup_min = st.slider("Markup de Segurança", 1.1, 1.5, 1.3)
    with c_map3:
        col_ean = st.selectbox("Selecione a coluna de EAN (Opcional):", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO REAL"):
        with st.spinner('Varrendo Amazon, Mercado Livre, Magalu e outros...'):
            
            df = df_raw.copy()
            res_mercado = []
            res_popularidade = []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                search = GoogleSearch({
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br",
                    "hl": "pt-br", "gl": "br",
                    "api_key": api_key
                })
                results = search.get_dict()

                if "shopping_results" in results:
                    precos = [item['price_raw'] for item in results['shopping_results']]
                    menor_mercado = min(precos)
                    pop = "🔥 Alta Saída" if len(precos) > 10 else "💎 Raro" if len(precos) < 3 else "👍 Estável"
                else:
                    menor_mercado = row[col_custo] * 2
                    pop = "💎 Raro"
                
                res_mercado.append(menor_mercado)
                res_popularidade.append(pop)

            df['Preço Concorrência'] = res_mercado
            df['Potencial de Saída'] = res_popularidade
            
            # IA DE PRECIFICAÇÃO
            def precificar(preco_m, custo, pop):
                alvo = (preco_m * 0.97) / custo
                if pop == "💎 Raro": return max(alvo, 1.9)
                return max(alvo, markup_min)

            df['Markup Sugerido'] = df.apply(lambda x: precificar(x['Preço Concorrência'], x[col_custo], x['Potencial de Saída']), axis=1)
            df['Seu Preço Sugerido'] = df[col_custo] * df['Markup Sugerido']
            df['Status'] = df.apply(lambda x: "✅ Vencendo" if x['Seu Preço Sugerido'] < x['Preço Concorrência'] else "🟡 Risco", axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço Sugerido']) * 100

            st.success("Análise Finalizada!")
            
            # DASHBOARD
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(df, names='Status', title="Competitividade"))
            c2.plotly_chart(px.bar(df, x=col_nome, y='Margem Líquida %', color='Potencial de Saída', title="Margem vs Potencial"))

            st.dataframe(df)

            # DOWNLOAD
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Resultados", data=output.getvalue(), file_name="analise_mercado.xlsx")
