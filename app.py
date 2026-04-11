import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="Analisador de Mercado Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# 2. INSTRUÇÕES PARA O UTILIZADOR (EXIBIDAS NO TOPO)
with st.expander("🔑 COMO OBTER SUA CHAVE DE ACESSO GRATUITA (Obrigatório)", expanded=True):
    st.markdown("""
    Para que o sistema pesquise preços na Amazon, Mercado Livre e outros players, siga estes passos:
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta gratuita.
    2. Confirme o seu e-mail.
    3. No seu painel (Dashboard), copie o código chamado **'API Key'**.
    4. Cole esse código no campo abaixo para ativar o sistema.
    
    *Nota: A conta gratuita permite 100 pesquisas por mês.*
    """)

# 3. CAMPO DE ATIVAÇÃO
api_key = st.text_input("Insira sua SerpApi Key aqui para ativar:", type="password")

if not api_key:
    st.warning("⚠️ O sistema está desativado. Insira a sua chave acima para continuar.")
    st.stop()

st.success("✅ Sistema Ativado! Agora pode subir o seu ficheiro.")

# 4. UPLOAD E MAPEAMENTO
uploaded_file = st.file_uploader("Suba sua planilha Excel aqui", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.markdown("### 🛠️ Configurações de Colunas e Impostos")
    c_map1, c_map2, c_map3 = st.columns(3)
    
    with c_map1:
        col_nome = st.selectbox("Nome do Produto", colunas)
        imposto = st.number_input("Imposto sobre Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Preço de Custo", colunas)
        markup_min = st.slider("Markup de Segurança", 1.1, 1.5, 1.3)
    with c_map3:
        col_ean = st.selectbox("Código EAN (Opcional)", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO"):
        with st.spinner('Consultando Amazon, Magalu, Mercado Livre e RiHappy...'):
            
            df = df_raw.copy()
            res_mercado = []
            res_popularidade = []

            for idx, row in df.iterrows():
                query_extra = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                search = GoogleSearch({
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{query_extra}",
                    "google_domain": "google.com.br",
                    "hl": "pt-br",
                    "gl": "br",
                    "api_key": api_key
                })
                results = search.get_dict()

                if "shopping_results" in results:
                    precos = [item['price_raw'] for item in results['shopping_results']]
                    menor_mercado = min(precos)
                    pop = "🔥 Alta Saída" if len(precos) > 10 else "💎 Colecionável" if len(precos) < 3 else "👍 Estável"
                else:
                    menor_mercado = row[col_custo] * 2
                    pop = "💎 Desconhecido"
                
                res_mercado.append(menor_mercado)
                res_popularidade.append(pop)

            df['Preço Concorrência'] = res_mercado
            df['Potencial de Saída'] = res_popularidade
            
            # Lógica de Preço IA
            df['Markup Sugerido'] = df.apply(lambda x: max((x['Preço Concorrência']*0.97)/x[col_custo], markup_min) if x['Potencial de Saída'] != "💎 Colecionável" else 1.9, axis=1)
            df['Seu Preço Sugerido'] = df[col_custo] * df['Markup Sugerido']
            df['Margem Líquida %'] = (((df['Seu Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço Sugerido']) * 100
            df['Status'] = df.apply(lambda x: "✅ Vencendo" if x['Seu Preço Sugerido'] < x['Preço Concorrência'] else "🟡 Risco", axis=1)

            st.success("Análise Concluída!")
            st.plotly_chart(px.pie(df, names='Status', title="Competitividade Geral"))
            st.dataframe(df)

            # EXPORTAÇÃO
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Resultados", data=output.getvalue(), file_name="analise_mercado.xlsx")
