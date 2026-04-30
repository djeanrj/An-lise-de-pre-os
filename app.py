# -*- coding: utf-8 -*-
"""
IA Marketplace Global v2 — Análise de Preços e Concorrência
Novidades v2:
- Integração Supabase (histórico de análises + histórico de preços de mercado)
- Lógica de "loja própria" (vembrincarcomagente.com / .com.br)
- Aba "Histórico" com tendência de preço por produto e ranking
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
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, quote_plus

# Supabase é opcional — se não estiver configurado, a app continua a funcionar sem histórico
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


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
WHITELIST = {
    "BR": [
        "mercadolivre.com.br", "amazon.com.br", "magazineluiza.com.br", "magalu",
        "americanas.com.br", "submarino.com.br", "shoptime.com.br",
        "casasbahia.com.br", "pontofrio.com.br", "carrefour.com.br",
        "extra.com.br", "fastshop.com.br", "kabum.com.br", "girafa.com.br",
        "shopee.com.br", "ricardoeletro.com.br", "centauro.com.br",
        "netshoes.com.br", "dafiti.com.br", "leroymerlin.com.br",
        "ribrinquedos.com.br", "rihappy.com.br", "mpbrinquedos.com.br",
        "lojaodosbrinquedos.com", "bumerangbrinquedos.com.br",
    ],
    "PT_ONLY": [
        "worten.pt", "fnac.pt", "elcorteingles.pt", "pcdiga.com",
        "auchan.pt", "continente.pt", "radiopopular.pt", "mediamarkt.pt",
        "pixmania.pt", "kuantokusta.pt", "toysrus.pt", "globaldata.pt",
        "phonehouse.pt", "rdgshop.pt", "chip7.pt", "bebebrinquedo.pt",
    ],
    "EU": [
        "worten.pt", "fnac.pt", "elcorteingles.pt", "pcdiga.com", "mediamarkt.pt",
        "kuantokusta.pt", "phonehouse.pt", "radiopopular.pt", "auchan.pt",
        "bebebrinquedo.pt",
        "amazon.es", "elcorteingles.es", "pccomponentes.com", "fnac.es",
        "mediamarkt.es", "carrefour.es",
        "amazon.de", "mediamarkt.de", "otto.de", "saturn.de", "notebooksbilliger.de",
        "amazon.it", "mediaworld.it", "unieuro.it", "kidinn.com", "vendiloshop.com",
        "amazon.fr", "fnac.com", "darty.com", "cdiscount.com",
        "bol.com", "amazon.nl", "coolblue.nl",
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
    # Loja própria: não deve contar como concorrente
    "vembrincarcomagente.com", "vembrincarcomagente.com.br",
]

BLACKLIST_REGIONAL = {
    "BR": BLACKLIST_GLOBAL + ["ebay.com", "kidinn.com", "tradeinn.com", "vendiloshop"],
    "PT_ONLY": BLACKLIST_GLOBAL + ["ebay", "kidinn.com", "tradeinn.com", "vendiloshop"],
    "EU": BLACKLIST_GLOBAL + ["ebay"],
    "US": BLACKLIST_GLOBAL,
}

# Palavras-chave que indicam produto usado, incompleto ou peça avulsa.
# Qualquer match faz o resultado ser rejeitado.
KEYWORDS_NAO_NOVO = [
    # PT-BR
    "usado", "seminovo", "semi-novo", "semi novo", "peças", "pecas",
    "incompleto", "avulso", "avulsa", "sem caixa", "sem manual", "recondicionado",
    "outlet", "vitrine", "mostruário", "mostruario", "danificado",
    # PT-PT
    "em segunda mão", "segunda mao", "como novo", "reembalado",
    # EN
    "used", "pre-owned", "preowned", "open box", "open-box", "openbox",
    "refurbished", "loose", "no box", "incomplete", "missing pieces",
    "missing parts", "bricklink", "spare", "replacement parts",
    # IT
    "usato", "ricondizionato",
    # DE
    "gebraucht", "generalüberholt",
    # FR / ES
    "occasion", "reacondicionado", "segunda mano",
]


def parece_produto_novo(item):
    """Devolve False se houver indícios de produto usado/incompleto/avulso."""
    blob = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("extensions", "")),
        str(item.get("source", "")),
    ]).lower()
    for kw in KEYWORDS_NAO_NOVO:
        if kw in blob:
            return False
    return True


# =============================================================================
# 4. CLIENTE SUPABASE (lazy-loaded e cacheado)
# =============================================================================
@st.cache_resource
def get_supabase_client():
    """Devolve o cliente Supabase ou None se não estiver configurado."""
    if not SUPABASE_AVAILABLE:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except (KeyError, FileNotFoundError):
        return None
    except Exception as e:
        st.warning(f"Falha ao conectar ao Supabase: {e}")
        return None


def supabase_ativo():
    return get_supabase_client() is not None


def gravar_historico_supabase(df_resultado, regiao, scope, imposto, markup, margem_minima):
    """Grava a análise + snapshot de preços no Supabase. Devolve analise_id ou None."""
    sb = get_supabase_client()
    if sb is None:
        return None

    investimento = float((df_resultado["Custo"] * df_resultado["Qtde"]).sum())
    lucro = float(df_resultado["Lucro Total"].sum())

    try:
        analise_resp = sb.table("analises").insert({
            "regiao": regiao,
            "scope": scope,
            "imposto": float(imposto),
            "markup": float(markup),
            "margem_minima": float(margem_minima),
            "total_produtos": int(len(df_resultado)),
            "investimento": investimento,
            "lucro_projetado": lucro,
        }).execute()
        analise_id = analise_resp.data[0]["id"]
    except Exception as e:
        st.warning(f"Erro ao gravar análise no Supabase: {e}")
        return None

    # Bulk insert do histórico de preços
    registos = []
    for _, row in df_resultado.iterrows():
        def _f(col):
            """Float seguro: devolve None se coluna ausente ou valor inválido."""
            v = row.get(col)
            return float(v) if v is not None and pd.notna(v) else None

        def _s(col, default=""):
            v = row.get(col)
            return str(v) if v is not None and pd.notna(v) else default

        def _i(col, default=0):
            v = row.get(col)
            return int(v) if v is not None and pd.notna(v) else default

        registos.append({
            "analise_id": analise_id,
            "ean": _s("EAN"),
            "sku": _s("SKU"),
            "nome": _s("Nome"),
            "regiao": regiao,
            "custo": _f("Custo"),
            "menor_concorrente": _f("Menor Concorrente"),
            "mediana_mercado": _f("_mediana_mercado"),
            "loja_lider": _s("_loja_lider"),
            "n_concorrentes": _i("N Concorrentes"),
            "score_procura": _i("Score Procura"),
            "status": _s("Status"),
            "preco_sugerido": _f("Preço Sugerido"),
            "recomendacao": _s("Recomendação"),
        })

    try:
        # Inserir em chunks de 100 para evitar timeout em catálogos grandes
        for i in range(0, len(registos), 100):
            sb.table("historico_precos").insert(registos[i:i+100]).execute()
        return analise_id
    except Exception as e:
        st.warning(f"Erro ao gravar histórico de preços no Supabase: {e}")
        return analise_id  # Análise foi gravada, mesmo que histórico falhe


@st.cache_data(ttl=60)  # Cache de 1 minuto para não martelar a BD
def carregar_analises_recentes(limite=50):
    """Lista as últimas análises feitas."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    try:
        resp = sb.table("analises").select("*").order("criado_em", desc=True).limit(limite).execute()
        return pd.DataFrame(resp.data)
    except Exception as e:
        st.warning(f"Erro ao ler análises: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_historico_produto(ean, sku, nome, regiao, dias=180):
    """Devolve histórico de preços de um produto.
    Estratégia: filtra por EAN (mais preciso) > SKU (universal do fabricante) > nome (fallback)."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    try:
        data_limite = (datetime.utcnow() - timedelta(days=dias)).isoformat()
        query = sb.table("historico_precos").select("*").eq("regiao", regiao).gte("criado_em", data_limite)
        if ean and str(ean).strip():
            query = query.eq("ean", str(ean).strip())
        elif sku and str(sku).strip():
            query = query.eq("sku", str(sku).strip())
        else:
            query = query.eq("nome", nome)
        resp = query.order("criado_em", desc=False).execute()
        return pd.DataFrame(resp.data)
    except Exception as e:
        st.warning(f"Erro ao ler histórico do produto: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def ranking_produtos_analisados(regiao, dias=90):
    """Top produtos mais analisados na região, com últimos preços."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    try:
        data_limite = (datetime.utcnow() - timedelta(days=dias)).isoformat()
        resp = sb.table("historico_precos").select("nome, ean, sku, menor_concorrente, score_procura, status, criado_em").eq("regiao", regiao).gte("criado_em", data_limite).execute()
        df = pd.DataFrame(resp.data)
        if df.empty:
            return df
        agg = df.groupby(["nome", "ean", "sku"], dropna=False).agg(
            n_analises=("criado_em", "count"),
            ultimo_preco=("menor_concorrente", "last"),
            score_medio=("score_procura", "mean"),
            ultimo_status=("status", "last"),
        ).reset_index().sort_values("n_analises", ascending=False)
        return agg
    except Exception as e:
        st.warning(f"Erro ao calcular ranking: {e}")
        return pd.DataFrame()


# =============================================================================
# 5. FUNÇÕES UTILITÁRIAS
# =============================================================================
def identificar_coluna(lista_cols, chaves, default=-1):
    """Encontra a coluna mais provável com base numa lista de palavras-chave (ordem = prioridade).
    1) Match exato com a chave inteira; 2) Match por substring respeitando a ordem das chaves."""
    lista_lower = [str(c).lower().strip() for c in lista_cols]
    # Match exato
    for chave in chaves:
        for i, c in enumerate(lista_lower):
            if c == chave:
                return i
    # Match por substring, respeitando a prioridade da lista de chaves
    for chave in chaves:
        for i, c in enumerate(lista_lower):
            if chave in c:
                return i
    return default


def limpar_custo(serie):
    """Aceita custo como número ou como texto formatado em pt-BR/pt-PT (R$ 1.234,56 / 1.234,56 €).
    Devolve uma Series numérica."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    # Texto: remover tudo o que não é dígito, vírgula, ponto ou sinal
    s = serie.astype(str).str.replace(r"[^\d,.\-]", "", regex=True)
    # Heurística: se tem vírgula, assumir formato BR/EU (ponto = milhar, vírgula = decimal)
    tem_virgula = s.str.contains(",", na=False).any()
    if tem_virgula:
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_preco(valor_raw, formato="BR"):
    if valor_raw is None:
        return None
    if isinstance(valor_raw, (int, float)):
        return float(valor_raw) if valor_raw > 0 else None
    s = str(valor_raw).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if not s:
        return None
    try:
        if formato in ("BR", "EU"):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        return float(s) if float(s) > 0 else None
    except ValueError:
        return None


def vendedor_confiavel(item, whitelist, blacklist):
    """True se o item é de um vendedor confiável da região (whitelist) e não está na blacklist."""
    fonte = str(item.get("source", "")).lower()
    link = str(item.get("link", "")).lower()
    try:
        dominio = urlparse(link).netloc.lower()
    except Exception:
        dominio = ""

    blob = f"{fonte} {link} {dominio}"

    # Blacklist sobrepõe whitelist (inclui já a loja própria, que não conta como concorrente)
    for b in blacklist:
        if b.lower() in blob:
            return False

    if whitelist:
        return any(w.lower() in blob for w in whitelist)
    return True


def buscar_serpapi(produto, ean, sku, custo, regiao_cfg, whitelist, blacklist, api_key,
                    apenas_novos=True, preco_minimo_pct_custo=0.40):
    """Devolve concorrentes confiáveis + log de rejeitados.
    Estratégia em cascata: EAN > SKU+marca > Nome.
    Filtros aplicados:
    - Vendedor confiável da região (whitelist) e fora da blacklist
    - Produto novo (rejeita 'usado', 'open box', 'peças avulsas', etc.) se apenas_novos=True
    - Outlier de preço: rejeita preço abaixo de `preco_minimo_pct_custo` × custo
      (default 40%: se compraste a R$ 100, ignora resultados abaixo de R$ 40)"""
    concorrentes = []
    rejeitados_log = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0}
    consultas = []

    def _valido(v):
        return v is not None and str(v).strip() and str(v).strip().lower() != "nan"

    if _valido(ean):
        consultas.append(str(ean).strip())
    if _valido(sku) and (not _valido(ean) or str(sku).strip() != str(ean).strip()):
        primeira_palavra = str(produto).split("-")[0].strip().split()[0] if produto else ""
        if primeira_palavra and primeira_palavra.lower() != str(sku).strip().lower():
            consultas.append(f"{sku} {primeira_palavra}")
        else:
            consultas.append(str(sku).strip())
    consultas.append(f"{produto}")

    # Limites de outlier baseados no custo
    preco_min_aceitavel = custo * preco_minimo_pct_custo if custo else 0
    preco_max_aceitavel = custo * 10 if custo else float("inf")

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

            if apenas_novos and not parece_produto_novo(item):
                rejeitados_log["usado"] += 1
                continue

            preco = item.get("extracted_price")
            if preco is None:
                preco = parse_preco(item.get("price"), regiao_cfg["currency_format"])
            if preco is None or preco <= 0:
                continue

            if custo:
                if preco < preco_min_aceitavel:
                    rejeitados_log["outlier_baixo"] += 1
                    continue
                if preco > preco_max_aceitavel:
                    rejeitados_log["outlier_alto"] += 1
                    continue

            concorrentes.append({
                "preco": float(preco),
                "loja": item.get("source", "Desconhecido"),
                "link": item.get("link") or item.get("product_link") or "",
                "rating": item.get("rating"),
                "reviews": item.get("reviews", 0) or 0,
                "tag": str(item.get("extensions", "")).lower() + " " + str(item).lower(),
            })

        if concorrentes:
            break

        time.sleep(0.3)

    return concorrentes, rejeitados_log


def calcular_score_procura(itens):
    if not itens:
        return 0, "Sem dados"
    n_vendedores = len({i["loja"] for i in itens})
    total_reviews = sum(int(i["reviews"]) if isinstance(i["reviews"], (int, float)) else 0 for i in itens)
    has_tags = any(any(t in i["tag"] for t in ["sale", "promo", "best seller", "popular", "oferta"]) for i in itens)

    score = 0
    score += min(n_vendedores * 5, 35)
    if total_reviews > 0:
        score += min(int(np.log10(total_reviews + 1) * 15), 40)
    if has_tags:
        score += 10
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
    fator_imposto = 1 / (1 - imposto) if imposto < 1 else 1
    preco_minimo = round(custo * (1 + margem_minima) * fator_imposto, 2)
    preco_alvo = round(custo * (1 + markup) * fator_imposto, 2)

    if not precos_concorrencia:
        return {
            "preco_minimo": preco_minimo,
            "preco_competitivo": preco_alvo,
            "preco_otimo": preco_alvo,
            "preco_mercado": preco_alvo,
            "preco_alvo_markup": preco_alvo,
            "menor_concorrente": None,
            "mercado_competitivo": None,
            "mediana_mercado": None,
        }

    precos_ord = sorted(precos_concorrencia)
    menor = precos_ord[0]
    segundo = precos_ord[1] if len(precos_ord) >= 2 else menor
    mediana = statistics.median(precos_ord)

    # Mercado Competitivo = média dos top 3 mais baratos (ou todos se houver < 3)
    # Representa o "cluster de concorrentes que o cliente vai realmente comparar"
    top_n = min(3, len(precos_ord))
    mercado_competitivo = round(sum(precos_ord[:top_n]) / top_n, 2)

    preco_competitivo = max(round(menor * 0.98, 2), preco_minimo)
    preco_otimo = max(round(segundo * 0.98, 2), preco_minimo)
    preco_mercado = max(round(mercado_competitivo, 2), preco_minimo)

    return {
        "preco_minimo": preco_minimo,
        "preco_competitivo": preco_competitivo,
        "preco_otimo": preco_otimo,
        "preco_mercado": preco_mercado,
        "preco_alvo_markup": preco_alvo,
        "menor_concorrente": menor,
        "mercado_competitivo": mercado_competitivo,
        "mediana_mercado": mediana,  # mantida internamente para o histórico Supabase
    }


def calcular_status(custo, imposto, markup, menor_concorrente):
    if menor_concorrente is None:
        return "❔ Sem dados", "sem_dados"
    fator_imposto = 1 / (1 - imposto) if imposto < 1 else 1
    preco_alvo = custo * (1 + markup) * fator_imposto
    custo_minimo = custo * fator_imposto
    if menor_concorrente < custo_minimo:
        return "🟥 Burn", "burn"
    diff_pct = (preco_alvo - menor_concorrente) / menor_concorrente
    if diff_pct <= -0.05:
        return "✅ Vencendo", "vencendo"
    if abs(diff_pct) < 0.05:
        return "🟡 Risco", "risco"
    return "⚠️ Caro", "caro"


def recomendacao_investimento(status_codigo, score_procura, qtde_atual):
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
    exemplo = pd.DataFrame([
        {"SKU": "10281", "EAN": "5702016667967", "Produto": "LEGO Icons Bonsai", "Categoria": "Lego Icons", "Custo": 256.83, "Estoque": 2},
        {"SKU": "10280", "EAN": "5702016912388", "Produto": "LEGO Icons Buquê de Flores", "Categoria": "Lego Icons", "Custo": 308.19, "Estoque": 1},
        {"SKU": "31151", "EAN": "5702017415925", "Produto": "LEGO Creator T. rex", "Categoria": "Lego Creator", "Custo": 288.59, "Estoque": 1},
        {"SKU": "75392", "EAN": "5702017592664", "Produto": "LEGO Star Wars Construtor de Droid", "Categoria": "Star Wars", "Custo": 494.73, "Estoque": 1},
        {"SKU": "60408", "EAN": "5702017583266", "Produto": "LEGO City Caminhão-cegonha com Carros Esportivos", "Categoria": "Lego City", "Custo": 494.73, "Estoque": 1},
        {"SKU": "21357", "EAN": "5702017583815", "Produto": "LEGO Ideias Disney Pixar Luxo Jr.", "Categoria": "Ideias", "Custo": 364.58, "Estoque": 1},
        {"SKU": "31201", "EAN": "5702017153957", "Produto": "LEGO Art Harry Potter Hogwarts Brasões", "Categoria": "Art", "Custo": 655.73, "Estoque": 1},
        {"SKU": "76295", "EAN": "5702017583617", "Produto": "LEGO Marvel O Helicarrier dos Vingadores", "Categoria": "Super Heroes", "Custo": 412.27, "Estoque": 2},
        {"SKU": "75389", "EAN": "5702017462066", "Produto": "LEGO Star Wars A Dark Falcon", "Categoria": "Star Wars", "Custo": 927.63, "Estoque": 1},
        {"SKU": "10989", "EAN": "5702017384207", "Produto": "LEGO Duplo Parque Aquático", "Categoria": "DUPLO", "Custo": 208.33, "Estoque": 2},
    ])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        exemplo.to_excel(writer, index=False, sheet_name="Produtos")
    buf.seek(0)
    return buf.getvalue()


def enviar_email_log(nome, email, mensagem):
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
    except Exception:
        return False


# =============================================================================
# 6. CONTROLE DE SESSÃO
# =============================================================================
for k, v in {
    "api_key": None,
    "df_final": None,
    "historico_global": pd.DataFrame(),
    "pais_anterior": None,
    "ultima_analise_id": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v


# =============================================================================
# 7. SIDEBAR
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
    # Status do Supabase
    if supabase_ativo():
        st.success("📚 Histórico ativo (Supabase)")
    else:
        st.info("📚 Histórico desativado\n(configure SUPABASE_URL/KEY)")

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
# 8. CORPO PRINCIPAL — ABAS
# =============================================================================
st.title(t["titulo"])

st.subheader("📋 Termos de Uso")
aceite_regiao = st.checkbox(t["termos_check"], key=f"aceite_{pais_sel}")
if not aceite_regiao:
    st.warning("Aguardando aceite dos termos para continuar...")
    st.stop()

if not st.session_state.api_key:
    st.warning("⚠️ Insira a sua SerpApi Key na barra lateral para continuar.")
    st.stop()


tab_analise, tab_historico = st.tabs(["🎯 Nova Análise", "📜 Histórico"])


# =============================================================================
# 8.1 TAB: NOVA ANÁLISE
# =============================================================================
with tab_analise:
    if st.session_state.df_final is None:
        st.header("📦 Carregamento de Produtos")

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
                            "SKU": i.get("codigo", ""),
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

                with st.expander("👀 Pré-visualizar dados carregados"):
                    st.dataframe(df_raw.head(10))

                st.markdown("**🤖 Mapeamento automático das colunas (corrija se necessário):**")
                c1, c2, c3, c4, c5, c6 = st.columns(6)

                idx_n = identificar_coluna(cols, ["nome produto", "descrição", "descricao", "produto", "nome", "item", "name"])
                idx_c = identificar_coluna(cols, ["preço de custo", "preco custo", "custo", "compra", "cost"])
                idx_q = identificar_coluna(cols, ["quantidade", "estoque", "stock", "qtd", "qty"])
                idx_l = identificar_coluna(cols, ["linha", "categoria", "category", "tipo", "departamento"])
                idx_e = identificar_coluna(cols, ["código de barras", "codigo de barras", "ean", "gtin", "upc", "barras", "barra"])
                idx_s = identificar_coluna(cols, ["sku", "código produto", "codigo produto", "ref", "referência", "referencia", "model", "modelo", "código", "codigo"])

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
                with c6:
                    opcoes_s = ["(Sem SKU)"] + cols
                    col_s = st.selectbox("SKU/REF:", opcoes_s, index=(idx_s + 1) if idx_s >= 0 else 0)

                st.caption(
                    "💡 **SKU/REF** é o código do fabricante (ex: LEGO `10281`, Playmobil `70980`). "
                    "Quando preenchido, melhora muito a precisão da busca em mercados estrangeiros, "
                    "porque o nome muda entre idiomas mas o SKU é universal."
                )

                df_base = df_raw.copy().rename(columns={col_n: "Nome", col_c: "Custo", col_q: "Qtde"})
                df_base["EAN"] = df_raw[col_e] if col_e != "(Sem EAN)" else ""
                df_base["SKU"] = df_raw[col_s].astype(str) if col_s != "(Sem SKU)" else ""
                df_base["Linha"] = df_raw[col_l] if col_l != "(Sem categoria)" else "Geral"
                df_base["ID"] = 0

                df_base["Custo"] = limpar_custo(df_base["Custo"])
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

            with st.expander("🎛️ Filtros avançados de qualidade"):
                cf_a, cf_b = st.columns(2)
                with cf_a:
                    apenas_novos = st.checkbox(
                        "Aceitar apenas produtos NOVOS",
                        value=True,
                        help="Rejeita resultados marcados como usado, seminovo, open box, peças avulsas, "
                             "incompleto, recondicionado, etc. Recomendado manter ativado.",
                    )
                with cf_b:
                    preco_min_pct = st.slider(
                        "Filtro de outlier de preço (% do custo)",
                        min_value=10, max_value=80, value=40, step=5,
                        help="Rejeita resultados cujo preço seja inferior a esta percentagem do seu custo de aquisição. "
                             "Default 40%: se compra a R$ 100, ignora resultados abaixo de R$ 40 (provavelmente são "
                             "peças avulsas, fraude, ou erro de scraping).",
                    ) / 100

            if st.button(t["btn_analisar"], type="primary"):
                if "Brasil" in pais_sel:
                    whitelist = WHITELIST["BR"]
                    blacklist = BLACKLIST_REGIONAL["BR"]
                    regiao_id = "BR"
                elif "Portugal" in pais_sel:
                    if scope_pt == "União Europeia":
                        whitelist = WHITELIST["EU"]
                        blacklist = BLACKLIST_REGIONAL["EU"]
                        regiao_id = "EU"
                    else:
                        whitelist = WHITELIST["PT_ONLY"]
                        blacklist = BLACKLIST_REGIONAL["PT_ONLY"]
                        regiao_id = "PT"
                else:
                    whitelist = WHITELIST["US"]
                    blacklist = BLACKLIST_REGIONAL["US"]
                    regiao_id = "US"

                progress = st.progress(0.0, text="A analisar produtos...")
                registos = []
                total = len(df_base)
                rejeitados_total = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0}

                for idx, (_, row) in enumerate(df_base.iterrows()):
                    progress.progress((idx + 1) / total, text=f"Analisando {idx + 1}/{total}: {row['Nome'][:50]}")
                    concorrentes, rej = buscar_serpapi(
                        produto=row["Nome"],
                        ean=row.get("EAN", ""),
                        sku=row.get("SKU", ""),
                        custo=row["Custo"],
                        regiao_cfg=t,
                        whitelist=whitelist,
                        blacklist=blacklist,
                        api_key=st.session_state.api_key,
                        apenas_novos=apenas_novos,
                        preco_minimo_pct_custo=preco_min_pct,
                    )
                    for k, v in rej.items():
                        rejeitados_total[k] += v

                    precos_conc = [it["preco"] for it in concorrentes]
                    estrategias = calcular_estrategias_preco(
                        custo=row["Custo"], imposto=imposto, markup=markup,
                        margem_minima=margem_minima, precos_concorrencia=precos_conc,
                    )
                    score, rotulo_procura = calcular_score_procura(concorrentes)
                    status_label, status_codigo = calcular_status(
                        custo=row["Custo"], imposto=imposto, markup=markup,
                        menor_concorrente=estrategias["menor_concorrente"],
                    )
                    recomendacao = recomendacao_investimento(status_codigo, score, row["Qtde"])

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

                    concorrentes_ordenados = sorted(concorrentes, key=lambda x: x["preco"]) if concorrentes else []
                    loja_lider = concorrentes_ordenados[0]["loja"] if concorrentes_ordenados else "Sem dados"

                    diff_vs_mercado = None
                    if estrategias["mercado_competitivo"] and preco_sugerido:
                        diff_vs_mercado = round(
                            (preco_sugerido - estrategias["mercado_competitivo"]) / estrategias["mercado_competitivo"] * 100, 1
                        )

                    registos.append({
                        "Nome": row["Nome"],
                        "Linha": row.get("Linha", "Geral"),
                        "EAN": str(row.get("EAN", "")),
                        "SKU": str(row.get("SKU", "")),
                        "Qtde": row["Qtde"],
                        "Custo": row["Custo"],
                        "Preço Markup": estrategias["preco_alvo_markup"],
                        "Menor Concorrente": estrategias["menor_concorrente"],
                        "Mercado Competitivo": estrategias["mercado_competitivo"],
                        "Diff vs Mercado %": diff_vs_mercado,
                        "_concorrentes": concorrentes_ordenados,
                        "N Concorrentes": len(concorrentes),
                        "Preço Mínimo": estrategias["preco_minimo"],
                        "Preço Competitivo": estrategias["preco_competitivo"],
                        "Preço Óptimo": estrategias["preco_otimo"],
                        "Preço Mercado": estrategias["preco_mercado"],
                        "Preço Sugerido": preco_sugerido,
                        "Margem Real %": round(margem_real, 1),
                        "Lucro Unitário": round(lucro_unitario, 2),
                        "Lucro Total": lucro_total,
                        "Status": status_label,
                        "_status_code": status_codigo,
                        "Score Procura": score,
                        "Procura": rotulo_procura,
                        "Recomendação": recomendacao,
                        "_loja_lider": loja_lider,
                        "_mediana_mercado": estrategias["mediana_mercado"],
                    })

                progress.empty()
                df_resultado = pd.DataFrame(registos)
                st.session_state.df_final = df_resultado
                st.session_state.df_final.attrs["imposto"] = imposto
                st.session_state.df_final.attrs["markup"] = markup
                st.session_state.df_final.attrs["margem_minima"] = margem_minima
                st.session_state.df_final.attrs["regiao"] = regiao_id
                st.session_state.df_final.attrs["rejeitados"] = rejeitados_total

                # Resumo dos filtros aplicados
                if any(rejeitados_total.values()):
                    msgs = []
                    if rejeitados_total["usado"]:
                        msgs.append(f"🧹 {rejeitados_total['usado']} resultados rejeitados (produto não novo)")
                    if rejeitados_total["outlier_baixo"]:
                        msgs.append(f"📉 {rejeitados_total['outlier_baixo']} preços rejeitados (muito baixos — peças/avulsos)")
                    if rejeitados_total["outlier_alto"]:
                        msgs.append(f"📈 {rejeitados_total['outlier_alto']} preços rejeitados (outliers altos)")
                    st.info(" · ".join(msgs))

                # Gravar histórico no Supabase
                if supabase_ativo():
                    analise_id = gravar_historico_supabase(
                        df_resultado, regiao_id, scope_pt if "Portugal" in pais_sel else None,
                        imposto, markup, margem_minima,
                    )
                    if analise_id:
                        st.session_state.ultima_analise_id = analise_id
                        st.toast(f"✅ Análise #{analise_id} gravada no histórico", icon="📚")
                        # Limpar caches de leitura para que o novo histórico apareça
                        carregar_analises_recentes.clear()
                        ranking_produtos_analisados.clear()

                st.rerun()

    # ----- Exibição de Resultados (após corrida) -----
    if st.session_state.df_final is not None:
        df = st.session_state.df_final.copy()
        moeda = t["moeda"]
        imposto_used = df.attrs.get("imposto", 0.04)

        st.divider()
        st.header("📊 Resultados da Análise")

        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            sel_lojas = st.multiselect("🏪 Marketplace líder (🥇):",
                                        options=sorted(df["_loja_lider"].dropna().unique()),
                                        default=sorted(df["_loja_lider"].dropna().unique()))
        with cf2:
            sel_linhas = st.multiselect("📦 Categorias:",
                                         options=sorted(df["Linha"].dropna().unique()),
                                         default=sorted(df["Linha"].dropna().unique()))
        with cf3:
            sel_status = st.multiselect("🚦 Status:",
                                         options=sorted(df["Status"].unique()),
                                         default=sorted(df["Status"].unique()))

        df_v = df[
            (df["_loja_lider"].isin(sel_lojas))
            & (df["Linha"].isin(sel_linhas))
            & (df["Status"].isin(sel_status))
        ]

        if df_v.empty:
            st.warning("Nenhum produto corresponde aos filtros.")
            st.stop()

        investimento = (df_v["Custo"] * df_v["Qtde"]).sum()
        lucro_proj = df_v["Lucro Total"].sum()
        roi = (lucro_proj / investimento * 100) if investimento > 0 else 0
        margem_media = df_v["Margem Real %"].mean()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("💰 Investimento", f"{moeda} {investimento:,.2f}")
        m2.metric("📈 Lucro Projetado", f"{moeda} {lucro_proj:,.2f}")
        m3.metric("🎯 ROI", f"{roi:.1f}%")
        m4.metric("📐 Margem Média", f"{margem_media:.1f}%")

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
            agg = df_v.groupby("_loja_lider")["Lucro Total"].sum().reset_index().sort_values("Lucro Total", ascending=False)
            agg = agg.rename(columns={"_loja_lider": "Loja Líder"})
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
            amostra = df_v.head(15) if len(df_v) > 15 else df_v
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Preço Sugerido", x=amostra["Nome"], y=amostra["Preço Sugerido"], marker_color="#3498db"))
            fig.add_trace(go.Bar(name="Menor Concorrente", x=amostra["Nome"], y=amostra["Menor Concorrente"], marker_color="#e74c3c"))
            fig.add_trace(go.Bar(name="Mercado Competitivo (top 3)", x=amostra["Nome"], y=amostra["Mercado Competitivo"], marker_color="#95a5a6"))
            fig.update_layout(barmode="group", title="Posicionamento de preço (até 15 produtos)",
                              xaxis_tickangle=-45, height=550)
        else:
            fig = px.scatter(df_v, x="Score Procura", y="Qtde",
                             color="Recomendação", hover_name="Nome",
                             size="Custo", title="Cobertura de stock vs procura")

        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("📋 Tabela Detalhada")

        colunas_show = [
            "Nome", "Linha", "Qtde",
            "Custo", "Preço Markup",
            "Menor Concorrente", "Mercado Competitivo", "Diff vs Mercado %",
            "Preço Sugerido", "Margem Real %", "Lucro Total",
            "Status", "Procura", "Recomendação",
            "N Concorrentes",
        ]

        st.dataframe(
            df_v[colunas_show],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Custo": st.column_config.NumberColumn(format=f"{moeda} %.2f"),
                "Preço Markup": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço calculado pela sua margem (markup) configurada, "
                         "ignorando o mercado. Fórmula: custo × (1 + markup) / (1 - imposto). "
                         "Compare com o Preço Sugerido para ver se o mercado o obriga a baixar.",
                ),
                "Menor Concorrente": st.column_config.NumberColumn(format=f"{moeda} %.2f"),
                "Mercado Competitivo": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Média dos 3 concorrentes mais baratos confiáveis",
                ),
                "Diff vs Mercado %": st.column_config.NumberColumn(
                    "Δ vs Mercado", format="%+.1f %%",
                    help="Diferença do Preço Sugerido face ao Mercado Competitivo",
                ),
                "Preço Sugerido": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="O que o algoritmo recomenda face ao mercado e ao status",
                ),
                "Margem Real %": st.column_config.NumberColumn(format="%.1f %%"),
                "Lucro Total": st.column_config.NumberColumn(format=f"{moeda} %.2f"),
            },
        )

        # ---------- PAINEL DE VERIFICAÇÃO ----------
        st.divider()
        st.subheader("🔍 Painel de Verificação de Concorrentes")
        st.caption(
            "Escolha um produto para inspecionar todos os concorrentes confiáveis encontrados, "
            "com nome comercial completo, preço, avaliação e link para o anúncio."
        )

        produto_inspect = st.selectbox(
            "Produto a inspecionar:",
            options=df_v["Nome"].tolist(),
            key="produto_inspect",
        )

        if produto_inspect:
            linha_inspect = df_v[df_v["Nome"] == produto_inspect].iloc[0]
            concorrentes_lista = linha_inspect.get("_concorrentes", []) or []

            # Cabeçalho de contexto
            ci1, ci2, ci3, ci4 = st.columns(4)
            ci1.metric("Custo", f"{moeda} {linha_inspect['Custo']:,.2f}")
            ci2.metric("Preço Markup", f"{moeda} {linha_inspect['Preço Markup']:,.2f}")
            ci3.metric("Preço Sugerido", f"{moeda} {linha_inspect['Preço Sugerido']:,.2f}")
            ci4.metric("Concorrentes encontrados", len(concorrentes_lista))

            if not concorrentes_lista:
                st.info("Sem concorrentes confiáveis encontrados para este produto.")
            else:
                # Construir tabela de concorrentes; se link vier vazio, fallback para
                # busca no Google Shopping com nome da loja + nome do produto
                def _link_ou_fallback(c, nome_produto):
                    link_real = c.get("link") or ""
                    if link_real:
                        return link_real
                    loja = c.get("loja", "")
                    query = f'"{nome_produto}" "{loja}"' if loja else nome_produto
                    return f"https://www.google.com/search?tbm=shop&q={quote_plus(query)}"

                df_conc = pd.DataFrame([
                    {
                        "Posição": f"#{i+1}",
                        "Loja": c["loja"],
                        "Preço": c["preco"],
                        "Rating": c.get("rating"),
                        "Reviews": c.get("reviews", 0),
                        "Link": _link_ou_fallback(c, produto_inspect),
                        "Link directo?": "✅" if c.get("link") else "🔍 busca",
                    }
                    for i, c in enumerate(concorrentes_lista)
                ])

                st.dataframe(
                    df_conc,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Preço": st.column_config.NumberColumn(format=f"{moeda} %.2f"),
                        "Rating": st.column_config.NumberColumn(format="⭐ %.1f"),
                        "Reviews": st.column_config.NumberColumn(format="%d"),
                        "Link": st.column_config.LinkColumn(
                            "🔗 Anúncio",
                            display_text="abrir",
                            help="Abre o anúncio. Se a SerpAPI não devolveu link directo "
                                 "(comum para Amazon Buy Box), abre uma busca no Google Shopping "
                                 "com o produto e a loja.",
                        ),
                        "Link directo?": st.column_config.TextColumn(
                            "Tipo",
                            help="✅ = link directo do anúncio; 🔍 busca = não havia link, "
                                 "abre uma busca no Google Shopping com produto+loja",
                        ),
                    },
                )

                if len(concorrentes_lista) <= 2:
                    st.warning(
                        f"⚠️ Apenas {len(concorrentes_lista)} concorrente(s) encontrado(s). "
                        "Poucos resultados podem indicar produto pouco distribuído ou que os filtros "
                        "rejeitaram resultados (consulte o resumo no topo da análise)."
                    )

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


# =============================================================================
# 8.2 TAB: HISTÓRICO
# =============================================================================
with tab_historico:
    st.header("📜 Histórico de Análises e Tendências")

    if not supabase_ativo():
        st.warning(
            "🔌 **Histórico desativado.**\n\n"
            "Para ativar, configure as variáveis `SUPABASE_URL` e `SUPABASE_KEY` "
            "nos Secrets do Streamlit Cloud, e instale `supabase` no `requirements.txt`."
        )
        st.stop()

    # ----- Determinar a região para filtrar -----
    if "Brasil" in pais_sel:
        regiao_id = "BR"
    elif "Portugal" in pais_sel:
        regiao_id = "EU" if scope_pt == "União Europeia" else "PT"
    else:
        regiao_id = "US"

    st.caption(f"A mostrar dados da região: **{regiao_id}**")

    # ----- Análises recentes -----
    st.subheader("🗓️ Últimas análises")
    df_analises = carregar_analises_recentes(limite=20)
    if df_analises.empty:
        st.info("Ainda não há análises gravadas. Corra uma análise no separador ao lado para começar.")
    else:
        df_show = df_analises[df_analises["regiao"] == regiao_id].copy() if "regiao" in df_analises.columns else df_analises.copy()
        if df_show.empty:
            st.info(f"Sem análises gravadas para a região {regiao_id} ainda.")
        else:
            df_show["criado_em"] = pd.to_datetime(df_show["criado_em"]).dt.strftime("%d/%m/%Y %H:%M")
            st.dataframe(
                df_show[["id", "criado_em", "total_produtos", "investimento", "lucro_projetado", "imposto", "markup"]]
                .rename(columns={
                    "id": "ID", "criado_em": "Quando", "total_produtos": "Produtos",
                    "investimento": "Investimento", "lucro_projetado": "Lucro Projetado",
                    "imposto": "Imposto", "markup": "Markup",
                }),
                use_container_width=True, hide_index=True,
            )

    st.divider()

    # ----- Ranking de produtos -----
    st.subheader("🏆 Produtos mais analisados (últimos 90 dias)")
    df_rank = ranking_produtos_analisados(regiao_id, dias=90)
    if df_rank.empty:
        st.info("Sem dados suficientes para gerar ranking.")
    else:
        df_rank_show = df_rank.head(20).copy()
        df_rank_show["score_medio"] = df_rank_show["score_medio"].round(0)
        st.dataframe(
            df_rank_show.rename(columns={
                "nome": "Produto", "ean": "EAN", "n_analises": "Nº Análises",
                "ultimo_preco": "Último Menor Preço", "score_medio": "Score Procura Médio",
                "ultimo_status": "Último Status",
            }),
            use_container_width=True, hide_index=True,
        )

    st.divider()

    # ----- Tendência de preço por produto -----
    st.subheader("📈 Tendência de preço por produto")
    if df_rank.empty:
        st.caption("Ainda não há histórico suficiente para mostrar tendências.")
    else:
        opcoes_produtos = df_rank["nome"].head(50).tolist()
        produto_sel = st.selectbox("Escolha um produto:", opcoes_produtos)
        linha_sel = df_rank[df_rank["nome"] == produto_sel].iloc[0]
        ean_sel = linha_sel["ean"]
        sku_sel = linha_sel["sku"] if "sku" in linha_sel.index else ""
        dias_sel = st.slider("Janela de tempo (dias):", 7, 365, 90)

        df_tend = carregar_historico_produto(ean_sel, sku_sel, produto_sel, regiao_id, dias=dias_sel)
        if df_tend.empty or len(df_tend) < 2:
            st.info("São necessárias pelo menos 2 análises do mesmo produto para mostrar tendência. Continue a correr análises ao longo do tempo.")
        else:
            df_tend["criado_em"] = pd.to_datetime(df_tend["criado_em"])
            fig_tend = go.Figure()
            fig_tend.add_trace(go.Scatter(x=df_tend["criado_em"], y=df_tend["menor_concorrente"],
                                            name="Menor Concorrente", mode="lines+markers",
                                            line=dict(color="#e74c3c")))
            fig_tend.add_trace(go.Scatter(x=df_tend["criado_em"], y=df_tend["mediana_mercado"],
                                            name="Mediana Mercado", mode="lines+markers",
                                            line=dict(color="#95a5a6", dash="dash")))
            fig_tend.add_trace(go.Scatter(x=df_tend["criado_em"], y=df_tend["preco_sugerido"],
                                            name="Meu Preço Sugerido", mode="lines+markers",
                                            line=dict(color="#3498db")))
            fig_tend.update_layout(
                title=f"Evolução de preço — {produto_sel[:60]}",
                xaxis_title="Data", yaxis_title=f"Preço ({t['moeda']})",
                hovermode="x unified", height=450,
            )
            st.plotly_chart(fig_tend, use_container_width=True)

            # Variação face à 1ª análise
            primeira = df_tend.iloc[0]
            ultima = df_tend.iloc[-1]
            if primeira["menor_concorrente"] and ultima["menor_concorrente"]:
                var = (ultima["menor_concorrente"] - primeira["menor_concorrente"]) / primeira["menor_concorrente"] * 100
                seta = "📈" if var > 1 else ("📉" if var < -1 else "➡️")
                st.metric(
                    f"{seta} Variação do menor concorrente desde {primeira['criado_em'].strftime('%d/%m')}",
                    f"{var:+.1f}%",
                )
