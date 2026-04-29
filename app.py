# -*- coding: utf-8 -*-
"""
IA Marketplace Global — Análise de Preços e Concorrência
Versão refatorada com correções de bugs, sugestões de preço por estratégia,
score de procura, recomendação de investimento e gráficos de apoio à decisão.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import requests
from serpapi import GoogleSearch
import io
import re
import time
import smtplib
import statistics
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse

# =============================================================================
# 1. CONFIGURAÇÃO DA INTERFACE
# =============================================================================
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")

# =============================================================================
# 2. DICIONÁRIO DE TRADUÇÃO
# =============================================================================
idiomas = {
    "Brasil 🇧🇷": {
        "id": "BR", "moeda": "R$", "lang": "pt-BR", "domain": "google.com.br",
        "gl": "br", "loc": "Brazil", "currency_format": "BR",
        "titulo": "Inteligência de Mercado Brasil + Bling Sync",
        "label_chave": "SerpApi Key", "btn_confirmar": "Confirmar Chave",
        "termos_check": "Eu aceito os Termos de Uso do Brasil.",
        "btn_excel": "Subir planilha", "btn_analisar": "Iniciar Análise Real",
    },
    "Portugal 🇵🇹": {
        "id": "PT", "moeda": "€", "lang": "pt-PT", "domain": "google.pt",
        "gl": "pt", "loc": "Portugal", "currency_format": "EU",
        "titulo": "Inteligência de Mercado Portugal & UE",
        "label_chave": "Chave SerpApi", "btn_confirmar": "Confirmar Chave",
        "termos_check": "Aceito os Termos de Utilização de Portugal.",
        "btn_excel": "Carregar folha de cálculo", "btn_analisar": "Analisar Mercado Ibérico/UE",
    },
    "USA 🇺🇸": {
        "id": "US", "moeda": "$", "lang": "en", "domain": "google.com",
        "gl": "us", "loc": "United States", "currency_format": "US",
        "titulo": "USA Marketplace Intelligence",
        "label_chave": "SerpApi Key", "btn_confirmar": "Confirm Key",
        "termos_check": "I accept the USA Terms.",
        "btn_excel": "Upload Spreadsheet", "btn_analisar": "Start Market Analysis",
    },
}

# =============================================================================
# 3. WHITELIST E BLACKLIST DE MARKETPLACES POR REGIÃO
# =============================================================================
# Whitelist = vendedores SEDIADOS na região (sem custos de importação)
# Blacklist = sites de importação ou de outras regiões
WHITELIST = {
    "BR": [
        "mercadolivre.com.br", "amazon.com.br", "magazineluiza.com.br", "magalu",
        "americanas.com.br", "submarino.com.br", "shoptime.com.br",
        "casasbahia.com.br", "pontofrio.com.br", "carrefour.com.br",
        "extra.com.br", "fastshop.com.br", "kabum.com.br", "girafa.com.br",
        "shopee.com.br", "ricardoeletro.com.br", "centauro.com.br",
        "netshoes.com.br", "dafiti.com.br", "leroymerlin.com.br",
    ],
    "PT_ONLY": [
        "worten.pt", "fnac.pt", "elcorteingles.pt", "pcdiga.com",
        "auchan.pt", "continente.pt", "radiopopular.pt", "mediamarkt.pt",
        "pixmania.pt", "kuantokusta.pt", "toysrus.pt", "globaldata.pt",
        "phonehouse.pt", "rdgshop.pt", "chip7.pt",
    ],
    "EU": [
        # Portugal
        "worten.pt", "fnac.pt", "elcorteingles.pt", "pcdiga.com", "mediamarkt.pt",
        "kuantokusta.pt", "phonehouse.pt", "radiopopular.pt", "auchan.pt",
        # Espanha
        "amazon.es", "elcorteingles.es", "pccomponentes.com", "fnac.es",
        "mediamarkt.es", "carrefour.es",
        # Alemanha
        "amazon.de", "mediamarkt.de", "otto.de", "saturn.de", "notebooksbilliger.de",
        # Itália (incluindo as mencionadas pelo utilizador)
        "amazon.it", "mediaworld.it", "unieuro.it", "kidinn.com", "vendiloshop.com",
        # França
        "amazon.fr", "fnac.com", "darty.com", "cdiscount.com",
        # Holanda
        "bol.com", "amazon.nl", "coolblue.nl",
        # Multipaís EU (sediados na UE)
        "tradeinn.com",
    ],
    "US": [
        "amazon.com", "ebay.com", "walmart.com", "target.com", "bestbuy.com",
        "newegg.com", "bhphotovideo.com", "homedepot.com", "lowes.com",
        "costco.com", "macys.com", "nordstrom.com", "kohls.com", "wayfair.com",
        "samsclub.com", "staples.com", "officedepot.com",
    ],
}

BLACKLIST_GLOBAL = [
    "aliexpress.com", "temu.com", "wish.com", "tiendamia", "fishpond",
    "grandado", "fruugo", "desertcart", "ubuy", "joom",
]

# Por região, o que NUNCA aceitamos (sobrepõe whitelist se houver conflito)
BLACKLIST_REGIONAL = {
    "BR": BLACKLIST_GLOBAL + ["ebay.com", "kidinn.com", "tradeinn.com", "vendiloshop"],
    "PT_ONLY": BLACKLIST_GLOBAL + ["ebay", "kidinn.com", "tradeinn.com", "vendiloshop"],
    "EU": BLACKLIST_GLOBAL + ["ebay"],
    "US": BLACKLIST_GLOBAL,
}


# =============================================================================
# 4. FUNÇÕES UTILITÁRIAS
# =============================================================================
def identificar_coluna(lista_cols, chaves, default=-1):
    """Identifica a coluna mais provável dado um conjunto de palavras-chave.
    Retorna o índice ou `default` (-1 indica 'não encontrado')."""
    lista_lower = [str(c).lower().strip() for c in lista_cols]
    # Match exato primeiro
    for i, c in enumerate(lista_lower):
        if c in chaves:
            return i
    # Match por substring depois
    for i, c in enumerate(lista_lower):
        if any(k in c for k in chaves):
            return i
    return default


def parse_preco(valor_raw, formato="BR"):
    """Converte string de preço para float, respeitando o formato regional.
    BR/EU: "1.234,56" -> 1234.56 ; US: "1,234.56" -> 1234.56
    Retorna None se não conseguir converter."""
    if valor_raw is None:
        return None
    if isinstance(valor_raw, (int, float)):
        return float(valor_raw) if valor_raw > 0 else None
    s = str(valor_raw).strip()
    if not s:
        return None
    # Manter apenas dígitos, vírgula e ponto
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    try:
        if formato in ("BR", "EU"):
            # Remove separador de milhar (.) e converte vírgula decimal
            s = s.replace(".", "").replace(",", ".")
        else:  # US
            s = s.replace(",", "")
        return float(s) if float(s) > 0 else None
    except ValueError:
        return None


def vendedor_confiavel(item, whitelist, blacklist):
    """True se o item é de um vendedor confiável da região (whitelist) e não está na blacklist.
    Faz match em `source` e em `link` (domínio)."""
    fonte = str(item.get("source", "")).lower()
    link = str(item.get("link", "")).lower()
    try:
        dominio = urlparse(link).netloc.lower()
    except Exception:
        dominio = ""

    blob = f"{fonte} {link} {dominio}"

    # Se aparece na blacklist, descartar imediatamente
    for b in blacklist:
        if b.lower() in blob:
            return False
    # Se a whitelist tem itens, exigir match
    if whitelist:
        return any(w.lower() in blob for w in whitelist)
    return True


def buscar_serpapi(produto, ean, regiao_cfg, whitelist, blacklist, api_key):
    """Faz a pesquisa no Google Shopping via SerpAPI e devolve resultados filtrados.
    Estratégia: pesquisa primeiro por EAN (mais preciso); se vier vazio, pesquisa por nome."""
    resultados_validos = []
    consultas = []
    if ean and str(ean).strip() and str(ean).strip().lower() != "nan":
        consultas.append(f"{ean}")
    consultas.append(f"{produto}")

    for q in consultas:
        try:
            params = {
                "engine": "google_shopping",
                "q": q,
                "google_domain": regiao_cfg["domain"],
                "hl": regiao_cfg["lang"][:2],
                "gl": regiao_cfg["gl"],
                "location": regiao_cfg["loc"],
                "num": 30,
                "api_key": api_key,
            }
            search = GoogleSearch(params)
            results = search.get_dict()
        except Exception as e:
            st.warning(f"Falha SerpAPI para '{q}': {e}")
            continue

        if "error" in results:
            st.warning(f"SerpAPI: {results['error']}")
            continue

        for item in results.get("shopping_results", []):
            if not vendedor_confiavel(item, whitelist, blacklist):
                continue
            # Preferir extracted_price (numérico) quando existe
            preco = item.get("extracted_price")
            if preco is None:
                preco = parse_preco(item.get("price"), regiao_cfg["currency_format"])
            if preco is None or preco <= 0:
                continue

            resultados_validos.append({
                "preco": float(preco),
                "loja": item.get("source", "Desconhecido"),
                "link": item.get("link", ""),
                "rating": item.get("rating"),
                "reviews": item.get("reviews", 0) or 0,
                "tag": str(item.get("extensions", "")).lower() + " " + str(item).lower(),
            })

        if resultados_validos:
            break  # Já temos resultados, não precisa fazer a 2ª query

        # Pequeno delay entre chamadas para evitar hammering
        time.sleep(0.3)

    return resultados_validos


def calcular_score_procura(itens):
    """Calcula um score de procura 0-100 baseado em vários sinais.
    - Nº de vendedores únicos: + concorrência = + procura
    - Soma de reviews: popularidade
    - Presença de tags 'sale', 'best seller', 'popular'
    - Dispersão de preços (CV): muito baixa = commodity saturada
    """
    if not itens:
        return 0, "Sem dados"

    n_vendedores = len({i["loja"] for i in itens})
    total_reviews = sum(int(i["reviews"]) if isinstance(i["reviews"], (int, float)) else 0 for i in itens)
    has_tags = any(any(t in i["tag"] for t in ["sale", "promo", "best seller", "popular", "oferta"]) for i in itens)

    score = 0
    # Vendedores: até 35 pontos
    score += min(n_vendedores * 5, 35)
    # Reviews: até 40 pontos (escala log-ish)
    if total_reviews > 0:
        score += min(int(np.log10(total_reviews + 1) * 15), 40)
    # Tags promocionais: até 10 pontos
    if has_tags:
        score += 10
    # Bonus se há ≥3 vendedores E ≥50 reviews
    if n_vendedores >= 3 and total_reviews >= 50:
        score += 15

    score = min(score, 100)

    if score >= 70:
        rotulo = "🔥 Muito Alta"
    elif score >= 45:
        rotulo = "📈 Alta"
    elif score >= 25:
        rotulo = "➡️ Média"
    else:
        rotulo = "📉 Baixa"
    return score, rotulo


def calcular_estrategias_preco(custo, imposto, markup, margem_minima, precos_concorrencia):
    """Devolve um dicionário com 4 estratégias de preço:
    - preco_minimo: chão (custo + imposto + margem mínima)
    - preco_competitivo: 2% abaixo do concorrente mais barato confiável
    - preco_otimo: ligeiramente abaixo do 2º mais barato (maximiza margem mantendo competitividade)
    - preco_mediana: mediana dos concorrentes (preço de mercado)
    """
    # Fórmula correcta: o imposto incide sobre a venda; o custo e o markup definem a meta
    # preco_alvo = custo * (1 + markup) / (1 - imposto)  -> garante margem desejada após imposto
    fator_imposto = 1 / (1 - imposto) if imposto < 1 else 1
    preco_minimo = round(custo * (1 + margem_minima) * fator_imposto, 2)
    preco_alvo = round(custo * (1 + markup) * fator_imposto, 2)

    if not precos_concorrencia:
        return {
            "preco_minimo": preco_minimo,
            "preco_competitivo": preco_alvo,
            "preco_otimo": preco_alvo,
            "preco_mediana": preco_alvo,
            "preco_alvo_markup": preco_alvo,
            "menor_concorrente": None,
            "mediana_mercado": None,
        }

    precos_ord = sorted(precos_concorrencia)
    menor = precos_ord[0]
    segundo = precos_ord[1] if len(precos_ord) >= 2 else menor
    mediana = statistics.median(precos_ord)

    preco_competitivo = max(round(menor * 0.98, 2), preco_minimo)
    preco_otimo = max(round(segundo * 0.98, 2), preco_minimo)
    preco_mediana = max(round(mediana, 2), preco_minimo)

    return {
        "preco_minimo": preco_minimo,
        "preco_competitivo": preco_competitivo,
        "preco_otimo": preco_otimo,
        "preco_mediana": preco_mediana,
        "preco_alvo_markup": preco_alvo,
        "menor_concorrente": menor,
        "mediana_mercado": mediana,
    }


def calcular_status(custo, imposto, markup, menor_concorrente):
    """Devolve emoji + rótulo:
    ✅ Vencendo: o concorrente mais barato ainda está acima do nosso alvo (lucro confortável)
    🟡 Risco: preço praticamente igual (diferença <5%)
    ⚠️ Caro: nosso alvo está acima do mercado, perdemos competitividade
    🟥 Burn: nem com markup zero conseguimos cobrir custo+imposto vs mercado
    """
    if menor_concorrente is None:
        return "❔ Sem dados", "sem_dados"

    fator_imposto = 1 / (1 - imposto) if imposto < 1 else 1
    preco_alvo = custo * (1 + markup) * fator_imposto
    custo_minimo = custo * fator_imposto  # mínimo para não dar prejuízo

    if menor_concorrente < custo_minimo:
        return "🟥 Burn", "burn"
    diff_pct = (preco_alvo - menor_concorrente) / menor_concorrente
    if diff_pct <= -0.05:
        return "✅ Vencendo", "vencendo"
    if abs(diff_pct) < 0.05:
        return "🟡 Risco", "risco"
    return "⚠️ Caro", "caro"


def recomendacao_investimento(status_codigo, score_procura, qtde_atual):
    """Devolve uma recomendação clara de investimento."""
    if status_codigo == "burn":
        return "❌ Não investir"
    if status_codigo == "sem_dados":
        return "❔ Sem dados de mercado"
    if score_procura >= 60 and status_codigo in ("vencendo", "risco"):
        return "🚀 Investir / Repor estoque"
    if score_procura >= 60 and status_codigo == "caro":
        return "⚖️ Renegociar fornecedor"
    if score_procura >= 30 and status_codigo == "vencendo":
        return "✅ Manter / Investir leve"
    if score_procura < 30:
        if qtde_atual > 0:
            return "🔻 Liquidar estoque"
        return "⏸️ Aguardar / Não comprar"
    return "🤔 Avaliar caso a caso"


def gerar_planilha_exemplo():
    """Gera um Excel de exemplo em memória para o utilizador descarregar."""
    exemplo = pd.DataFrame([
        {"EAN": "7891000100103", "Produto": "Headset Gamer HyperX Cloud II", "Categoria": "Periféricos", "Custo": 320.00, "Estoque": 12},
        {"EAN": "7898912345678", "Produto": "Cadeira Gamer DT3 Elise", "Categoria": "Móveis", "Custo": 850.00, "Estoque": 5},
        {"EAN": "7896543210987", "Produto": "Teclado Mecânico Logitech G Pro", "Categoria": "Periféricos", "Custo": 410.00, "Estoque": 8},
        {"EAN": "7891234567890", "Produto": "Monitor LG UltraGear 27\" 144Hz", "Categoria": "Monitores", "Custo": 1450.00, "Estoque": 3},
        {"EAN": "7890000111222", "Produto": "Mouse Razer DeathAdder V3", "Categoria": "Periféricos", "Custo": 280.00, "Estoque": 20},
        {"EAN": "7894561237894", "Produto": "Webcam Logitech C920 Full HD", "Categoria": "Periféricos", "Custo": 360.00, "Estoque": 7},
        {"EAN": "7898765432109", "Produto": "SSD Kingston NV2 1TB NVMe", "Categoria": "Armazenamento", "Custo": 380.00, "Estoque": 15},
        {"EAN": "7891111222233", "Produto": "Memória RAM Corsair Vengeance 16GB DDR4", "Categoria": "Memórias", "Custo": 220.00, "Estoque": 25},
        {"EAN": "7892222333344", "Produto": "Placa de Vídeo RTX 4060 8GB", "Categoria": "Hardware", "Custo": 1850.00, "Estoque": 4},
        {"EAN": "7893333444455", "Produto": "Fonte Corsair RM750e 80 Plus Gold", "Categoria": "Hardware", "Custo": 540.00, "Estoque": 6},
    ])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        exemplo.to_excel(writer, index=False, sheet_name="Produtos")
    buf.seek(0)
    return buf.getvalue()


def enviar_email_log(nome, email, mensagem):
    """Envia email de suporte. Corrigido: SMTP correto (smtp.gmail.com)."""
    try:
        origem = st.secrets["EMAIL_ORIGEM"]
        senha = st.secrets["SENHA_APP"].replace(" ", "")
        msg = MIMEMultipart()
        msg["From"] = origem
        msg["To"] = "contato@vembrincarcomagente.com"
        msg["Subject"] = f"[SUPORTE] - {nome}"
        msg.attach(MIMEText(f"Contato: {nome}\nEmail: {email}\n\nMsg: {mensagem}", "plain"))
        s = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        s.starttls()
        s.login(origem, senha)
        s.sendmail(origem, "contato@vembrincarcomagente.com", msg.as_string())
        s.quit()
        return True
    except Exception as e:
        return False


# =============================================================================
# 5. CONTROLE DE SESSÃO
# =============================================================================
for k, v in {
    "api_key": None,
    "df_final": None,
    "historico_global": pd.DataFrame(),
    "pais_anterior": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =============================================================================
# 6. SIDEBAR
# =============================================================================
with st.sidebar:
    st.header("🌎 Região")
    pais_sel = st.selectbox("Selecione:", list(idiomas.keys()), key="pais_main")

    if st.session_state.pais_anterior != pais_sel:
        st.session_state.df_final = None
        st.session_state.pais_anterior = pais_sel

    t = idiomas[pais_sel]

    st.divider()
    st.header("🔑 Chave API")
    api_key_input = st.text_input(t["label_chave"], type="password", value=st.session_state.api_key or "")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input.strip() or None
        if st.session_state.api_key:
            st.success("Chave ativada!")
        else:
            st.error("Chave vazia.")

    scope_pt = "Apenas Portugal"
    if "Portugal" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])

    st.divider()
    st.markdown("""
    <div style='font-size: 0.85rem;'>
    <b>Status</b><br>
    ✅ Vencendo &nbsp; 🟡 Risco<br>
    ⚠️ Caro &nbsp; 🟥 Burn<br><br>
    <b>Procura</b><br>
    🔥 Muito Alta &nbsp; 📈 Alta<br>
    ➡️ Média &nbsp; 📉 Baixa
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    st.header("✉️ Suporte")
    user_q = st.text_input("Dúvida rápida:")
    if user_q:
        with st.form("suporte_form", clear_on_submit=True):
            sn = st.text_input("Nome")
            se = st.text_input("Email")
            sm = st.text_area("Mensagem", value=user_q)
            if st.form_submit_button("Enviar"):
                if enviar_email_log(sn, se, sm):
                    st.success("✅ Enviado")
                else:
                    st.error("❌ Falha no envio")


