import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# --- PASSO 1: ATIVAÇÃO (CHAVE) ---
st.markdown("### 1️⃣ Ativação do Sistema")
with st.expander("🔑 CLIQUE AQUI PARA SABER COMO GERAR SUA CHAVE GRATUITA", expanded=True):
    st.markdown("""
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta gratuita.
    2. No seu Dashboard, copie o código chamado **'API Key'**.
    3. Cole no campo abaixo.
    """)

api_key = st.text_input("Insira sua SerpApi Key aqui:", type="password")

if not api_key:
    st.warning("⚠️ Aguardando chave de ativação para prosseguir...")
    st.stop()

st.success("✅ Sistema Ativado!")
st.divider()

# --- PASSO 2: INSTRUÇÕES DA PLANILHA ---
st.markdown("### 2️⃣ Preparação da Planilha")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.markdown("""
    **Regras de Ouro para Precisão:**
    *   O sistema ignora preços abaixo do seu custo (anúncios falsos/usados).
    *   Anúncios de peças, manuais e kits de LED são descartados.
    *   **EAN** é fundamental para o robô não confundir os sets.
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
    
    st.download_button(label="📥 Baixar Planilha Exemplo", data=buffer.getvalue(), file_name="modelo_lego.xlsx")

st.divider()

# --- PASSO 3: UPLOAD E ANÁLISE ---
uploaded_file = st.file_uploader("Suba seu arquivo Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.info("Mapeie as colunas:")
    c_map1, c_map2, c_map3 = st.columns(3)
    with c_map1:
        col_nome = st.selectbox("Coluna de NOME:", colunas)
        imposto = st.number_input("Imposto de Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Coluna de CUSTO:", colunas)
        markup_min = st.slider("Markup Mínimo", 1.1, 2.0, 1.3)
    with c_map3:
        col_ean = st.selectbox("Coluna de EAN:", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE"):
        with st.spinner('Filtrando anúncios falsos e consultando mercado...'):
            df = df_raw.copy()
            res_mercado, res_popularidade = [], []

            for idx, row in df.iterrows():
                ean_q = f" {row[col_ean]}" if col_ean != "Não possuo" else ""
                custo_ref = row[col_custo]
                
                search = GoogleSearch({
                    "engine": "google_shopping",
                    "q": f"{row[col_nome]}{ean_q}",
                    "google_domain": "google.com.br", "hl": "pt-br", "gl": "br", "api_key": api_key
                })
                results = search.get_dict()

                precos_validos = []
                if "shopping_results" in results:
                    for item in results['shopping_results']:
                        p_text = item.get('price') or item.get('price_raw')
                        titulo = item.get('title', '').lower()
                        loja = item.get('source', '').lower()
                        
                        # FILTRO 1: Termos de "Sujeira"
                        lixo = ['peça', 'manual', 'led', 'luz', 'compatível', 'similar', 'minifigura', 'usado', 'danificada']
                        if any(t in titulo for t in lixo): continue

                        if p_text:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_text))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            
                            try:
                                valor_num = float(p_limpo)
                                # --- NOVA TRAVA DE SEGURANÇA ---
                                # Se o preço de mercado for MENOR que o seu custo, ignoramos.
                                # Ninguém vende LEGO novo oficial abaixo do preço de custo de entrada.
                                if valor_num > (custo_ref * 1.05): # Considera apenas quem vende com pelo menos 5% de margem sobre o seu custo
                                    precos_validos.append(valor_num)
                            except: continue
                
                if precos_validos:
                    menor_mercado = min(precos_validos)
                    pop = "🔥 Alta Saída" if len(precos_validos) > 5 else "👍 Estável"
                else:
                    menor_mercado = custo_ref * 1.7 # Se não houver concorrência válida, aplica markup padrão
                    pop = "💎 Raro / Exclusivo"
                
                res_mercado.append(menor_mercado)
                res_popularidade.append(pop)

            df['Preço Concorrência'] = res_mercado
            df['Saída'] = res_popularidade
            df['Markup Sugerido'] = df.apply(lambda x: max((x['Preço Concorrência']*0.97)/x[col_custo], markup_min), axis=1)
            df['Seu Preço'] = df[col_custo] * df['Markup Sugerido']
            df['Margem Líquida %'] = (((df['Seu Preço']*(1-imposto))-df[col_custo])/df['Seu Preço'])*100
            
            st.success("Análise Finalizada!")
            st.dataframe(df[[col_nome, col_custo, 'Preço Concorrência', 'Seu Preço', 'Margem Líquida %', 'Saída']])
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Resultados", data=output.getvalue(), file_name="analise_lego_ia.xlsx")

