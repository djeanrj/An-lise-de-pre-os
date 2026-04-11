import streamlit as st
import pandas as pd
import plotly.express as px
from serpapi import GoogleSearch
import io
import re

# 1. CONFIGURAÇÃO DA INTERFACE
st.set_page_config(page_title="IA de Precificação Pro", layout="wide", page_icon="📈")

st.title("🚀 Inteligência de Mercado: Monitor de Preços Real")

# --- PASSO 1: ATIVAÇÃO COM INSTRUÇÕES MELHORADAS ---
st.markdown("### 1️⃣ Ativação do Sistema")

with st.expander("👉 CLIQUE AQUI PARA VER O PASSO A PASSO PARA GERAR SUA CHAVE", expanded=True):
    st.markdown("""
    O sistema utiliza o motor de busca do Google para encontrar preços reais. Para isso, você precisa de uma chave gratuita:
    
    1. **Aceda ao site:** [SerpApi.com](https://serpapi.com) e crie uma conta.
    2. **Confirme o e-mail:** Verifique a sua caixa de entrada e clique no link de confirmação.
    3. **Dashboard:** Após logar, você verá o campo **'Your Private API Key'**.
    4. **Copiar:** Clique no ícone de copiar ao lado do código e cole no campo abaixo.
    
    *Nota: O plano gratuito oferece 100 pesquisas por mês sem custo.*
    """)

api_key = st.text_input("Cole sua API Key aqui para desbloquear:", type="password")

if not api_key:
    st.warning("⚠️ O sistema está bloqueado. Insira a chave acima para prosseguir.")
    st.stop()

st.success("✅ Sistema Ativado!")
st.divider()

# --- PASSO 2: INSTRUÇÕES E MODELO ---
st.markdown("### 2️⃣ Preparação da Planilha")
col_inst1, col_inst2 = st.columns(2)

with col_inst1:
    st.markdown("""
    **Como funciona a análise:**
    *   **Seu Preço:** É o seu custo + a % de aumento que você escolher.
    *   **Trava de Segurança:** O sistema ignora preços de mercado menores que o seu custo (usados/falsos).
    *   **Alerta:** Se o lucro final for menor que 15%, o valor aparecerá em **Vermelho**.
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

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
st.markdown("### 3️⃣ Configuração de Venda")
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

    if st.button("🚀 INICIAR ANÁLISE COMPLETA"):
        with st.spinner('Consultando mercado e eliminando anúncios irreais...'):
            df = df_raw.copy()
            res_mercado, res_pop = [], []

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
                        
                        # Filtro de termos irrelevantes
                        if any(t in titulo for t in ['peça', 'manual', 'led', 'luz', 'usado', 'caixa vazia', 'minifigura']): continue

                        if p_text:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_text))
                            if ',' in p_limpo and '.' in p_limpo: p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo: p_limpo = p_limpo.replace(',', '.')
                            try:
                                valor_num = float(p_limpo)
                                # CORREÇÃO: O preço de mercado deve ser no mínimo o seu custo + 5%
                                # Isso ignora anúncios internacionais/usados de R$ 264 para custos de R$ 308
                                if valor_num >= (custo_ref * 1.05): 
                                    precos_validos.append(valor_num)
                            except: continue
                
                # Se não achar preço válido acima do custo, assume um valor de mercado padrão (Custo + 75%)
                res_mercado.append(min(precos_validos) if precos_validos else custo_ref * 1.75)
                res_pop.append("🔥 Alta" if len(precos_validos) > 5 else "💎 Baixa")

            df['Concorrência'] = res_mercado
            df['Popularidade'] = res_pop
            
            # CÁLCULOS
            df['Seu Preço'] = df[col_custo] * (1 + (markup_percentual / 100))
            
            def gerar_sugestao(row):
                if row['Seu Preço'] > row['Concorrência']:
                    return row['Concorrência'] * 0.98
                return row['Seu Preço']

            df['Preço Sugerido'] = df.apply(gerar_sugestao, axis=1)
            df['Status'] = df.apply(lambda x: "✅ Vencendo" if x['Seu Preço'] <= x['Concorrência'] else "⚠️ Caro", axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço']) * 100
            df['Alerta'] = df['Margem Líquida %'].apply(lambda x: "🚨 Margem Baixa!" if x < 15 else "💰 Saudável")

            # EXIBIÇÃO
            st.success("Análise Finalizada!")
            
            def color_margin(val):
                color = 'red' if val < 15 else 'green'
                return f'color: {color}'

            st.subheader("📋 Resultados Detalhados")
            st.dataframe(df[[col_nome, col_custo, 'Seu Preço', 'Concorrência', 'Status', 'Preço Sugerido', 'Margem Líquida %', 'Alerta']].style.map(color_margin, subset=['Margem Líquida %']))
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Analise')
            st.download_button(label="📥 Baixar Relatório Final", data=output.getvalue(), file_name="analise_mercado_lego.xlsx")