# =============================================================================
# 7. CORPO PRINCIPAL
# =============================================================================
st.title(t["titulo"])

# Termos
st.subheader("📋 Termos de Uso")
aceite_regiao = st.checkbox(t["termos_check"], key=f"aceite_{pais_sel}")
if not aceite_regiao:
    st.warning("Aguardando aceite dos termos para continuar...")
    st.stop()

if not st.session_state.api_key:
    st.warning("⚠️ Insira a sua SerpApi Key na barra lateral para continuar.")
    st.stop()


# -----------------------------------------------------------------------------
# 7.1 Bloco de Carregamento
# -----------------------------------------------------------------------------
if st.session_state.df_final is None:
    st.header("📦 Carregamento de Produtos")

    # Botão para descarregar planilha de exemplo
    col_ex1, col_ex2 = st.columns([2, 1])
    with col_ex1:
        st.info("👉 Não tem ainda uma planilha? Descarregue o exemplo abaixo, preencha com os seus produtos e volte a carregar.")
    with col_ex2:
        st.download_button(
            "📥 Baixar planilha de exemplo",
            data=gerar_planilha_exemplo(),
            file_name="planilha_exemplo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    fonte = st.radio(
        "Fonte de dados:",
        ["Planilha", "Bling (API V3)"] if "Brasil" in pais_sel else ["Planilha"],
        horizontal=True,
    )
    df_base = pd.DataFrame()

    if "Bling" in fonte:
        token_bl = st.text_input("Token Bling V3:", type="password")
        if st.button("📥 Importar do Bling"):
            try:
                # Endpoint correcto da API Bling V3
                r = requests.get(
                    "https://api.bling.com.br/Api/v3/produtos",
                    headers={"Authorization": f"Bearer {token_bl}", "Accept": "application/json"},
                    timeout=30,
                )
                if r.status_code == 200:
                    dados = r.json().get("data", [])
                    df_base = pd.DataFrame([{
                        "Nome": i.get("nome", ""),
                        "Custo": round(float(i.get("precoCusto", 0) or 0), 2),
                        "Qtde": float(i.get("estoque", {}).get("quantidade", 1) or 1),
                        "EAN": i.get("codigoBarra", ""),
                        "Linha": (i.get("categoria") or {}).get("nome", "Geral"),
                        "ID": i.get("id", 0),
                    } for i in dados])
                    st.success(f"✅ {len(df_base)} produtos importados.")
                else:
                    st.error(f"Erro Bling {r.status_code}: {r.text[:200]}")
            except Exception as e:
                st.error(f"Erro ao chamar API Bling: {e}")
    else:
        uploaded_file = st.file_uploader(t["btn_excel"], type=["xlsx", "csv"])
        if uploaded_file:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df_raw = pd.read_csv(uploaded_file)
                else:
                    df_raw = pd.read_excel(uploaded_file)
            except Exception as e:
                st.error(f"Erro ao ler ficheiro: {e}")
                st.stop()

            cols = df_raw.columns.tolist()
            st.success(f"✅ Ficheiro lido com sucesso. {len(df_raw)} linhas, {len(cols)} colunas detectadas.")

            # Pré-visualização
            with st.expander("👀 Pré-visualizar dados carregados"):
                st.dataframe(df_raw.head(10))

            st.markdown("**🤖 Mapeamento automático das colunas (corrija se necessário):**")
            c1, c2, c3, c4, c5 = st.columns(5)

            idx_n = identificar_coluna(cols, ["produto", "nome", "item", "name", "descrição", "descricao"])
            idx_c = identificar_coluna(cols, ["custo", "compra", "cost", "preço de custo", "preco custo"])
            idx_q = identificar_coluna(cols, ["qtd", "quantidade", "stock", "estoque", "qty"])
            idx_l = identificar_coluna(cols, ["linha", "categoria", "category", "tipo", "departamento"])
            idx_e = identificar_coluna(cols, ["ean", "barra", "barras", "upc", "gtin", "código"])

            with c1:
                col_n = st.selectbox("PRODUTO:", cols, index=max(idx_n, 0))
            with c2:
                col_c = st.selectbox("CUSTO:", cols, index=max(idx_c, 0))
            with c3:
                col_q = st.selectbox("QTDE:", cols, index=max(idx_q, 0))
            with c4:
                opcoes_l = ["(Sem categoria)"] + cols
                col_l = st.selectbox("LINHA/CATEGORIA:", opcoes_l, index=(idx_l + 1) if idx_l >= 0 else 0)
            with c5:
                opcoes_e = ["(Sem EAN)"] + cols
                col_e = st.selectbox("EAN/CÓD. BARRAS:", opcoes_e, index=(idx_e + 1) if idx_e >= 0 else 0)

            df_base = df_raw.copy().rename(columns={col_n: "Nome", col_c: "Custo", col_q: "Qtde"})
            df_base["EAN"] = df_raw[col_e] if col_e != "(Sem EAN)" else ""
            df_base["Linha"] = df_raw[col_l] if col_l != "(Sem categoria)" else "Geral"
            df_base["ID"] = 0

            # Limpeza básica
            df_base["Custo"] = pd.to_numeric(df_base["Custo"], errors="coerce")
            df_base["Qtde"] = pd.to_numeric(df_base["Qtde"], errors="coerce").fillna(0)
            n_invalid = df_base["Custo"].isna().sum()
            df_base = df_base.dropna(subset=["Custo"])
            df_base = df_base[df_base["Custo"] > 0]
            if n_invalid > 0:
                st.warning(f"⚠️ {n_invalid} linhas removidas (custo inválido ou zero).")

    # ------ Parâmetros + execução ------
    if not df_base.empty:
        st.divider()
        st.header("⚙️ Parâmetros da Análise")
        ca1, ca2, ca3 = st.columns(3)
        with ca1:
            imposto = st.number_input("% Imposto sobre venda", 0.0, 90.0, 4.0, step=0.5) / 100
        with ca2:
            markup = st.number_input("% Markup desejado", 0.0, 500.0, 70.0, step=5.0) / 100
        with ca3:
            margem_minima = st.number_input("% Margem mínima (chão)", 0.0, 200.0, 15.0, step=5.0) / 100

        st.caption(
            "ℹ️ **Markup** é a margem que quer ganhar; **Margem mínima** é o chão abaixo do qual nunca vendemos. "
            "O imposto é descontado do preço de venda na hora de calcular o lucro real."
        )

        if st.button(t["btn_analisar"], type="primary"):
            # Determinar whitelist/blacklist da região
            if "Brasil" in pais_sel:
                whitelist = WHITELIST["BR"]
                blacklist = BLACKLIST_REGIONAL["BR"]
            elif "Portugal" in pais_sel:
                if scope_pt == "União Europeia":
                    whitelist = WHITELIST["EU"]
                    blacklist = BLACKLIST_REGIONAL["EU"]
                else:
                    whitelist = WHITELIST["PT_ONLY"]
                    blacklist = BLACKLIST_REGIONAL["PT_ONLY"]
            else:
                whitelist = WHITELIST["US"]
                blacklist = BLACKLIST_REGIONAL["US"]

            progress = st.progress(0.0, text="A analisar produtos...")
            log_box = st.empty()
            registros = []
            total = len(df_base)

            for idx, (_, row) in enumerate(df_base.iterrows()):
                progress.progress((idx + 1) / total, text=f"Analisando {idx + 1}/{total}: {row['Nome'][:50]}")
                itens = buscar_serpapi(
                    produto=row["Nome"],
                    ean=row.get("EAN", ""),
                    regiao_cfg=t,
                    whitelist=whitelist,
                    blacklist=blacklist,
                    api_key=st.session_state.api_key,
                )

                precos = [it["preco"] for it in itens]
                estrategias = calcular_estrategias_preco(
                    custo=row["Custo"],
                    imposto=imposto,
                    markup=markup,
                    margem_minima=margem_minima,
                    precos_concorrencia=precos,
                )
                score, rotulo_procura = calcular_score_procura(itens)
                status_label, status_codigo = calcular_status(
                    custo=row["Custo"], imposto=imposto, markup=markup,
                    menor_concorrente=estrategias["menor_concorrente"],
                )
                recomendacao = recomendacao_investimento(status_codigo, score, row["Qtde"])

                # Escolher preço sugerido baseado no status:
                # - Vencendo: usar preço óptimo (margem máxima)
                # - Risco/Caro: usar preço competitivo (undercut)
                # - Sem dados: usar preço alvo do markup
                if status_codigo == "vencendo":
                    preco_sugerido = estrategias["preco_otimo"]
                elif status_codigo in ("risco", "caro"):
                    preco_sugerido = estrategias["preco_competitivo"]
                elif status_codigo == "burn":
                    preco_sugerido = estrategias["preco_minimo"]
                else:
                    preco_sugerido = estrategias["preco_alvo_markup"]

                lucro_unitario = preco_sugerido * (1 - imposto) - row["Custo"]
                lucro_total = round(lucro_unitario * row["Qtde"], 2)
                margem_real = (lucro_unitario / preco_sugerido * 100) if preco_sugerido > 0 else 0

                loja_lider = itens[0]["loja"] if itens else "Sem dados"
                # Loja com o menor preço, na verdade
                if itens:
                    item_menor = min(itens, key=lambda x: x["preco"])
                    loja_lider = item_menor["loja"]

                registros.append({
                    "Nome": row["Nome"],
                    "Linha": row.get("Linha", "Geral"),
                    "EAN": str(row.get("EAN", "")),
                    "Qtde": row["Qtde"],
                    "Custo": row["Custo"],
                    "Menor Concorrente": estrategias["menor_concorrente"],
                    "Mediana Mercado": estrategias["mediana_mercado"],
                    "Loja Líder": loja_lider,
                    "N Concorrentes": len(itens),
                    "Preço Mínimo": estrategias["preco_minimo"],
                    "Preço Competitivo": estrategias["preco_competitivo"],
                    "Preço Óptimo": estrategias["preco_otimo"],
                    "Preço Mediana": estrategias["preco_mediana"],
                    "Preço Sugerido": preco_sugerido,
                    "Margem Real %": round(margem_real, 1),
                    "Lucro Unitário": round(lucro_unitario, 2),
                    "Lucro Total": lucro_total,
                    "Status": status_label,
                    "_status_code": status_codigo,
                    "Score Procura": score,
                    "Procura": rotulo_procura,
                    "Recomendação": recomendacao,
                })

            progress.empty()
            log_box.empty()
            st.session_state.df_final = pd.DataFrame(registros)
            st.session_state.df_final.attrs["imposto"] = imposto
            st.session_state.df_final.attrs["markup"] = markup
            st.rerun()


