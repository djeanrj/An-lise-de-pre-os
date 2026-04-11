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
    Para que o sistema pesquise preços na Amazon, Mercado Livre e outros, você precisa de uma chave de acesso:
    1. Aceda ao site **[SerpApi.com](https://serpapi.com)** e crie uma conta gratuita.
    2. Confirme o seu e-mail.
    3. No seu painel (Dashboard), copie o código chamado **'API Key'**.
    4. Cole esse código no campo abaixo.
    
    *Nota: A conta gratuita permite 100 pesquisas por mês.*
    """)

api_key = st.text_input("Insira sua SerpApi Key aqui para desbloquear o sistema:", type="password")

if not api_key:
    st.warning("⚠️ Aguardando chave de ativação para prosseguir...")
    st.stop()

st.success("✅ Sistema Ativado com Sucesso!")
st.divider()

# --- PASSO 2: INSTRUÇÕES DA PLANILHA ---
st.markdown("### 2️⃣ Preparação da Planilha")
col_inst1, col_inst2 = st.columns([2, 1])

with col_inst1:
    st.markdown("""
    **Como preparar seu arquivo Excel:**
    *   Sua planilha deve ter, no mínimo, o **Nome do Produto** e o **Custo**.
    *   O código **EAN (Barras)** é altamente recomendado para evitar erros de busca.
    *   O sistema ignora automaticamente anúncios de peças, manuais e preços irreais (muito abaixo do custo).
    """)

with col_inst2:
    # CRIAR MODELO PARA DOWNLOAD
    buffer = io.BytesIO()
    exemplo_df = pd.DataFrame({
        "Nome do Produto": ["LEGO Star Wars", "LEGO Technic Ferrari"],
        "Custo": [308.19, 1200.00],
        "EAN": ["673419340526", "673419358514"]
    })
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        exemplo_df.to_excel(writer, index=False, sheet_name='Modelo')
    
    st.download_button(
        label="📥 Baixar Planilha Exemplo",
        data=buffer.getvalue(),
        file_name="modelo_lego.xlsx",
        mime="application/vnd.ms-excel"
    )

st.divider()

# --- PASSO 3: UPLOAD E CONFIGURAÇÃO ---
st.markdown("### 3️⃣ Upload e Análise")
uploaded_file = st.file_uploader("Selecione seu arquivo Excel finalizado", type=["xlsx", "xls"])

if uploaded_file:
    df_raw = pd.read_excel(uploaded_file)
    colunas = df_raw.columns.tolist()
    
    st.info("Mapeie as colunas abaixo para que a IA entenda seu arquivo:")
    c_map1, c_map2, c_map3 = st.columns(3)
    
    with c_map1:
        col_nome = st.selectbox("Coluna de NOME:", colunas)
        imposto = st.number_input("Imposto sobre Venda (%)", 0, 100, 4) / 100
    with c_map2:
        col_custo = st.selectbox("Coluna de CUSTO:", colunas)
        markup_min = st.slider("Markup Mínimo Desejado", 1.1, 2.0, 1.3)
    with c_map3:
        col_ean = st.selectbox("Coluna de EAN (Opcional):", ["Não possuo"] + colunas)

    if st.button("🚀 INICIAR ANÁLISE DE MERCADO"):
        with st.spinner('Consultando preços reais e eliminando ruídos...'):
            
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
                        
                        # Filtro Anti-Peças/Manuais
                        termos_lixo = ['peça', 'manual', 'led', 'luz', 'compatível', 'similar', 'minifigura', 'acessório', 'adesivo']
                        if any(termo in titulo for termo in termos_lixo):
                            continue

                        if p_text:
                            p_limpo = re.sub(r'[^\d,.]', '', str(p_text))
                            if ',' in p_limpo and '.' in p_limpo:
                                p_limpo = p_limpo.replace('.', '').replace(',', '.')
                            elif ',' in p_limpo:
                                p_limpo = p_limpo.replace(',', '.')
                                
                            try:
                                valor_num = float(p_limpo)
                                # FILTRO DE SANIDADE (Mínimo 80% do custo)
                                if valor_num >= (custo_unitario * 0.8):
                                    precos_validos.append(valor_num)
                            except:
                                continue
                
                if precos_validos:
                    menor_mercado = min(precos_validos)
                    pop = "🔥 Alta Saída" if len(precos_validos) > 8 else "👍 Estável"
                else:
                    menor_mercado = custo_unitario * 1.75
                    pop = "💎 Raro / Sem Concorrência Direta"
                
                res_mercado.append(menor_mercado)
                res_popularidade.append(pop)

            df['Preço Concorrência'] = res_mercado
            df['Potencial de Saída'] = res_popularidade
            
            def precificar(preco_m, custo, pop):
                alvo = (preco_m * 0.97) / custo
                if pop == "💎 Raro / Sem Concorrência Direta": return 1.9
                return max(alvo, markup_min)

            df['Markup Sugerido'] = df.apply(lambda x: precificar(x['Preço Concorrência'], x[col_custo], x['Potencial de Saída']), axis=1)
            df['Seu Preço Sugerido'] = df[col_custo] * df['Markup Sugerido']
            df['Status'] = df.apply(lambda x: "✅ Vencendo" if x['Seu Preço Sugerido'] < x['Preço Concorrência'] else "🟡 Risco", axis=1)
            df['Margem Líquida %'] = (((df['Seu Preço Sugerido'] * (1 - imposto)) - df[col_custo]) / df['Seu Preço Sugerido']) * 100

            st.success("Análise Finalizada!")
            
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(df, names='Status', title="Resumo de Competitividade", color_discrete_sequence=['#2ecc71', '#f1c40f']))
            c2.plotly_chart(px.bar(df, x=col_nome, y='Margem Líquida %', color='Potencial de Saída', title="Margem Líquida por Item"))

            st.subheader("📋 Relatório Detalhado")
            st.dataframe(df)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Resultados_IA')
            st.download_button(label="📥 Baixar Planilha com Resultados", data=output.getvalue(), file_name="analise_mercado_final.xlsx")