# -----------------------------------------------------------------------------
# 7.2 Exibição de Resultados
# -----------------------------------------------------------------------------
if st.session_state.df_final is not None:
    df = st.session_state.df_final.copy()
    moeda = t["moeda"]
    imposto_used = df.attrs.get("imposto", 0.04)

    st.divider()
    st.header("📊 Resultados da Análise")

    # ----- Filtros -----
    cf1, cf2, cf3 = st.columns(3)
    with cf1:
        sel_lojas = st.multiselect("🏪 Marketplaces:", options=sorted(df["Loja Líder"].dropna().unique()),
                                    default=sorted(df["Loja Líder"].dropna().unique()))
    with cf2:
        sel_linhas = st.multiselect("📦 Categorias:", options=sorted(df["Linha"].dropna().unique()),
                                     default=sorted(df["Linha"].dropna().unique()))
    with cf3:
        sel_status = st.multiselect("🚦 Status:", options=sorted(df["Status"].unique()),
                                     default=sorted(df["Status"].unique()))

    df_v = df[
        (df["Loja Líder"].isin(sel_lojas))
        & (df["Linha"].isin(sel_linhas))
        & (df["Status"].isin(sel_status))
    ]

    if df_v.empty:
        st.warning("Nenhum produto corresponde aos filtros.")
        st.stop()

    # ----- Métricas -----
    investimento = (df_v["Custo"] * df_v["Qtde"]).sum()
    lucro_proj = df_v["Lucro Total"].sum()
    roi = (lucro_proj / investimento * 100) if investimento > 0 else 0
    margem_media = df_v["Margem Real %"].mean()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💰 Investimento", f"{moeda} {investimento:,.2f}")
    m2.metric("📈 Lucro Projetado", f"{moeda} {lucro_proj:,.2f}")
    m3.metric("🎯 ROI", f"{roi:.1f}%")
    m4.metric("📐 Margem Média", f"{margem_media:.1f}%")

    # ----- Gráficos -----
    st.divider()
    st.subheader("📉 Análise Visual")

    grafico = st.selectbox("Tipo de gráfico:", [
        "1. Distribuição por Status",
        "2. Lucro por Marketplace",
        "3. Lucro por Categoria",
        "4. Procura vs Estoque",
        "5. Matriz Investimento (Margem × Procura)",
        "6. Top 10 Oportunidades de Lucro",
        "7. Posicionamento de Preço (Eu vs Mercado)",
        "8. Cobertura de Estoque vs Procura",
    ])

    color_map = {
        "✅ Vencendo": "#2ecc71", "🟡 Risco": "#f39c12",
        "⚠️ Caro": "#e67e22", "🟥 Burn": "#e74c3c", "❔ Sem dados": "#95a5a6",
    }

    if grafico.startswith("1"):
        fig = px.pie(df_v, names="Status", hole=0.45, color="Status",
                     color_discrete_map=color_map,
                     title="Como estão os preços face ao mercado")

    elif grafico.startswith("2"):
        agg = df_v.groupby("Loja Líder")["Lucro Total"].sum().reset_index().sort_values("Lucro Total", ascending=False)
        fig = px.bar(agg, x="Loja Líder", y="Lucro Total", color="Loja Líder",
                     title="Lucro projetado por marketplace líder")

    elif grafico.startswith("3"):
        fig = px.pie(df_v, names="Linha", values="Lucro Total", hole=0.45,
                     title="Lucro projetado por categoria")

    elif grafico.startswith("4"):
        fig = px.scatter(df_v, x="Score Procura", y="Qtde", size="Lucro Total",
                         color="Status", color_discrete_map=color_map,
                         hover_name="Nome", title="Procura de mercado vs Stock atual")
        fig.update_layout(xaxis_title="Score de Procura (0-100)", yaxis_title="Quantidade em Stock")

    elif grafico.startswith("5"):
        fig = px.scatter(df_v, x="Score Procura", y="Margem Real %",
                         size="Qtde", color="Status", color_discrete_map=color_map,
                         hover_name="Nome",
                         title="Onde investir: alta procura + alta margem = quadrante superior direito")
        fig.add_hline(y=20, line_dash="dot", line_color="grey", annotation_text="Margem 20%")
        fig.add_vline(x=45, line_dash="dot", line_color="grey", annotation_text="Procura média")

    elif grafico.startswith("6"):
        top = df_v.nlargest(10, "Lucro Total")
        fig = px.bar(top, x="Lucro Total", y="Nome", orientation="h",
                     color="Status", color_discrete_map=color_map,
                     title="Top 10 produtos por lucro projetado")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})

    elif grafico.startswith("7"):
        # Comparação meu preço sugerido vs menor concorrente vs mediana
        amostra = df_v.head(15) if len(df_v) > 15 else df_v
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Preço Sugerido", x=amostra["Nome"], y=amostra["Preço Sugerido"], marker_color="#3498db"))
        fig.add_trace(go.Bar(name="Menor Concorrente", x=amostra["Nome"], y=amostra["Menor Concorrente"], marker_color="#e74c3c"))
        fig.add_trace(go.Bar(name="Mediana Mercado", x=amostra["Nome"], y=amostra["Mediana Mercado"], marker_color="#95a5a6"))
        fig.update_layout(barmode="group", title="Posicionamento de preço (até 15 produtos)",
                          xaxis_tickangle=-45, height=550)

    else:  # 8
        fig = px.scatter(df_v, x="Score Procura", y="Qtde",
                         color="Recomendação", hover_name="Nome",
                         size="Custo", title="Cobertura de stock vs procura — onde reforçar/reduzir")

    st.plotly_chart(fig, use_container_width=True)

    # ----- Tabela de resultados -----
    st.divider()
    st.subheader("📋 Tabela Detalhada")

    colunas_show = [
        "Nome", "Linha", "Qtde", "Custo", "Menor Concorrente", "Mediana Mercado",
        "Loja Líder", "N Concorrentes", "Preço Mínimo", "Preço Competitivo",
        "Preço Óptimo", "Preço Sugerido", "Margem Real %", "Lucro Total",
        "Status", "Procura", "Recomendação",
    ]
    st.dataframe(df_v[colunas_show], use_container_width=True, hide_index=True)

    # ----- Download dos resultados -----
    cd1, cd2 = st.columns(2)
    with cd1:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_v[colunas_show].to_excel(writer, index=False, sheet_name="Análise")
        st.download_button("📥 Baixar análise em Excel", data=buf.getvalue(),
                           file_name="analise_precos.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with cd2:
        if st.button("🗑️ Limpar análise e começar nova"):
            st.session_state.df_final = None
            st.rerun()


Refactor: bugs corrigidos + estratégias de preço + score de procura
