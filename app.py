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
import os
import smtplib
import statistics
from datetime import datetime, timedelta, timezone
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, quote_plus

# Supabase é opcional — se não estiver configurado, a app continua a funcionar sem histórico
try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


import os

# =============================================================================
# 1. CONFIGURAÇÃO DA INTERFACE
# =============================================================================
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")


# ─── SESSÃO PERSISTENTE VIA URL STATE (?sid=) ────────────────────────────────
# Como cookies de terceiros não funcionam em iframes (limitação do browser para
# HF Spaces), usamos um identificador opaco na URL para identificar a sessão.
# O `sid` é a chave de um registo na tabela `user_sessions` do Supabase que
# guarda os tokens. URL fica: https://...hf.space/?sid=abc123xyz...

def _gerar_sid():
    """Gera um identificador de sessão aleatório criptograficamente seguro."""
    import secrets as _s
    return "sess_" + _s.token_urlsafe(24)


def _criar_sessao_persistente(user_session_dados, dias_validade=7):
    """Guarda a sessão no Supabase e devolve o `sid` correspondente."""
    sb = get_supabase_client()
    if sb is None:
        return None
    try:
        from datetime import datetime, timedelta, timezone
        sid = _gerar_sid()
        expira = datetime.now(timezone.utc) + timedelta(days=dias_validade)
        user = user_session_dados.get("user") or {}
        sb.table("user_sessions").insert({
            "sid": sid,
            "user_id": user.get("id", ""),
            "user_email": user.get("email", ""),
            "user_name": user.get("name", ""),
            "user_avatar": user.get("avatar", ""),
            "access_token": user_session_dados.get("access_token", ""),
            "refresh_token": user_session_dados.get("refresh_token", ""),
            "expira_em": expira.isoformat(),
        }).execute()
        return sid
    except Exception as e:
        st.session_state["_sid_save_error"] = f"{type(e).__name__}: {e}"
        return None


def _restaurar_sessao_de_sid():
    """Se a URL tem ?sid=..., procura no Supabase e restaura user_session.
    Devolve True se restaurou, False senão."""
    if st.session_state.get("user_session"):
        return True
    qs = st.query_params
    sid = qs.get("sid")
    if not sid:
        return False
    sb = get_supabase_client()
    if sb is None:
        return False
    try:
        from datetime import datetime, timezone
        resp = sb.table("user_sessions").select("*").eq("sid", sid).limit(1).execute()
        rows = resp.data or []
        if not rows:
            try:
                del st.query_params["sid"]
            except Exception:
                pass
            return False
        row = rows[0]
        try:
            expira = datetime.fromisoformat(row["expira_em"].replace("Z", "+00:00"))
            if expira < datetime.now(timezone.utc):
                sb.table("user_sessions").delete().eq("sid", sid).execute()
                try:
                    del st.query_params["sid"]
                except Exception:
                    pass
                return False
        except Exception:
            pass
        st.session_state["user_session"] = {
            "access_token": row.get("access_token", ""),
            "refresh_token": row.get("refresh_token", ""),
            "user": {
                "id": row.get("user_id", ""),
                "email": row.get("user_email", ""),
                "name": row.get("user_name", ""),
                "avatar": row.get("user_avatar", ""),
            },
        }
        return True
    except Exception:
        return False


def _apagar_sessao_persistente():
    """Apaga o registo da sessão persistente no Supabase (chamado no logout)."""
    qs = st.query_params
    sid = qs.get("sid")
    if not sid:
        return
    sb = get_supabase_client()
    if sb is None:
        return
    try:
        sb.table("user_sessions").delete().eq("sid", sid).execute()
    except Exception:
        pass


# ─── PREFERÊNCIAS PERSISTENTES POR UTILIZADOR ────────────────────────────────
# Guardadas em user_preferences (Supabase) para sobreviverem a navegações
# (ex: depois de autorizar Bling, a chave SerpAPI e termos aceites mantêm-se).

def _carregar_preferencias_user():
    """Lê preferências do utilizador actual. Devolve dict (vazio se nada existe)."""
    sb = get_supabase_client()
    if sb is None:
        return {}
    uid = user_id_actual()
    if not uid:
        return {}
    try:
        r = sb.table("user_preferences").select("*").eq("user_id", uid).limit(1).execute()
        return r.data[0] if r.data else {}
    except Exception:
        return {}


def _guardar_preferencia(campo, valor):
    """Persiste uma preferência específica (upsert)."""
    sb = get_supabase_client()
    if sb is None:
        return
    uid = user_id_actual()
    if not uid:
        return
    try:
        sb.table("user_preferences").upsert({
            "user_id": uid,
            campo: valor,
            "actualizado_em": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id").execute()
    except Exception:
        pass


# Handler do redirect OAuth do Bling — só executa se houver utilizador autenticado.
# Quando o utilizador autoriza no Bling, este redireciona para a app com `?code=...&state=...`
# Como a sessão Streamlit pode reiniciar entre clique e callback, não validamos o `state`
# contra session_state — basta `code`+`state` na URL e ausência do nosso `pkce_v`
# (que é exclusivo do callback Google).
def _handle_bling_oauth_callback():
    qs = st.query_params
    # Bling devolve code+state. Distinguir de Google: Google nosso tem pkce_v.
    if "code" in qs and "state" in qs and "pkce_v" not in qs:
        # O state Bling tem formato "<sid>|<random>" — extrair sid e restaurar
        # sessão Google (que pode ter sido perdida pela navegação para o Bling).
        state = qs.get("state", "")
        if "|" in state:
            sid_do_state, _ = state.split("|", 1)
            if sid_do_state and not utilizador_autenticado():
                # Injectar ?sid= na URL e restaurar sessão antes de continuar
                st.query_params["sid"] = sid_do_state
                _restaurar_sessao_de_sid()

        if not utilizador_autenticado():
            return
        codigo = qs["code"]
        ok, msg = bling_trocar_codigo_por_tokens(codigo)
        # Preservar sid mas limpar code/state
        sid_actual = st.query_params.get("sid")
        st.query_params.clear()
        if sid_actual:
            st.query_params["sid"] = sid_actual
        if ok:
            st.success(f"✅ {msg}")
        else:
            st.error(f"❌ {msg}")


# A chamada destes handlers acontece mais abaixo no ficheiro,
# depois de todas as funções estarem definidas.


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
    "USA 🇺🇸 (experimental)": {
        "id": "US", "moeda": "$", "lang": "en", "domain": "google.com",
        "gl": "us", "loc": "United States", "currency_format": "US",
        "titulo": "USA Marketplace Intelligence (experimental)",
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
        # Lojas LEGO + brinquedos PT confirmadas
        "lego.com", "universoencantado.com", "colorbricks.pt",
        "cubosluminosos.pt", "capytoys.pt", "papelariaencantada.pt",
        "babykids.pt", "imaginarium.pt", "minilatas.pt",
        # Generalistas com presença confiável em PT
        "amazon.es", "el corte inglés", "elcorteingles.es",
    ],
    "EU": [
        # === PORTUGAL (todas as PT_ONLY + mais que aparecem em busca) ===
        "worten.pt", "fnac.pt", "elcorteingles.pt", "pcdiga.com", "mediamarkt.pt",
        "kuantokusta.pt", "phonehouse.pt", "radiopopular.pt", "auchan.pt",
        "continente.pt", "bebebrinquedo.pt", "toysrus.pt", "chip7.pt",
        # Lojas LEGO + brinquedos PT confirmadas
        "lego.com", "universoencantado.com", "colorbricks.pt",
        "cubosluminosos.pt", "capytoys.pt", "papelariaencantada.pt",
        "babykids.pt", "imaginarium.pt", "minilatas.pt",
        # === ESPANHA ===
        "amazon.es", "elcorteingles.es", "pccomponentes.com", "fnac.es",
        "mediamarkt.es", "carrefour.es", "el corte inglés",
        # === ALEMANHA ===
        "amazon.de", "mediamarkt.de", "otto.de", "saturn.de", "notebooksbilliger.de",
        # === ITÁLIA ===
        "amazon.it", "mediaworld.it", "unieuro.it",
        # === FRANÇA ===
        "amazon.fr", "fnac.com", "darty.com", "cdiscount.com",
        # === HOLANDA ===
        "bol.com", "amazon.nl", "coolblue.nl",
    ],
    "US": [
        "amazon.com", "ebay.com", "walmart.com", "target.com", "bestbuy.com",
        "newegg.com", "bhphotovideo.com", "homedepot.com", "lowes.com",
        "costco.com", "macys.com", "nordstrom.com", "kohls.com", "wayfair.com",
        "samsclub.com", "staples.com", "officedepot.com",
    ],
}

BLACKLIST_GLOBAL = [
    # Plataformas dropshipping/internacionais (sempre rejeitar em qualquer região)
    "aliexpress.com", "temu.com", "wish.com", "tiendamia", "fishpond",
    "grandado", "fruugo", "desertcart", "ubuy", "joom", "banggood",
    "etsy.com",  # quase sempre vasos/acessórios LEGO, não LEGO original
    # Marketplaces de produtos usados em massa
    "wallapop", "vinted", "olx",
    # Lojas de brindes corporativos / roupa profissional (não fiável para retalho)
    "lojadosbrindes",
    # Loja própria: não deve contar como concorrente
    "vembrincarcomagente.com", "vembrincarcomagente.com.br",
    # NOTA: eBay NÃO está na global porque em US é um marketplace legítimo para retalho novo.
    # Está na blacklist de BR/EU (mercados onde eBay é majoritariamente cross-border + frete caro).
]

BLACKLIST_REGIONAL = {
    "BR": BLACKLIST_GLOBAL + ["ebay", "kidinn.com", "tradeinn.com", "vendiloshop", "you get"],
    "PT_ONLY": BLACKLIST_GLOBAL + ["ebay", "kidinn.com", "tradeinn.com", "vendiloshop", "you get"],
    "EU": BLACKLIST_GLOBAL + ["ebay", "kidinn.com", "tradeinn.com", "vendiloshop", "you get"],
    "US": BLACKLIST_GLOBAL + [
        # Lojas estrangeiras com frete internacional caro / impostos extras
        # (lojas "estilo X" / acessórios LEGO não estão aqui — coerente_com_tipo()
        # filtra por tipo do produto procurado; se procuras acessório, são bem-vindas).
        "turkish souq", "kidinn", "tradeinn", "vendiloshop", "snkrdunk",
        "desertcart", "ubuy", "fruugo",
    ],
}

# Palavras-chave que indicam produto usado, incompleto ou peça avulsa.
# Qualquer match faz o resultado ser rejeitado.
KEYWORDS_NAO_NOVO = [
    # PT-BR
    "usado", "seminovo", "semi-novo", "semi novo",
    "incompleto", "avulso", "avulsa", "sem caixa", "sem manual", "recondicionado",
    "outlet", "vitrine", "mostruário", "mostruario", "danificado",
    # ATENÇÃO: "peças" / "pecas" foi REMOVIDO da lista porque títulos em PT-BR
    # usam "X peças" para descrever o número de peças do set (ex: "474 Peças").
    # Para captar venda de peças avulsas, usar padrões específicos abaixo:
    "peças avulsas", "pecas avulsas", "peças soltas", "pecas soltas",
    "vendido em peças", "vendido em pecas", "venda de peças", "venda de pecas",
    "lote de peças", "lote de pecas", "kit de peças", "kit de pecas",
    "só peças", "so pecas", "apenas peças", "apenas pecas",
    # PT-PT
    "em segunda mão", "segunda mao", "como novo", "reembalado",
    # EN
    "used", "pre-owned", "preowned", "previously owned", "previously-owned",
    "like new", "like-new", "nearly new",  # Mercari/eBay common phrasing for used
    "good condition", "fair condition",  # eBay condition tags
    "open box", "open-box", "openbox",
    "damaged box", "damaged-box", "damaged packaging",
    "refurbished", "loose", "no box", "incomplete", "missing pieces",
    "missing parts", "bricklink", "spare", "replacement parts",
    # Clones / não-originais
    "3rd party", "3rd-party", "third party", "third-party", "non-oem",
    "non oem", "knockoff", "knock-off", "replica", "fake",
    # Saquetas individuais (vendido só uma parte do set, não o set completo)
    "bag #", "bag no.", "bag no ", "bag 1 of", "bag 2 of", "bag 3 of", "bag 4 of",
    "bag 5 of", "bag #1", "bag #2", "bag #3", "bag #4", "bag #5",
    "bags 1 &", "bags 2 &", "bags 3 &", "bags 4 &", "bags 5 &",  # "Bags 4 & 5 Only"
    "bag 4 & 5", "bag 1 & 2", "bag 2 & 3", "bag 3 & 4",
    "& 5 only", "& 4 only", "& 3 only",  # "Bags 4 & 5 Only Sealed"
    "sealed bag", "sealed no.", "sealed no ", "sealed no#",
    "soil element sealed", "element sealed",  # "Soil Element Sealed Bag"
    "from set", "from lego set", "single bag", "individual bag",
    "polybag from", "parts from set", "pieces from set",
    "manual only", "instructions only", "box only", "no bricks",
    "no bricks or parts", "instruction manual only", "box and instructions",
    "outer box only", "box & instructions", "set lot",  # "Lego Used Botanical Collection Set Lot"
    # IT
    "usato", "ricondizionato",
    # DE
    "gebraucht", "generalüberholt",
    # FR / ES
    "occasion", "reacondicionado", "segunda mano",
]

# Palavras-chave que indicam um produto que NÃO É o original mas sim um acessório,
# kit complementar ou produto compatível. Estes não devem ser usados para comparar
# preços com o produto LEGO original.
KEYWORDS_ACESSORIO_OU_COMPATIVEL = [
    # PT-BR
    "kit de luzes", "kit de luz", "kit de iluminação", "kit de iluminacao",
    "kit luminoso", "luzes led", "iluminação led", "iluminacao led",
    "compatível com lego", "compativel com lego", "compatível com o lego", "compativel com o lego",
    "compatível para lego", "compativel para lego",
    "alternativa ao lego", "tipo lego", "estilo lego",
    "expositor para lego", "expositor lego", "acrílico para lego", "vitrine para lego",
    "moldura para lego", "suporte para lego", "base para lego", "case para lego",
    "estojo para lego", "organizador para lego",
    "adesivo para lego", "decalque", "decals",
    # Acessórios para consolas/electrónica (cases, carregadores, etc.)
    "capa para", "case para", "carregador para", "estojo para",
    "protetor de tela", "película", "pelicula", "screen protector",
    # PT-PT (variações)
    "compatível com o", "para o",
    # EN — LEGO/brinquedos
    "light kit", "led light kit", "lighting kit", "led kit",
    "compatible with lego", "compatible with the lego",
    "for lego", "fits lego", "designed for lego",
    "display case for lego", "display for lego", "shelf for lego",
    "stand for lego", "frame for lego",
    "display case", "wall display", "premium display",  # genéricos
    "display-case", "display-frame", "wall-display",  # slugs URL
    "acrylic display", "acrylic-display",  # display acrílico
    "elevenmark",  # domínio Mark's Magic Store (só vende displays)
    "lf-displays", "lfdisplaysolu",  # vendedores Etsy de displays para LEGO
    "kingdombricksupply", "brickshellcases", "brickcessories",  # display brands
    "shoppopdisplays", "wezhape", "icuanuty", "hox3d", "prodocase",  # mais display brands
    "wickedbrick",  # Wicked Brick (displays)
    # MOC = "My Own Creation" — builds não oficiais (clones / instruções alternativas)
    "moc-", "moc compatible", "moc compativel", "moc kompatibel",
    "compatible moc", "build alternativo", "alternative build",
    "moc instructions", "instruction moc",
    "sticker for lego", "decal for lego", "decals for",
    # EN — Acessórios genéricos para consolas/electrónica
    # (carrying case, protective case, charging case, etc — quando é um anexo, não o produto)
    "carrying case", "carry case", "protective case",
    "charging case", "charging dock", "charging stand", "screen protector",
    "crossbody bag", "travel case", "storage case", "hard case",
    "soft case", "shell case", "case for nintendo", "case for playstation",
    "case for xbox", "case for switch", "skin for", "wrap for",
    "snapback hat", "snapback cap", "trucker hat", "cap for", "hat for",
    "stand for nintendo", "stand for playstation", "dock for",
    "wall mount for", "mount for",
    # Variantes sem espaço (slugs URL)
    "fancycase", "shellcase", "softcase", "hardcase", "traveler-deluxe",
    "carrycase", "carryingcase", "protectivecase", "screenprotector",
    "crossbodybag", "travelcase", "storagecase",
    # Outros tipos de produto (não acessórios mas também não o produto procurado)
    # Detectados via slugs de URL
    "game-traveler", "system-case", "deluxe-system",
    "switch-dock", "switch-console", "switch-lite", "switch-oled",
    "joy-con-set", "joy-con-strap",
    "previously-owned", "previously_owned", "refurbished",
    # FR / ES / DE / IT (genérico)
    "compatible avec lego", "compatible con lego", "compatibile con lego",
    "kompatibel mit lego",
    "éclairage pour lego", "iluminación para lego", "illuminazione per lego",
    "beleuchtung für lego",
]


def detectar_tipo_produto(nome_produto):
    """Detecta se o produto procurado é o produto PRINCIPAL ou um ACESSÓRIO/PEÇA.

    Devolve uma das strings:
    - "acessorio"  → kits luz, vasos, displays, cases, "para X", "compatível com X"
    - "peca_avulsa"→ minifiguras, instruções, polybags, "manual only", "box only"
    - "principal"  → produto principal (default — quando nenhum indicador detectado)

    Esta classificação é depois usada para FILTRAR resultados:
    se procuro acessório, rejeito produto principal e vice-versa.
    Princípio: o produto procurado define o que esperamos encontrar.
    """
    if not nome_produto:
        return "principal"

    nome = str(nome_produto).lower()

    # Acessório: indicadores claros no nome procurado
    keywords_acessorio = [
        # Iluminação / luzes
        "kit luz", "kit de luz", "luz led", "iluminação", "iluminacao", "iluminação led",
        "light kit", "led light", "led kit", "lighting kit",
        # Displays / cases / suportes
        "case para", "display case", "expositor", "vitrine", "stand para", "stand for",
        "suporte para", "support for", "wall mount", "mount for", "presentation case",
        "skin", "skins", "decal", "sticker para",
        # Acessório explícito
        "acessório para", "acessorio para", "accessory for", "compatible with",
        "compativel com", "compatível com",
        # Vasos / decoração para o produto principal
        "vaso para", "vase for", "vaso decorativo",
        # "Para LEGO X" / "for LEGO X" — claramente acessório
        " para lego ", " for lego ",
    ]
    for kw in keywords_acessorio:
        if kw in nome:
            return "acessorio"

    # Peça avulsa: minifigura sozinha, manual, polybag, peças soltas
    # Usar regex \b para bater "minifigure" tanto em "LEGO Minifigure" como "Minifigure pack"
    keywords_peca_regex = [
        r"\bminifigura\b", r"\bminifigure\b", r"\bminifig\b",
        r"\binstructions only\b", r"\bmanual only\b",
        r"\bpolybag\b", r"\bspare parts\b", r"\breplacement parts\b",
        r"\bindividual part\b",
        r"\bbox only\b", r"\bcaixa apenas\b", r"\binstruções apenas\b", r"\binstrucoes apenas\b",
    ]
    for kw_re in keywords_peca_regex:
        if re.search(kw_re, nome):
            return "peca_avulsa"

    return "principal"


def parece_acessorio_compativel(item):
    """Devolve True se o título indicar um acessório/produto compatível (não o LEGO oficial).
    Usado para evitar comparar preço do LEGO original com luzes LED, expositores, etc.

    ⚠️ Uso condicional: só faz sentido aplicar este filtro quando o produto PROCURADO
    é o principal. Se o utilizador procura um acessório, este filtro está errado.
    A coerência é validada via `coerente_com_tipo()`.
    """
    blob = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
    ]).lower()
    for kw in KEYWORDS_ACESSORIO_OU_COMPATIVEL:
        if kw in blob:
            return True
    return False


def coerente_com_tipo(item, tipo_procurado):
    """Verifica se o resultado é coerente com o tipo de produto procurado.

    Regra: o resultado tem de ser do MESMO tipo que o produto procurado.
    - Procuro principal → rejeito acessórios e peças avulsas
    - Procuro acessório → rejeito produto principal (não interessa para o que procuro)
    - Procuro peça avulsa → rejeito set completo e acessórios

    Esta abordagem torna a app universal sem manter blacklist de "lojas de acessórios".
    Light My Bricks, BrickBling, etc. podem ser concorrentes legítimos para quem
    vende acessórios. Aqui rejeitamos só se houver mismatch de tipo.

    Olha o `title`, `snippet` E `link` — porque algumas vezes a SerpAPI dá título
    genérico mas o link revela o tipo (ex: walmart.com/.../protective-case-for-...).
    """
    if not tipo_procurado:
        tipo_procurado = "principal"

    blob = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("link", "")),  # link revela tipo via URL
    ]).lower()

    # Detectar se o RESULTADO é acessório
    resultado_e_acessorio = False
    for kw in KEYWORDS_ACESSORIO_OU_COMPATIVEL:
        if kw in blob:
            resultado_e_acessorio = True
            break

    # Detectar se o RESULTADO é peça avulsa
    resultado_e_peca = False
    keywords_peca_resultado = [
        "minifigure ", "minifig ", "instructions only", "manual only",
        "polybag", "spare parts", "replacement parts", "individual part",
        "box only", "no bricks or parts", "instruction manual only",
        "bag #", "sealed bag", "from set",
    ]
    for kw in keywords_peca_resultado:
        if kw in blob:
            resultado_e_peca = True
            break

    # Aplicar regra de coerência
    if tipo_procurado == "principal":
        # Procuro produto principal → rejeito acessórios e peças
        return not (resultado_e_acessorio or resultado_e_peca)
    elif tipo_procurado == "acessorio":
        # Procuro acessório → quero acessório, rejeito principal e peças
        return resultado_e_acessorio
    elif tipo_procurado == "peca_avulsa":
        # Procuro peça → quero peça
        return resultado_e_peca

    return True  # fallback


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


# Palavras-chave que indicam compra internacional / importação directa
# (custo final muito maior que o anunciado por causa de taxas/frete internacional)
# Palavras-chave que indicam compra internacional / importação directa
# (custo final muito maior que o anunciado por causa de taxas/frete internacional)
KEYWORDS_COMPRA_INTERNACIONAL = [
    # Português Brasil — termos exactos usados na Amazon.com.br
    "compra internacional",
    "compras internacionais",
    "produto internacional",
    "produtos internacionais",
    "importação direta",
    "importacao direta",
    "produto importado",
    "envio internacional",
    "frete internacional",
    "envio do exterior",
    "vendido pela amazon.com",
    "vendido por amazon.com",
    "imposto de importação",
    "imposto de importacao",
    "imposto incluído",
    "imposto incluido",
    "impostos inclusos",
    "impostos incluídos",
    "impostos incluidos",
    "de estados unidos",
    "dos estados unidos",
    "da china",
    "import. direta",
    "import direta",
    "vem do exterior",
    "do exterior",
    "ships to brazil",
    "envia para o brasil",
    "envia ao brasil",
    "vendedor internacional",
    "vendedores internacionais",
    "global store",
    "amazon global",
    # Inglês (Amazon Global e similares)
    "delivered from",
    "ships from",
    "shipped from",
    "shipping from",
    "international shipping",
    "international product",
    "import",
    "imported",
    "amazon.com ",  # vendido por amazon.com (não amazon.com.br)
    "ali express",
    "aliexpress",
    "wish.com",
    "from china",
    "from usa",
    "from united states",
]


def parece_compra_internacional(item, regiao):
    """Devolve True se o produto parecer ser de compra internacional para a região indicada.
    Para cada região, "internacional" significa: produto vendido localmente mas enviado
    de fora do território, o que implica taxas/frete que distorcem o preço aparente.

    - BR: produto enviado de fora do Brasil (USA, Mexico, China, EU…)
    - PT: produto enviado de fora da UE (Brasil, USA, UK pós-Brexit, China, etc.)
    - EU: produto enviado de fora da UE (Brasil, USA, UK pós-Brexit, China, etc.)
    - US: produto enviado de fora dos EUA (raro, mas existe via Amazon Global)
    """
    blob = " ".join([
        str(item.get("title", "")),
        str(item.get("snippet", "")),
        str(item.get("extensions", "")),
        str(item.get("source", "")),
        str(item.get("delivery", "")),
        str(item.get("tag", "")),
        str(item.get("badge", "")),
    ]).lower()

    # Palavras-chave genéricas (válidas para qualquer região)
    for kw in KEYWORDS_COMPRA_INTERNACIONAL:
        if kw in blob:
            return True

    # Palavras-chave adicionais por região (idioma local)
    if regiao == "BR":
        kws_extra_br = [
            "envio dos eua", "envio dos estados unidos",
            "vendido pela amazon.com", "vendido por amazon.com",
            "amazon estados unidos", "amazon eua",
        ]
        for kw in kws_extra_br:
            if kw in blob:
                return True

    elif regiao in ("PT", "EU"):
        # PT/EU: produtos enviados de fora da UE
        kws_extra_pt = [
            "envio do reino unido", "expedido do reino unido",
            "envio do brasil", "expedido do brasil",
            "envio dos estados unidos", "expedido dos estados unidos",
            "envio dos eua", "expedido dos eua",
            "envio da china", "expedido da china",
            "ships from united kingdom", "ships from brazil", "ships from china",
            "from outside eu", "non-eu shipping",
            "amazon.co.uk ",  # UK pós-Brexit é internacional para EU
            "amazon.com ",   # US
        ]
        for kw in kws_extra_pt:
            if kw in blob:
                return True

    elif regiao == "US":
        # US: produtos enviados de fora dos EUA
        kws_extra_us = [
            "ships from china", "ships from brazil", "ships from europe",
            "ships from united kingdom", "ships from japan",
            "international seller", "imported from",
        ]
        for kw in kws_extra_us:
            if kw in blob:
                return True

    return False


# Palavras-chave genéricas/ruidosas que não devem contar como "match" entre títulos
STOPWORDS_RELEVANCIA = {
    # Artigos/preposições/conjunções PT
    "de", "do", "da", "dos", "das", "e", "o", "a", "os", "as", "um", "uma",
    "para", "com", "em", "no", "na", "nos", "nas", "por", "ou",
    # Marcadores comerciais que aparecem em qualquer anúncio
    "novo", "nova", "lacrado", "lacrada", "original", "oficial",
    "frete", "gratis", "grátis", "promoção", "promocao", "oferta",
    "envio", "imediato", "garantia", "kit", "combo",
    # EN
    "new", "the", "a", "an", "and", "or", "for", "with", "of",
    "free", "shipping", "official", "original",
}


# Marcas conhecidas que detectamos automaticamente no nome do produto.
# Quando uma marca é detectada, é adicionada à consulta SerpAPI (melhora precisão)
# e exigida no título dos resultados (filtra falsos positivos como "bateria 10280").
# A ordem importa — aliases mais específicos primeiro, marcas mais comuns no topo.
MARCAS_CONHECIDAS = [
    # ─── Brinquedos & Hobby ───────────────────────────────────────
    ("LEGO", ["lego", "lego®"]),
    ("Playmobil", ["playmobil"]),
    ("Hot Wheels", ["hot wheels", "hotwheels"]),
    ("Funko", ["funko pop", "funko"]),
    ("Bandai", ["bandai"]),
    ("Hasbro", ["hasbro"]),
    ("Mattel", ["mattel"]),
    ("Sylvanian Families", ["sylvanian families", "sylvanian"]),
    ("Barbie", ["barbie"]),
    ("Mega Bloks", ["mega bloks", "megabloks", "mega construx"]),
    ("Fisher-Price", ["fisher-price", "fisher price"]),
    # ─── Bebés & Cuidado ─────────────────────────────────────────
    ("Pampers", ["pampers"]),
    ("Huggies", ["huggies"]),
    ("Dodot", ["dodot"]),
    ("MamyPoko", ["mamypoko", "mamy poko"]),
    ("Chicco", ["chicco"]),
    ("Mustela", ["mustela"]),
    ("Aveeno Baby", ["aveeno baby"]),
    ("Aveeno", ["aveeno"]),
    # ─── Higiene & Beleza ────────────────────────────────────────
    ("Johnson's", ["johnson's", "johnsons", "johnson&apos;s"]),
    ("Pantene", ["pantene"]),
    ("Head & Shoulders", ["head & shoulders", "head and shoulders", "h&s"]),
    ("L'Oréal", ["l'oréal", "loreal", "l'oreal"]),
    ("Garnier", ["garnier"]),
    ("Nivea", ["nivea"]),
    ("Dove", ["dove"]),
    ("Sebamed", ["sebamed"]),
    ("Avène", ["avène", "avene"]),
    ("La Roche-Posay", ["la roche-posay", "la roche posay"]),
    ("Eucerin", ["eucerin"]),
    # ─── Electrónica ─────────────────────────────────────────────
    ("Apple", ["apple", "iphone", "ipad", "macbook", "airpods"]),
    ("Samsung", ["samsung", "galaxy"]),
    ("Xiaomi", ["xiaomi", "redmi", "poco"]),
    ("Sony", ["sony", "playstation", "ps5", "ps4"]),
    ("Microsoft", ["microsoft", "xbox", "surface"]),
    ("Nintendo", ["nintendo", "switch"]),
    ("LG", ["lg electronics"]),  # "lg" sozinho é ambíguo
    ("Asus", ["asus"]),
    ("Lenovo", ["lenovo"]),
    ("HP", ["hp inc", "hewlett-packard"]),  # "hp" sozinho é ambíguo
    ("Dell", ["dell"]),
    # ─── Casa & Limpeza ──────────────────────────────────────────
    ("Tide", ["tide"]),
    ("Ariel", ["ariel "]),  # com espaço para evitar "arielle"
    ("Skip", ["skip "]),
    ("Calgon", ["calgon"]),
    ("Cif", ["cif "]),
    ("Pinho Sol", ["pinho sol", "pinho-sol"]),
    # ─── Alimentar / Pet ─────────────────────────────────────────
    ("Nestlé", ["nestlé", "nestle"]),
    ("Royal Canin", ["royal canin"]),
    ("Pedigree", ["pedigree"]),
    ("Whiskas", ["whiskas"]),
    ("Friskies", ["friskies"]),
    ("Purina", ["purina"]),
    ("Pro Plan", ["pro plan", "proplan"]),
]


def detectar_marca(nome_produto):
    """Devolve o nome canónico da marca se for detectada no nome do produto, senão None.
    Exemplo: '10280 - LEGO® Icons - Buquê de Flores' → 'LEGO'
             'Pampers Active Baby T4 70un' → 'Pampers'"""
    if not nome_produto:
        return None
    nome_lower = str(nome_produto).lower()
    for marca_canonica, aliases in MARCAS_CONHECIDAS:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", nome_lower):
                return marca_canonica
    return None


def classificar_relevancia(item, nome_produto, sku, marca_esperada=None):
    """Classifica a relevância do título de um resultado SerpAPI face ao produto procurado.

    Devolve uma das 3 strings:
    - "forte"   → marca + SKU exacto no título (alta confiança, é o produto procurado)
    - "fraco"   → marca confirmada, mas SKU não bate ou ausente (similar — mostrar no expander)
    - "rejeitar"→ sem marca correcta ou totalmente irrelevante (lixo, não mostrar)
    """
    titulo = str(item.get("title", "")).lower().strip()
    if not titulo:
        return "rejeitar"

    # 1) Marca: usa o que foi passado, senão tenta detectar do nome
    if marca_esperada is None:
        marca_esperada = detectar_marca(nome_produto)

    marca_no_titulo = False
    if marca_esperada:
        marca_lower = marca_esperada.lower()
        aliases_marca = next(
            (aliases for canon, aliases in MARCAS_CONHECIDAS if canon == marca_esperada),
            [marca_lower]
        )
        marca_no_titulo = any(
            re.search(rf"\b{re.escape(a)}\b", titulo) for a in aliases_marca
        )

    sku_str = str(sku).strip().lower() if sku else ""
    sku_no_titulo = False
    if sku_str:
        if re.search(rf"\b{re.escape(sku_str)}\b", titulo):
            sku_no_titulo = True

    # 1) Se temos marca esperada mas NÃO está no título E nem o SKU está → rejeitar
    # (excepção: SKU específico e único — referência clara mesmo sem marca explícita)
    if marca_esperada and not marca_no_titulo:
        # Sem marca, mas há SKU específico (4+ caracteres) no título?
        # Aceita-se porque o SKU é referência única (10281 = LEGO sem precisar dizer "LEGO")
        if not (sku_no_titulo and len(sku_str) >= 4):
            return "rejeitar"

    # 2) ✅ FORTE: marca confirmada + SKU exacto OU SKU específico sozinho
    if (marca_no_titulo or (sku_no_titulo and len(sku_str) >= 4)) and sku_no_titulo:
        return "forte"

    # SKU alfanumérico (ex: LGO75301) sozinho é considerado forte
    if sku_no_titulo and any(c.isalpha() for c in sku_str):
        return "forte"

    if not nome_produto:
        # Sem nome para comparar — se o SKU bate é forte, senão rejeitar
        return "forte" if sku_no_titulo else "rejeitar"

    # Equivalências PT-BR ↔ PT-PT ↔ EN
    EQUIV = {
        "buquê": "bouquet", "buque": "bouquet", "bouquet": "bouquet",
        "icons": "creator", "creator": "creator",
        "estrela": "star", "star": "star",
        "guerras": "wars", "wars": "wars",
        "natal": "christmas", "christmas": "christmas",
    }
    def _tokens(s):
        s = re.sub(r"[^\w\s]", " ", s.lower())
        tokens = set()
        for w in s.split():
            if len(w) < 3 or w in STOPWORDS_RELEVANCIA:
                continue
            tokens.add(EQUIV.get(w, w))
        return tokens

    tokens_esperados = _tokens(nome_produto)
    if not tokens_esperados:
        return "forte" if sku_no_titulo else ("fraco" if marca_no_titulo else "rejeitar")

    tokens_titulo = _tokens(titulo)
    intersecao = tokens_esperados & tokens_titulo

    # 3) Marca confirmada + palavras a bater = FRACO (similar, vale para verificação)
    if marca_no_titulo:
        if len(intersecao) >= 1:
            return "fraco"
        # Marca presente mas zero palavras coincidem — provavelmente outro produto da marca
        # mas vale a pena o utilizador ver no expander (talvez é o mesmo produto renomeado)
        return "fraco"

    # Sem marca esperada — só palavras
    if len(tokens_esperados) <= 3 and len(intersecao) >= 1:
        return "forte"
    if len(intersecao) / len(tokens_esperados) >= 0.5:
        return "forte"

    return "rejeitar"


def titulo_relevante(item, nome_produto, sku, marca_esperada=None):
    """Wrapper de compatibilidade — devolve True se o resultado é minimamente relevante
    (forte OU fraco). Quem precisa de saber qual é dos dois deve usar classificar_relevancia."""
    return classificar_relevancia(item, nome_produto, sku, marca_esperada) != "rejeitar"


# =============================================================================
# 4. AUTENTICAÇÃO (Supabase Auth + Google OAuth) + CLIENTE SUPABASE
# =============================================================================
# Em Hugging Face Spaces, target="_top" funciona normalmente — não precisamos
# dos hacks que tentámos no Streamlit Cloud. Usamos Supabase Auth com Google.

def _get_anon_client():
    """Cliente Supabase com chave anónima (não autenticado, para auth).
    Tenta ler de st.secrets primeiro, depois de variáveis de ambiente
    (necessário no HF Spaces caso o secrets.toml não tenha sido gerado).
    Não usa cache porque queremos rever os secrets a cada chamada
    (caso secrets sejam alterados sem restart completo)."""
    if not SUPABASE_AVAILABLE:
        return None

    # Se já temos cliente em sessão, reutilizar
    cliente_cache = st.session_state.get("_supabase_anon_client")
    if cliente_cache is not None:
        return cliente_cache

    import os

    def _ler_secret(*nomes):
        for nome in nomes:
            try:
                v = st.secrets.get(nome)
                if v:
                    return v
            except Exception:
                pass
            v = os.environ.get(nome)
            if v:
                return v
        return None

    url = _ler_secret("SUPABASE_URL")
    key = _ler_secret("SUPABASE_ANON_KEY", "SUPABASE_KEY")

    if not url or not key:
        st.session_state["_supabase_init_error"] = (
            f"Secrets em falta — url={'OK' if url else 'MISSING'} key={'OK' if key else 'MISSING'}"
        )
        return None

    try:
        cliente = create_client(url, key)
        st.session_state["_supabase_anon_client"] = cliente
        st.session_state.pop("_supabase_init_error", None)
        return cliente
    except Exception as e:
        st.session_state["_supabase_init_error"] = f"{type(e).__name__}: {e}"
        return None


def _debug_secrets_disponiveis():
    """Diagnóstico para casos em que secrets parecem em falta.
    Não mostra valores, apenas se cada um foi encontrado."""
    import os
    nomes = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_KEY",
             "EMAIL_ORIGEM", "BLING_CLIENT_ID", "SITE_URL"]
    out = []
    for n in nomes:
        em_secrets = False
        em_env = bool(os.environ.get(n))
        try:
            em_secrets = bool(st.secrets.get(n))
        except Exception:
            pass
        marca = "✓" if (em_secrets or em_env) else "✗"
        fonte = []
        if em_secrets:
            fonte.append("st.secrets")
        if em_env:
            fonte.append("env")
        out.append(f"{marca} {n}: {', '.join(fonte) if fonte else '(não encontrado)'}")
    return "\n".join(out)



def _gerar_jwt_supabase(user_id):
    """Gera um JWT customizado assinado com o SUPABASE_JWT_SECRET.
    O Supabase reconhece este JWT como autêntico e `auth.uid()` devolve
    o valor do `sub`. Isto permite RLS com `auth.uid() = user_id`.

    Devolve None se o secret não estiver configurado ou em caso de erro."""
    if not user_id:
        return None
    jwt_secret = _ler_secret_global("SUPABASE_JWT_SECRET")
    if not jwt_secret:
        return None
    try:
        import jwt as pyjwt
        # Validade: 1 hora — renovamos a cada chamada de get_supabase_client
        exp = datetime.now(timezone.utc) + timedelta(hours=1)
        payload = {
            "sub": str(user_id),         # Subject = user_id Google
            "role": "authenticated",      # Role que o Supabase verifica
            "aud": "authenticated",       # Audience
            "exp": int(exp.timestamp()),
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        token = pyjwt.encode(payload, jwt_secret, algorithm="HS256")
        # Em PyJWT 2.x, devolve str; em 1.x devolve bytes
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        return token
    except Exception:
        return None


def get_supabase_client():
    """Cliente Supabase para queries da app.
    Se houver utilizador autenticado, gera um JWT customizado com o user_id
    e injecta no cliente. As tabelas com RLS activada vão usar `auth.uid()`
    para filtrar automaticamente. Se a tabela tiver RLS desactivada, funciona
    na mesma (o JWT é ignorado pela tabela)."""
    base = _get_anon_client()
    if base is None:
        return None

    uid = user_id_actual()
    if uid:
        token = _gerar_jwt_supabase(uid)
        if token:
            try:
                base.postgrest.auth(token)
            except Exception:
                pass  # Continua com anon — RLS-disabled tables vão funcionar
    return base


def supabase_ativo():
    return _get_anon_client() is not None


def utilizador_autenticado():
    return bool(st.session_state.get("user_session"))


def user_id_actual():
    sess = st.session_state.get("user_session") or {}
    return (sess.get("user") or {}).get("id")


def user_email_actual():
    sess = st.session_state.get("user_session") or {}
    return (sess.get("user") or {}).get("email")


def user_nome_actual():
    sess = st.session_state.get("user_session") or {}
    user = sess.get("user") or {}
    return user.get("name") or user.get("email")


def user_avatar_actual():
    sess = st.session_state.get("user_session") or {}
    return (sess.get("user") or {}).get("avatar")


def iniciar_login_google():
    """Devolve URL para o utilizador iniciar o login com Google via Supabase.
    Implementamos PKCE manualmente: geramos code_verifier + code_challenge.
    Para sobreviver a reinícios da sessão Streamlit, codificamos o code_verifier
    dentro do parâmetro `state` do OAuth (que o Supabase nos devolve intacto)."""
    import secrets as _secrets_mod
    import hashlib
    import base64

    sb = _get_anon_client()
    if sb is None:
        return None

    try:
        # 1) Gerar code_verifier aleatório (43-128 caracteres URL-safe)
        verifier = _secrets_mod.token_urlsafe(64)[:96]

        # 2) Calcular code_challenge = SHA256(verifier) em base64url sem padding
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")

        # 3) Construir URL de autorização do Supabase manualmente
        from urllib.parse import quote_plus
        supabase_url = _ler_secret_global("SUPABASE_URL")
        site_url = _ler_secret_global("SITE_URL") or ""

        params = (
            f"provider=google"
            f"&redirect_to={quote_plus(site_url)}"
            f"&code_challenge={challenge}"
            f"&code_challenge_method=s256"
        )
        return f"{supabase_url}/auth/v1/authorize?{params}", verifier

    except Exception as e:
        st.error(f"Falha ao iniciar login Google: {e}")
        return None, None


def _ler_secret_global(*nomes):
    """Helper global para ler secrets de st.secrets ou env."""
    for nome in nomes:
        try:
            v = st.secrets.get(nome)
            if v:
                return v
        except Exception:
            pass
        v = os.environ.get(nome)
        if v:
            return v
    return None


def _processar_token_url():
    """Detecta o `code` retornado pelo Supabase no callback e troca por sessão.
    O code_verifier é lido do query param `pkce_v` que codificámos quando
    geramos o link de login (sobrevive a reinícios da sessão Streamlit)."""
    if utilizador_autenticado():
        return

    qs = st.query_params

    if "code" not in qs:
        return

    # Bling também usa ?code=&state=... — distinguir pelo nosso pkce_v
    if "pkce_v" not in qs:
        # Provavelmente Bling, deixar passar
        return

    code = qs["code"]
    verifier = qs["pkce_v"]

    try:
        supabase_url = _ler_secret_global("SUPABASE_URL")
        anon_key = _ler_secret_global("SUPABASE_ANON_KEY", "SUPABASE_KEY")

        # Troca PKCE: POST para /auth/v1/token?grant_type=pkce
        r = requests.post(
            f"{supabase_url}/auth/v1/token",
            params={"grant_type": "pkce"},
            headers={
                "apikey": anon_key,
                "Content-Type": "application/json",
            },
            json={
                "auth_code": code,
                "code_verifier": verifier,
            },
            timeout=30,
        )

        if r.status_code != 200:
            st.session_state["_oauth_last_error"] = (
                f"Token endpoint devolveu {r.status_code}: {r.text[:300]}"
            )
            st.query_params.clear()
            return

        dados = r.json()
        access_token = dados.get("access_token")
        refresh_token = dados.get("refresh_token")
        user = dados.get("user") or {}
        user_meta = user.get("user_metadata") or {}

        if not access_token or not user.get("id"):
            st.session_state["_oauth_last_error"] = (
                f"Resposta inesperada do token endpoint: {list(dados.keys())}"
            )
            st.query_params.clear()
            return

        st.session_state["user_session"] = {
            "access_token": access_token,
            "refresh_token": refresh_token or "",
            "user": {
                "id": user["id"],
                "email": user.get("email", ""),
                "name": user_meta.get("full_name", ""),
                "avatar": user_meta.get("avatar_url", ""),
            },
        }
        # Criar sessão persistente no Supabase e injectar ?sid=... na URL.
        # Isto sobrevive a navegações (Bling OAuth, refresh, fechar/abrir aba).
        sid = _criar_sessao_persistente(st.session_state["user_session"])
        st.query_params.clear()
        if sid:
            st.query_params["sid"] = sid
        else:
            # Falha ao criar SID — guardar warning para mostrar na app
            err = st.session_state.get("_sid_save_error", "(sem detalhes)")
            st.session_state["_sid_init_warning"] = (
                f"Sessão persistente não pôde ser criada — login Bling pode "
                f"não funcionar. Erro: {err}"
            )
        st.session_state.pop("_oauth_last_error", None)
        st.rerun()

    except Exception as e:
        st.session_state["_oauth_last_error"] = f"{type(e).__name__}: {e}"
        st.query_params.clear()


def fazer_logout():
    # Apagar sessão persistente no Supabase antes de limpar session_state
    _apagar_sessao_persistente()
    sb = _get_anon_client()
    if sb is not None:
        try:
            sb.auth.sign_out()
        except Exception:
            pass
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def renderizar_pagina_login():
    """Tela de login. Em HF Spaces, target=_top funciona normalmente."""
    st.title("🌎 Viabilidade de Vendas")
    st.markdown("### Análise de preços e concorrência para o seu catálogo")
    st.divider()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("#### Faça login para começar")
        st.write("")

        # Se houve tentativa de login que falhou, mostrar erro
        oauth_err = st.session_state.get("_oauth_last_error")
        if oauth_err:
            st.error(f"⚠️ Tentativa de login falhou:\n\n`{oauth_err}`")
            if st.button("Limpar erro e tentar de novo"):
                st.session_state.pop("_oauth_last_error", None)
                st.rerun()

        if not supabase_ativo():
            st.error(
                "🔌 Sistema de autenticação indisponível. "
                "Tente recarregar a página. Se persistir, contacte o suporte."
            )
            with st.expander("🔍 Detalhes técnicos"):
                st.code(_debug_secrets_disponiveis(), language="text")
                init_err = st.session_state.get("_supabase_init_error")
                if init_err:
                    st.warning(f"**Erro:** `{init_err}`")
            return

        # Gerar URL OAuth + verifier. Codificamos o verifier no parâmetro
        # `pkce_v` da URL `redirect_to`, para que ele volte connosco e
        # consigamos completar a troca PKCE mesmo com sessão Streamlit perdida.
        url_oauth, verifier = iniciar_login_google()

        if url_oauth and verifier:
            # Reescrever a URL: queremos que o Supabase, ao redireccionar
            # de volta para o nosso `redirect_to`, mantenha `pkce_v` lá.
            # Solução: injectar `pkce_v` directamente no SITE_URL de redirect.
            from urllib.parse import quote_plus, urlencode, urlparse, parse_qs, urlunparse
            site_url = _ler_secret_global("SITE_URL") or ""
            sep = "&" if "?" in site_url else "?"
            site_url_com_pkce = f"{site_url}{sep}pkce_v={verifier}"

            # Reconstruir o URL OAuth com o redirect_to actualizado
            supabase_url = _ler_secret_global("SUPABASE_URL")
            import hashlib, base64
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).decode("ascii").rstrip("=")
            url_oauth = (
                f"{supabase_url}/auth/v1/authorize"
                f"?provider=google"
                f"&redirect_to={quote_plus(site_url_com_pkce)}"
                f"&code_challenge={challenge}"
                f"&code_challenge_method=s256"
            )

            # Link HTML com target=_top — em HF Spaces escapa do iframe sem problemas
            st.markdown(
                f"""
                <a href="{url_oauth}" target="_top" style="
                    display: inline-block;
                    padding: 0.5rem 1.2rem;
                    background-color: #FF4B4B;
                    color: white;
                    text-decoration: none;
                    border-radius: 0.5rem;
                    font-size: 0.95rem;
                    border: 1px solid #FF4B4B;
                    font-weight: 500;
                ">🔐 Entrar com Google</a>
                """,
                unsafe_allow_html=True,
            )

        st.caption(
            "Ao entrar, aceita os Termos de Utilização e a Política de Privacidade. "
            "Os seus dados (catálogo, análises) ficam isolados — só você os vê."
        )

        st.divider()
        with st.expander("ℹ️ Como funciona"):
            st.markdown("""
- **Login simples** com a sua conta Google (sem criar nova senha)
- **Carregue o seu catálogo** via planilha Excel/CSV ou ligação directa ao Bling V3 (Brasil)
- **Configure margem, imposto e markup** uma vez — ficam memorizados
- **Selecione os produtos** que quer analisar (economize créditos SerpAPI)
- **Análise inteligente** compara cada produto com concorrentes confiáveis da sua região
- **Recomendações automáticas** indicam quais produtos focar/comprar/liquidar
- **Atualize preços no Bling** directamente da app (modo Brasil + Bling)
- **Histórico** das suas análises guardado para ver tendências

✅ Os seus dados são privados — cada utilizador só vê os seus produtos.
            """)


# =============================================================================
# 4b. INTEGRAÇÃO BLING OAUTH2 (V3)
# =============================================================================
BLING_AUTH_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
BLING_TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"
BLING_API_BASE = "https://api.bling.com.br/Api/v3"


def bling_credenciais_disponiveis():
    """Verifica se há client_id e client_secret nos Secrets."""
    try:
        return bool(st.secrets["BLING_CLIENT_ID"] and st.secrets["BLING_CLIENT_SECRET"])
    except (KeyError, FileNotFoundError):
        return False


def _bling_redirect_uri():
    """URL para onde o Bling vai redirecionar após autorização.
    Usa SITE_URL (definido nos Secrets) ou BLING_REDIRECT_URI específico,
    para suportar mudanças de host (Streamlit Cloud → Hugging Face)."""
    # 1) Override específico se configurado
    v = _ler_secret_global("BLING_REDIRECT_URI")
    if v:
        return v
    # 2) SITE_URL (mesma URL onde a app está deployada)
    v = _ler_secret_global("SITE_URL")
    if v:
        return v
    # 3) Fallback histórico (Streamlit Cloud antigo) — só para não rebentar
    return "https://viabilidadedevendas.streamlit.app/"


def bling_iniciar_autorizacao():
    """Devolve URL para o utilizador autorizar a aplicação no Bling.
    Codifica o `sid` da sessão actual dentro do parâmetro `state` para que,
    quando o Bling redirecionar de volta, possamos restaurar a sessão Google
    (que de outra forma seria perdida pela navegação)."""
    import secrets as py_secrets

    # Format: "<sid>|<random>" — sid permite restaurar sessão; random é CSRF token
    sid_actual = st.query_params.get("sid", "") or ""
    random_token = py_secrets.token_urlsafe(16)
    state = f"{sid_actual}|{random_token}"

    params = {
        "response_type": "code",
        "client_id": _ler_secret_global("BLING_CLIENT_ID") or "",
        "state": state,
        "redirect_uri": _bling_redirect_uri(),
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{BLING_AUTH_URL}?{qs}"


def _bling_basic_header():
    """Header de Basic Auth: base64(client_id:client_secret)."""
    cid = st.secrets["BLING_CLIENT_ID"]
    csec = st.secrets["BLING_CLIENT_SECRET"]
    raw = f"{cid}:{csec}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def bling_trocar_codigo_por_tokens(codigo):
    """Troca o `code` recebido do redirect pelo par (access_token, refresh_token).
    Guarda os tokens no Supabase para reutilização entre sessões."""
    try:
        r = requests.post(
            BLING_TOKEN_URL,
            headers={
                "Authorization": f"Basic {_bling_basic_header()}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "authorization_code",
                "code": codigo,
            },
            timeout=30,
        )
        if r.status_code != 200:
            return False, f"Erro {r.status_code}: {r.text[:300]}"
        dados = r.json()
        _bling_guardar_tokens(dados)
        return True, "Conectado ao Bling"
    except Exception as e:
        return False, f"Falha ao trocar código: {e}"


def bling_renovar_token():
    """Usa refresh_token para obter novo access_token. Devolve True/False."""
    tokens = _bling_carregar_tokens()
    if not tokens or not tokens.get("refresh_token"):
        return False
    try:
        r = requests.post(
            BLING_TOKEN_URL,
            headers={
                "Authorization": f"Basic {_bling_basic_header()}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            },
            timeout=30,
        )
        if r.status_code != 200:
            return False
        _bling_guardar_tokens(r.json())
        return True
    except Exception:
        return False


def _bling_guardar_tokens(payload):
    """Persiste tokens no Supabase para o utilizador autenticado actual.
    payload vem do endpoint /oauth/token do Bling."""
    sb = get_supabase_client()
    if sb is None:
        return
    uid = user_id_actual()
    if not uid:
        return  # Sem utilizador autenticado, não há onde guardar
    expires_in = int(payload.get("expires_in", 21600))  # default 6h
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    sb.table("bling_tokens").upsert({
        "user_id": uid,
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="user_id").execute()


def _bling_carregar_tokens():
    """Lê tokens do Supabase para o utilizador autenticado actual. Devolve dict ou None."""
    sb = get_supabase_client()
    if sb is None:
        return None
    uid = user_id_actual()
    if not uid:
        return None
    try:
        r = sb.table("bling_tokens").select("*").eq("user_id", uid).limit(1).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None


def bling_access_token_valido():
    """Devolve access_token válido ou None. Renova automaticamente se expirado."""
    tokens = _bling_carregar_tokens()
    if not tokens:
        return None
    try:
        expires_at = datetime.fromisoformat(tokens["expires_at"].replace("Z", "+00:00"))
        # Renovar 5 min antes de expirar para evitar corridas
        if datetime.now(timezone.utc) + timedelta(minutes=5) >= expires_at:
            if bling_renovar_token():
                tokens = _bling_carregar_tokens()
            else:
                return None
        return tokens["access_token"]
    except Exception:
        return None


def bling_conectado():
    return bling_access_token_valido() is not None


def bling_desconectar():
    """Apaga os tokens do utilizador actual. Próxima utilização exigirá nova autorização."""
    sb = get_supabase_client()
    if sb is None:
        return
    uid = user_id_actual()
    if not uid:
        return
    try:
        sb.table("bling_tokens").delete().eq("user_id", uid).execute()
    except Exception:
        pass


def bling_listar_produtos(pagina=1, limite=100):
    """Lista produtos do Bling V3. Devolve (lista, total_paginas) ou ([], 0) em erro."""
    token = bling_access_token_valido()
    if not token:
        return [], 0
    try:
        r = requests.get(
            f"{BLING_API_BASE}/produtos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"pagina": pagina, "limite": limite},
            timeout=30,
        )
        if r.status_code == 401:
            if bling_renovar_token():
                token = bling_access_token_valido()
                r = requests.get(
                    f"{BLING_API_BASE}/produtos",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params={"pagina": pagina, "limite": limite},
                    timeout=30,
                )
        if r.status_code != 200:
            st.warning(f"Bling devolveu {r.status_code}: {r.text[:200]}")
            return [], 0
        dados = r.json()
        return dados.get("data", []), 1
    except Exception as e:
        st.warning(f"Erro ao chamar Bling: {e}")
        return [], 0


def bling_procurar_id_por_sku(sku):
    """Procura o id Bling de um produto a partir do SKU (campo `codigo`).
    Devolve int do id ou None se não encontrar."""
    token = bling_access_token_valido()
    if not token or not sku:
        return None
    try:
        r = requests.get(
            f"{BLING_API_BASE}/produtos",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"codigo": str(sku), "limite": 5},
            timeout=20,
        )
        if r.status_code != 200:
            return None
        produtos = r.json().get("data", [])
        for p in produtos:
            if str(p.get("codigo", "")) == str(sku):
                return p.get("id")
        # Não encontrou match exacto — devolver primeiro candidato se houver
        return produtos[0].get("id") if produtos else None
    except Exception:
        return None


def bling_obter_preco_atual(produto_id):
    """Obtém o preço atual do produto no Bling V3.
    Usa GET em /produtos/{id} e extrai o campo `preco`.
    Devolve (preco: float | None, mensagem: str).
    """
    token = bling_access_token_valido()
    if not token:
        return None, "Sem token Bling válido"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    url = f"{BLING_API_BASE}/produtos/{produto_id}"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return None, f"GET falhou ({r.status_code})"
        produto = r.json().get("data") or {}
        preco_raw = produto.get("preco")
        if preco_raw is None:
            return None, "Sem preço definido"
        try:
            preco = float(preco_raw)
        except (TypeError, ValueError):
            return None, f"Preço inválido: {preco_raw!r}"
        return preco, "ok"
    except Exception as e:
        return None, f"Erro: {e}"


def bling_atualizar_preco(produto_id, novo_preco):
    """Actualiza o preço de venda de um produto no Bling V3.
    Usa PATCH em /produtos/{id} enviando apenas o campo `preco` — evita problemas
    com campos customizados (que requerem permissão extra) ou outros campos do
    produto que poderiam ser interpretados como tentativa de alteração.
    Devolve (ok: bool, mensagem: str)."""
    token = bling_access_token_valido()
    if not token:
        return False, "Sem token Bling válido"

    def _formatar_erro_bling(resp):
        """Tenta extrair description detalhada do JSON de erro Bling."""
        try:
            j = resp.json()
            err = j.get("error", {}) if isinstance(j, dict) else {}
            tipo = err.get("type", "")
            msg = err.get("message", "")
            desc = err.get("description", "")
            fields = err.get("fields", []) or []
            parts = []
            if msg:
                parts.append(msg)
            if desc:
                parts.append(desc)
            if fields:
                campos_txt = ", ".join(
                    f"{f.get('element', '?')}: {f.get('msg', '')}"
                    for f in fields if isinstance(f, dict)
                )
                if campos_txt:
                    parts.append(f"campos: {campos_txt}")
            if tipo:
                parts.append(f"[{tipo}]")
            return " | ".join(parts) or resp.text[:500]
        except Exception:
            return resp.text[:500]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    url = f"{BLING_API_BASE}/produtos/{produto_id}"

    try:
        # Estratégia 1: PATCH com payload mínimo (só preço)
        r = requests.patch(url, headers=headers, json={"preco": float(novo_preco)}, timeout=30)
        if r.status_code in (200, 201, 204):
            return True, "Preço atualizado"

        # Estratégia 2 (fallback): se PATCH não suportado (405), tentar PUT com mínimo
        if r.status_code == 405:
            # GET para obter campos obrigatórios (nome, codigo, etc.)
            r_get = requests.get(url, headers=headers, timeout=20)
            if r_get.status_code != 200:
                return False, f"GET falhou ({r_get.status_code}): {_formatar_erro_bling(r_get)}"
            produto = r_get.json().get("data") or {}
            # Manter apenas campos básicos (sem campos customizados que requerem permissão)
            campos_seguros = ("nome", "codigo", "preco", "tipo", "situacao", "formato",
                              "descricaoCurta", "unidade")
            payload_min = {k: produto[k] for k in campos_seguros if k in produto}
            payload_min["preco"] = float(novo_preco)
            r2 = requests.put(url, headers=headers, json=payload_min, timeout=30)
            if r2.status_code in (200, 201, 204):
                return True, "Preço atualizado (via PUT fallback)"
            return False, f"PUT fallback falhou ({r2.status_code}): {_formatar_erro_bling(r2)}"

        # Outros erros do PATCH
        return False, f"PATCH falhou ({r.status_code}): {_formatar_erro_bling(r)}"
    except Exception as e:
        return False, f"Erro: {e}"


def bling_importar_catalogo(progresso_cb=None, apenas_com_stock=False):
    """Importa todos os produtos do Bling, paginando até esgotar.
    progresso_cb(pagina_atual, n_total_acumulado) é chamado entre páginas (opcional).
    apenas_com_stock=True filtra para produtos com saldoVirtualTotal > 0 ou estoque > 0."""
    todos = []
    pagina = 1
    while True:
        produtos, _ = bling_listar_produtos(pagina=pagina, limite=100)
        if not produtos:
            break

        if apenas_com_stock:
            filtrados = []
            for p in produtos:
                # O Bling V3 tem diversos campos para stock; testamos os mais comuns
                stock = (
                    p.get("estoque", {}).get("saldoVirtualTotal")
                    if isinstance(p.get("estoque"), dict) else None
                )
                if stock is None:
                    stock = p.get("estoque") if isinstance(p.get("estoque"), (int, float)) else None
                if stock is None:
                    stock = p.get("saldoVirtualTotal")
                try:
                    if stock is not None and float(stock) > 0:
                        filtrados.append(p)
                except (TypeError, ValueError):
                    pass
            todos.extend(filtrados)
        else:
            todos.extend(produtos)

        if progresso_cb:
            progresso_cb(pagina, len(todos))
        if len(produtos) < 100:
            break  # última página
        pagina += 1
        if pagina > 50:  # circuit breaker para evitar loop infinito
            break
    return todos


def gravar_historico_supabase(df_resultado, regiao, scope, imposto, markup, margem_minima):
    """Grava a análise + snapshot de preços no Supabase. Devolve analise_id ou None."""
    sb = get_supabase_client()
    if sb is None:
        return None

    # Cálculo defensivo: o modo "preco_venda" não tem coluna 'Custo' nem 'Lucro Total'.
    # Nesse caso, usamos o preço actual × qtde como proxy do "investimento em stock"
    # e lucro = 0 (não temos custo para calcular margem real).
    if "Custo" in df_resultado.columns:
        investimento = float((df_resultado["Custo"] * df_resultado["Qtde"]).sum())
    elif "Preço Actual" in df_resultado.columns:
        investimento = float((df_resultado["Preço Actual"] * df_resultado["Qtde"]).sum())
    else:
        investimento = 0.0

    if "Lucro Total" in df_resultado.columns:
        lucro = float(df_resultado["Lucro Total"].sum())
    else:
        lucro = 0.0

    # Validar que há utilizador autenticado (não devíamos chegar aqui sem user, mas defensivo)
    uid = user_id_actual()
    if not uid:
        st.warning("Não foi possível gravar histórico: utilizador não autenticado.")
        return None

    try:
        analise_resp = sb.table("analises").insert({
            "user_id": uid,
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
            "user_id": uid,
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
    """Lista as últimas análises feitas pelo utilizador actual.
    Com RLS activa, o filtro por user_id é redundante mas mantido como defesa em profundidade."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    uid = user_id_actual()
    if not uid:
        return pd.DataFrame()
    try:
        resp = sb.table("analises").select("*").eq("user_id", uid).order("criado_em", desc=True).limit(limite).execute()
        return pd.DataFrame(resp.data)
    except Exception as e:
        st.warning(f"Erro ao ler análises: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=60)
def carregar_historico_produto(ean, sku, nome, regiao, dias=180):
    """Devolve histórico de preços de um produto para o utilizador actual.
    Estratégia: filtra por EAN (mais preciso) > SKU (universal do fabricante) > nome (fallback)."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    uid = user_id_actual()
    if not uid:
        return pd.DataFrame()
    try:
        data_limite = (datetime.utcnow() - timedelta(days=dias)).isoformat()
        query = sb.table("historico_precos").select("*").eq("user_id", uid).eq("regiao", regiao).gte("criado_em", data_limite)
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
    """Top produtos mais analisados pelo utilizador actual na região, com últimos preços."""
    sb = get_supabase_client()
    if sb is None:
        return pd.DataFrame()
    uid = user_id_actual()
    if not uid:
        return pd.DataFrame()
    try:
        data_limite = (datetime.utcnow() - timedelta(days=dias)).isoformat()
        resp = sb.table("historico_precos").select("nome, ean, sku, menor_concorrente, score_procura, status, criado_em").eq("user_id", uid).eq("regiao", regiao).gte("criado_em", data_limite).execute()
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
    """Filtragem de vendedor — estratégia 'tudo aceite excepto lixo conhecido'.

    Filosofia: o utilizador quer ver os mesmos resultados que veria num Google Shopping
    directo. Em vez de exigir a loja estar numa whitelist (que requer manutenção contínua),
    aceitamos por defeito e rejeitamos APENAS:

    1. Lojas/marketplaces na blacklist (eBay com revendedores particulares, Aliexpress,
       lojas fraude conhecidas, sites de "compatível com X", etc.)
    2. Itens sem source nem link válido (lixo da SerpAPI)
    3. Se a whitelist for explicitamente "minúscula e restrita" (modo PT_ONLY estrito),
       respeita-a — mas EU/USA são abertos.

    Devolve: True (aceitar) ou False (rejeitar).
    """
    fonte = str(item.get("source", "")).lower().strip()
    link = str(item.get("link", "")).lower().strip()

    # Sem source nem link → lixo
    if not fonte and not link:
        return False

    try:
        dominio = urlparse(link).netloc.lower() if link else ""
    except Exception:
        dominio = ""

    # Normalizar fonte para comparar (remove acentos/espaços/pontuação)
    import unicodedata
    fonte_normalizada = unicodedata.normalize("NFKD", fonte).encode("ascii", "ignore").decode("ascii")
    fonte_normalizada = re.sub(r"[^a-z0-9]", "", fonte_normalizada)
    blob = f"{fonte} {link} {dominio} {fonte_normalizada}"

    # Blacklist: rejeita imediatamente
    for b in blacklist:
        b_low = b.lower()
        if b_low in blob:
            return False
        b_no_tld = re.sub(r"\.(com|pt|es|de|fr|it|nl|com\.br|co\.uk)$", "", b_low)
        b_no_tld = re.sub(r"[^a-z0-9]", "", b_no_tld)
        if b_no_tld and b_no_tld in fonte_normalizada:
            return False

    # Sem whitelist → aceita tudo (excepto blacklist acima)
    if not whitelist:
        return True

    # Se a whitelist é "pequena" (< 25 entradas), tratamos como modo estrito (PT_ONLY)
    # Senão, é apenas uma lista indicativa — aceita também o que não está nela
    if len(whitelist) < 25:
        # Modo estrito: SÓ aceita se bater
        for w in whitelist:
            w_low = w.lower()
            if w_low in blob:
                return True
            w_no_tld = re.sub(r"\.(com|pt|es|de|fr|it|nl|com\.br|co\.uk)$", "", w_low)
            w_no_tld = re.sub(r"[^a-z0-9]", "", w_no_tld)
            if w_no_tld and w_no_tld in fonte_normalizada:
                return True
        return False

    # Modo aberto: aceita por defeito (whitelist é só "lista preferida")
    return True


# ============================================================================
# CACHE DE LINKS DIRECTOS DA LOJA (Plano B)
# ============================================================================
# A SerpAPI no engine google_shopping NÃO devolve links directos da loja em PT/UE
# (devolve apenas product_link → Google Shopping, e o campo `link` vem vazio).
#
# Para obter o URL real (worten.pt/produtos/X, continente.pt/produto/Y, etc.)
# é preciso uma 2ª chamada à API google_product, que devolve `sellers_results`
# com os links reais de cada loja para esse product_id.
#
# ============================================================
# Cache de buscas SerpAPI principal (google_shopping)
# ============================================================
# Tabela Supabase: `cache_serpapi_searches`
# Colunas: query_hash (PK), query, gl, results (jsonb), updated_at
# TTL: 24 horas. Cache GLOBAL (partilhada entre utilizadores) — não há info sensível.

import hashlib as _hashlib_serpcache

CACHE_SERPAPI_TTL_HORAS = 24

def _cache_serpapi_chave(query: str, gl: str):
    """Gera hash único da query+região para usar como chave de cache."""
    raw = f"{query.lower().strip()}|{gl.lower().strip()}"
    return _hashlib_serpcache.sha256(raw.encode("utf-8")).hexdigest()


@st.cache_data(ttl=60, show_spinner=False)
def _cache_serpapi_get(query: str, gl: str):
    """Procura resultados em cache Supabase. Devolve (results: dict | None, idade_horas: float | None).
    Cache válido durante CACHE_SERPAPI_TTL_HORAS."""
    if not query:
        return None, None
    try:
        sb = get_supabase_client()
        if not sb:
            return None, None
        chave = _cache_serpapi_chave(query, gl)
        res = sb.table("cache_serpapi_searches").select("results, updated_at").eq("query_hash", chave).limit(1).execute()
        if not res.data:
            return None, None
        row = res.data[0]
        try:
            updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            idade = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
            if idade > CACHE_SERPAPI_TTL_HORAS:
                return None, None  # expirado
            return row.get("results") or {}, idade
        except Exception:
            return None, None
    except Exception:
        return None, None


def _cache_serpapi_set(query: str, gl: str, results: dict):
    """Guarda resultados na cache Supabase. Faz upsert."""
    if not query or not results:
        return
    try:
        sb = get_supabase_client()
        if not sb:
            return
        chave = _cache_serpapi_chave(query, gl)
        sb.table("cache_serpapi_searches").upsert({
            "query_hash": chave,
            "query": query[:500],
            "gl": gl,
            "results": results,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="query_hash").execute()
        _cache_serpapi_get.clear()
    except Exception as e:
        print(f"[CACHE-SERPAPI] Falha ao guardar '{query[:60]}': {e}", flush=True)


def _cache_serpapi_invalidar_tudo():
    """Limpa cache local Streamlit (não apaga Supabase) — força próxima leitura a re-consultar BD."""
    try:
        _cache_serpapi_get.clear()
    except Exception:
        pass


# ========== CONSULTA DE CRÉDITOS SERPAPI ==========
# O endpoint /account.json devolve estatísticas da conta (searches_left, plan_searches_left,
# this_month_usage). É uma chamada META — NÃO consome créditos de busca.

@st.cache_data(ttl=60, show_spinner=False)
def obter_creditos_serpapi(api_key: str) -> dict | None:
    """Consulta /account.json da SerpAPI.
    NÃO consome créditos. Cache local 60s para evitar spam.
    Retorna dict com 'searches_left', 'plan_searches_left', 'this_month_usage' ou None."""
    if not api_key or len(api_key.strip()) < 10:
        return None
    try:
        import requests
        resp = requests.get(
            "https://serpapi.com/account.json",
            params={"api_key": api_key.strip()},
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "searches_left": int(data.get("searches_left", 0)),
                "plan_searches_left": int(data.get("plan_searches_left", 0)),
                "this_month_usage": int(data.get("this_month_usage", 0)),
                "account_email": data.get("account_email", ""),
            }
        return None
    except Exception as e:
        print(f"[SERPAPI-CREDITOS] erro: {e}", flush=True)
        return None


# Para reduzir o custo SerpAPI, fazemos cache no Supabase com TTL 30 dias.
# Cache é GLOBAL (partilhada entre utilizadores) — é só URL público de loja,
# não há informação sensível.

@st.cache_data(ttl=300, show_spinner=False)
def _cache_get_sellers(product_id: str):
    """Procura sellers na cache Supabase. Devolve lista de {name, link, price} ou None.
    Cache válida durante 30 dias."""
    if not product_id:
        return None
    try:
        sb = get_supabase_client()
        if not sb:
            return None
        res = sb.table("cache_product_sellers").select("sellers, updated_at").eq("product_id", str(product_id)).limit(1).execute()
        if not res.data:
            return None
        row = res.data[0]
        # Verificar TTL: 30 dias
        try:
            updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - updated_at).days > 30:
                return None  # expirou
        except Exception:
            pass
        return row.get("sellers") or []
    except Exception:
        return None


def _cache_set_sellers(product_id: str, gl: str, sellers: list):
    """Guarda sellers na cache Supabase. Faz upsert."""
    if not product_id or not sellers:
        return
    try:
        sb = get_supabase_client()
        if not sb:
            return
        sb.table("cache_product_sellers").upsert({
            "product_id": str(product_id),
            "gl": gl,
            "sellers": sellers,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="product_id").execute()
        # Invalidar cache local Streamlit para que próxima leitura vá ao Supabase
        _cache_get_sellers.clear()
    except Exception as e:
        print(f"[CACHE] Falha ao guardar sellers para {product_id}: {e}", flush=True)


def _fetch_real_sellers(cache_key: str, page_token: str, regiao_cfg: dict, api_key: str):
    """Faz 2ª chamada SerpAPI (engine=google_immersive_product) para obter URLs reais das lojas.

    cache_key: usado como chave única na cache (geralmente product_id da SerpAPI).
    page_token: o `immersive_product_page_token` que veio nos resultados de google_shopping.

    Devolve lista de {name, link, price_str}. Faz cache no Supabase (TTL 30 dias).

    A SerpAPI Google Product API foi descontinuada em Setembro 2025 (Google fechou o endpoint).
    Esta versão usa a alternativa oficial recomendada: google_immersive_product.
    """
    if not cache_key:
        return []

    # 1) Verificar cache primeiro
    cached = _cache_get_sellers(cache_key)
    if cached is not None:
        print(f"[PLANO-B] cache HIT key={cache_key} sellers={len(cached)}", flush=True)
        # DEBUG: para pids ricos (5+ stores), mostrar quais stores temos
        if len(cached) >= 5:
            for s in cached[:13]:
                _nm = s.get("name", "")[:30]
                _lk = str(s.get("link", ""))[:90]
                print(f"[PLANO-B]   store: '{_nm}' | {_lk}", flush=True)
        return cached

    if not page_token:
        return []  # sem token não há como chamar a API

    # 2) Cache miss — chamada SerpAPI google_immersive_product
    try:
        params = {
            "engine": "google_immersive_product",
            "page_token": page_token,
            "more_stores": "1",  # até 13 lojas em vez de 3-5 default
            "api_key": api_key,
        }
        search = GoogleSearch(params)
        results = search.get_dict()

        # As lojas estão em product_results.stores (estrutura nova da SerpAPI Maio 2026)
        _stores = (
            results.get("product_results", {}).get("stores", [])
            or results.get("stores", [])
            or []
        )

        sellers = []
        for s in _stores:
            link = s.get("link") or ""
            if not link or "google.com" in link.lower():
                continue  # ignorar links que vão ao Google
            sellers.append({
                "name": s.get("name", ""),
                "link": link,
                "price_str": s.get("price") or s.get("base_price") or "",
                "total_str": s.get("total") or "",
                "extracted_price": s.get("extracted_price"),
                "extracted_total": s.get("extracted_total"),
                "shipping": s.get("shipping", ""),
            })
        # 3) Popular cache (mesmo se vazia, para evitar repetir chamada falhada nos próximos 30 dias)
        _cache_set_sellers(cache_key, regiao_cfg["gl"], sellers)
        return sellers
    except Exception as e:
        print(f"[PLANO-B] EXCEPTION key={cache_key}: {e}", flush=True)
        return []


def _link_real_da_loja(item: dict, regiao_cfg: dict, api_key: str):
    """Para um item da SerpAPI, devolve o URL real da loja (via cache ou 2ª chamada
    google_immersive_product). Devolve '' se não conseguir."""
    pid = item.get("product_id")
    page_token = item.get("immersive_product_page_token", "")
    source = str(item.get("source", "")).strip().lower()
    if not pid or not source:
        return ""

    import unicodedata
    src_norm = unicodedata.normalize("NFKD", source).encode("ascii", "ignore").decode()
    src_norm = re.sub(r"[^a-z0-9]", "", src_norm)

    sellers = _fetch_real_sellers(str(pid), page_token, regiao_cfg, api_key)
    if not sellers:
        return ""
    for s in sellers:
        seller_name = str(s.get("name", "")).strip().lower()
        seller_norm = unicodedata.normalize("NFKD", seller_name).encode("ascii", "ignore").decode()
        seller_norm = re.sub(r"[^a-z0-9]", "", seller_norm)
        if src_norm and seller_norm:
            if src_norm in seller_norm or seller_norm in src_norm:
                return s.get("link", "")
    return ""


def buscar_serpapi(produto, ean, sku, custo, regiao_cfg, whitelist, blacklist, api_key,
                    apenas_novos=True, preco_minimo_pct_custo=0.40, marca_override=None,
                    forcar_busca=False):
    """Devolve concorrentes confiáveis + log de rejeitados.
    Estratégia em cascata: EAN > SKU+marca > Nome.
    Filtros aplicados:
    - Vendedor confiável da região (whitelist) e fora da blacklist
    - Produto novo (rejeita 'usado', 'open box', 'peças avulsas', etc.) se apenas_novos=True
    - Outlier de preço: rejeita preço abaixo de `preco_minimo_pct_custo` × custo
      (default 40%: se compraste a R$ 100, ignora resultados abaixo de R$ 40)
    - marca_override: se passar valor, usa esta marca em vez de detectar do nome
      (útil quando planilha tem coluna "Marca")
    - forcar_busca: se True, ignora cache e faz busca SerpAPI real (consome créditos)."""
    concorrentes = []           # match forte (marca + SKU exacto, alta confiança)
    concorrentes_similares = [] # match fraco (marca confirmada, sem SKU exacto — para verificação)
    rejeitados_log = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0, "irrelevante": 0, "internacional": 0, "acessorio": 0, "vendedor_naoconfiavel": 0, "serpapi_total": 0, "sem_preco": 0}

    # Detectar o tipo do produto procurado (principal / acessório / peça avulsa)
    # para filtrar resultados de forma coerente
    tipo_procurado = detectar_tipo_produto(produto)
    consultas = []

    def _valido(v):
        return v is not None and str(v).strip() and str(v).strip().lower() != "nan"

    # Marca: override da planilha tem prioridade; senão detectamos do nome
    if marca_override and str(marca_override).strip():
        marca = str(marca_override).strip()
    else:
        marca = detectar_marca(produto)

    # Ordem de prioridade (cascata — pára na 1ª que devolver concorrentes confiáveis):
    # 1) Marca + SKU      → principal: lojas costumam pôr SKU/referência no título
    # 2) Nome do produto  → fallback: nome descritivo, captura títulos sem referência numérica
    # 3) Marca + EAN      → último recurso: EAN raramente está em títulos (só metadado interno),
    #                       mas em USA e mercados maduros pode trazer match preciso
    if _valido(sku):
        if marca:
            consultas.append(f"{marca} {sku}")
        else:
            consultas.append(str(sku).strip())

    consultas.append(f"{produto}")

    if _valido(ean) and (not _valido(sku) or str(ean).strip() != str(sku).strip()):
        if marca:
            consultas.append(f"{marca} {str(ean).strip()}")
        else:
            consultas.append(str(ean).strip())

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
            # === CACHE CHECK ===
            # Se não estamos a forçar, tentar cache primeiro (TTL 24h, partilhada)
            results = None
            cache_hit = False
            if not forcar_busca:
                cached, idade_h = _cache_serpapi_get(q, regiao_cfg["gl"])
                if cached is not None:
                    results = cached
                    cache_hit = True
                    print(f"[CACHE-SERPAPI] HIT q='{q[:40]}' idade={idade_h:.1f}h", flush=True)
            if results is None:
                # Cache miss ou forçado → chamada real SerpAPI (consome crédito)
                search = GoogleSearch(params)
                results = search.get_dict()
                # Guardar em cache se devolveu algo válido
                if results and "error" not in results:
                    _cache_serpapi_set(q, regiao_cfg["gl"], results)
                    print(f"[CACHE-SERPAPI] MISS q='{q[:40]}' guardado", flush=True)
        except Exception as e:
            st.warning(f"Falha SerpAPI para '{q}': {e}")
            continue

        if "error" in results:
            st.warning(f"SerpAPI: {results['error']}")
            continue

        _items_dbg = results.get("shopping_results", []) or []
        _srcs_dbg = [str(it.get("source", ""))[:20] for it in _items_dbg]
        print(f"[US-DBG] q='{q}' total={len(_items_dbg)} sources={_srcs_dbg[:10]}", flush=True)

        # Acumular product_ids "ricos" (>=5 sellers) durante o loop para expansão
        # mesmo quando o item original é rejeitado. A SerpAPI dispersa product_ids
        # mas alguns são "canónicos" (com muitas lojas) — vale a pena tentar expandir
        # esses mesmo se o item da SerpAPI principal foi outlier ou acessório.
        _pids_ricos_orfaos = {}  # {pid: token}  — pids a expandir mesmo após rejeição
        _pids_ja_expandidos = set()  # pids que já foram expandidos via item aceito

        for item in _items_dbg:
            # Tentar registar este pid como "potencialmente rico" para expansão futura
            # Registamos TODOS os pids — mesmo com 1 seller — porque produtos novos podem
            # ter cada vendedor num PID separado. Depois validamos pelo SKU match.
            _pid_atual = item.get("product_id")
            _token_atual = item.get("immersive_product_page_token", "")
            if _pid_atual and _token_atual:
                _pids_ricos_orfaos[str(_pid_atual)] = _token_atual

            rejeitados_log["serpapi_total"] += 1
            _src = str(item.get("source", ""))[:20]
            _tit = str(item.get("title", ""))[:60]

            if not vendedor_confiavel(item, whitelist, blacklist):
                print(f"[US-DBG] VEND '{_src}' | '{_tit}'", flush=True)
                rejeitados_log["vendedor_naoconfiavel"] += 1
                continue

            relevancia = classificar_relevancia(item, produto, sku, marca_esperada=marca)
            if relevancia == "rejeitar":
                print(f"[US-DBG] REL '{_src}' | '{_tit}' (marca={marca} sku={sku})", flush=True)
                rejeitados_log["irrelevante"] += 1
                continue
            # `relevancia` agora é "forte" ou "fraco" — usado mais abaixo para
            # decidir em qual lista colocar o item.

            if apenas_novos and not parece_produto_novo(item):
                print(f"[US-DBG] USD '{_src}' | '{_tit}'", flush=True)
                rejeitados_log["usado"] += 1
                continue

            if not coerente_com_tipo(item, tipo_procurado):
                print(f"[US-DBG] TIPO '{_src}' | '{_tit}' (procurado={tipo_procurado})", flush=True)
                rejeitados_log["acessorio"] = rejeitados_log.get("acessorio", 0) + 1
                continue

            if parece_compra_internacional(item, regiao_cfg.get("id", "")):
                print(f"[US-DBG] INT '{_src}' | '{_tit}'", flush=True)
                rejeitados_log["internacional"] = rejeitados_log.get("internacional", 0) + 1
                continue

            preco = item.get("extracted_price")
            if preco is None:
                preco = parse_preco(item.get("price"), regiao_cfg["currency_format"])
            if preco is None or preco <= 0:
                print(f"[US-DBG] PRC '{_src}' | sem preço", flush=True)
                rejeitados_log["sem_preco"] += 1
                continue

            if custo:
                if preco < preco_min_aceitavel:
                    print(f"[US-DBG] OBX '{_src}' | {preco} < min {preco_min_aceitavel}", flush=True)
                    rejeitados_log["outlier_baixo"] += 1
                    continue
                if preco > preco_max_aceitavel:
                    print(f"[US-DBG] OAX '{_src}' | {preco} > max {preco_max_aceitavel}", flush=True)
                    rejeitados_log["outlier_alto"] += 1
                    continue

            # Link: a SerpAPI no engine `google_shopping` quase nunca devolve link directo
            # da loja em PT/UE. O campo `link` vem vazio. O `product_link` aponta para o
            # Google Shopping (`google.com/shopping/product/...` ou `google.pt/search?udm=28`),
            # não para a loja real.
            # Estratégia: aceitar apenas link directo da loja; se for Google ou vazio,
            # construir URL de busca na loja certa a partir do `source`.
            _raw_link = (item.get("link") or "").strip()
            _is_google_link = (
                not _raw_link
                or "google.com" in _raw_link.lower()
                or "google.pt" in _raw_link.lower()
                or "google.es" in _raw_link.lower()
                or "google.com.br" in _raw_link.lower()
                or "udm=28" in _raw_link.lower()
            )
            link_real = "" if _is_google_link else _raw_link

            if not link_real:
                _source_str = str(item.get("source", "")).strip()
                _src_low = _source_str.lower()
                _sku_str = str(sku).strip() if _valido(sku) else ""

                # === ESTRATÉGIA DE LINKS (Plano B com cache) ===
                # 1) Para LEGO+SKU: URL directa lego.com/pt-pt/product/<SKU> (testada)
                # 2) Senão: 2ª chamada SerpAPI (google_product) → URL real da loja, com cache 30 dias
                # 3) Fallback: mapping de URLs validadas manualmente para lojas comuns
                # 4) Sem link → será filtrado no painel

                if marca == "LEGO" and _sku_str and ("lego" in _src_low):
                    link_real = f"https://www.lego.com/pt-pt/product/{_sku_str}"
                else:
                    # PLANO B: tenta obter URL real via google_product API (com cache)
                    link_real = _link_real_da_loja(item, regiao_cfg, api_key)

                if not link_real:
                    # Fallback final: mapping validado manualmente para lojas comuns
                    if marca and _sku_str:
                        _termo_busca = f"{marca} {_sku_str}"
                    elif _sku_str:
                        _termo_busca = _sku_str
                    else:
                        _termo_busca = produto[:60]
                    _mapping_validado = {
                        "worten": "https://www.worten.pt/search?query={q}",
                        "continente": "https://www.continente.pt/pesquisa/?q={q}&start=0&srule=Continente&pmin=0.01",
                        "marcelo fonte": "https://universoencantado.com/?s={q}&post_type=product",
                        "universo encantado": "https://universoencantado.com/?s={q}&post_type=product",
                        "amazon.es": "https://www.amazon.es/s?k={q}",
                        "amazon.de": "https://www.amazon.de/s?k={q}",
                        "amazon.it": "https://www.amazon.it/s?k={q}",
                        "amazon.fr": "https://www.amazon.fr/s?k={q}",
                        "amazon.nl": "https://www.amazon.nl/s?k={q}",
                        "amazon.com.br": "https://www.amazon.com.br/s?k={q}",
                        "amazon": "https://www.amazon.com/s?k={q}",
                    }
                    for chave, tpl in _mapping_validado.items():
                        if chave in _src_low:
                            link_real = tpl.format(q=quote_plus(_termo_busca))
                            break

            registo = {
                "preco": float(preco),
                "loja": item.get("source", "Desconhecido"),
                "link": link_real,
                "rating": item.get("rating"),
                "reviews": item.get("reviews", 0) or 0,
                "tag": str(item.get("extensions", "")).lower() + " " + str(item).lower(),
                "titulo": item.get("title", ""),  # útil para mostrar no expander
                "_raw": {  # campos crus para debug — útil para identificar internacional
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "link": item.get("link", ""),
                    "extensions": item.get("extensions", ""),
                    "delivery": item.get("delivery", ""),
                    "badge": item.get("badge", ""),
                    "tag": item.get("tag", ""),
                    "snippet": item.get("snippet", ""),
                },
            }
            if relevancia == "forte":
                concorrentes.append(registo)

                # === EXPANSÃO: usar TODAS as stores do product_id como concorrentes ===
                # O `product_id` no Google Shopping agrupa todas as lojas que vendem o
                # mesmo produto. Já fizemos o _fetch_real_sellers acima (com cache),
                # agora vamos adicionar essas stores como concorrentes adicionais.
                # Resultado: 1 item original → 5-13 concorrentes (todos com link directo).
                _pid = item.get("product_id")
                _token = item.get("immersive_product_page_token", "")
                if _pid and _token:
                    _all_stores = _fetch_real_sellers(str(_pid), _token, regiao_cfg, api_key)
                    print(f"[US-EXP] inicio expansao pid={_pid} stores_devolvidas={len(_all_stores)} item_source={item.get('source','')}", flush=True)
                    _pids_ja_expandidos.add(str(_pid))  # registar para não duplicar no fim
                    for store in _all_stores:
                        store_link = store.get("link", "")
                        store_name = store.get("name", "")
                        if not store_link or not store_name:
                            continue
                        # Não duplicar a loja original (que já adicionámos como registo)
                        if store_name.lower().strip() == str(item.get("source", "")).lower().strip():
                            continue

                        # Aplicar os MESMOS filtros que aplicamos ao item original.
                        # As stores expandidas vêm de Plano B mas precisam passar pelos
                        # mesmos critérios — senão entra ruído (eBay blacklisted, produto
                        # usado, preços outlier, etc.)
                        # ATENÇÃO: a SerpAPI google_immersive_product não devolve um título
                        # específico por store — usamos o link da store como "pseudo-título"
                        # para filtros de coerência (palavras na URL revelam o tipo).
                        store_pseudo_title = (store_link + " " + item.get("title", "")).lower()
                        store_item_compat = {
                            "source": store_name,
                            "link": store_link,
                            "title": store_pseudo_title,
                            "extensions": store.get("shipping", ""),
                            "delivery": store.get("shipping", ""),
                        }

                        # Filtro 1: vendedor confiável (blacklist + whitelist)
                        if not vendedor_confiavel(store_item_compat, whitelist, blacklist):
                            print(f"[US-EXP] VEND '{store_name}' | {store_link[:80]}", flush=True)
                            continue

                        # Filtro 2: produto novo (rejeita "usado", "open box", "damaged", etc.)
                        if apenas_novos and not parece_produto_novo(store_item_compat):
                            print(f"[US-EXP] USD '{store_name}' | {store_link[:80]}", flush=True)
                            continue

                        # Filtro 3: coerência de tipo (acessório vs principal vs peça)
                        # Usa palavras-chave do link da store + título canónico
                        if not coerente_com_tipo(store_item_compat, tipo_procurado):
                            print(f"[US-EXP] TIPO '{store_name}' | {store_link[:80]} (proc={tipo_procurado})", flush=True)
                            continue

                        print(f"[US-EXP] ACEITO '{store_name}' | {store_link[:80]}", flush=True)

                        # Filtro 3: preço — heurística robusta para lidar com bug do BR.
                        # Problema: no Brasil a SerpAPI devolve VALOR DE PARCELA em `extracted_price`
                        # (ex: "12x de R$ 33,34") e o preço total real (com envio) em `extracted_total`.
                        # Estratégia: usar o MAIOR entre price e total (geralmente o total é o real),
                        # mas descontar envio quando explícito.
                        _ep = store.get("extracted_price") or 0
                        _et = store.get("extracted_total") or 0
                        store_preco = max(_ep, _et) if (_ep or _et) else None

                        # Se há envio explícito (formato "+ R$ 60,00"), descontar do total
                        # para chegar ao preço base do produto (mais útil para comparação)
                        _ship_str = str(store.get("shipping", ""))
                        if store_preco and "+" in _ship_str:
                            _ship_val = parse_preco(_ship_str.replace("+", "").strip(), regiao_cfg["currency_format"])
                            if _ship_val and _ship_val > 0 and store_preco - _ship_val > 0:
                                store_preco = store_preco - _ship_val

                        if store_preco is None or store_preco <= 0:
                            store_preco = parse_preco(store.get("total_str", "") or store.get("price_str", ""), regiao_cfg["currency_format"])
                        if store_preco is None or store_preco <= 0:
                            continue

                        # Filtro 4: outlier (mesmo que aplicamos ao original)
                        if custo:
                            if store_preco < preco_min_aceitavel or store_preco > preco_max_aceitavel:
                                continue

                        concorrentes.append({
                            "preco": float(store_preco),
                            "loja": store_name,
                            "link": store_link,
                            "rating": None,
                            "reviews": 0,
                            "tag": "",
                            "titulo": item.get("title", ""),  # herdamos o título do item canónico
                            "_raw": {
                                "title": "(expandido do product_id " + str(_pid) + ")",
                                "source": store_name,
                                "link": store_link,
                                "extensions": "",
                                "delivery": "",
                                "badge": "",
                                "tag": "",
                                "snippet": "",
                            },
                        })
            else:  # "fraco"
                concorrentes_similares.append(registo)

        # === EXPANSÃO DE PIDs RICOS ÓRFÃOS ===
        # Alguns product_ids têm muitas stores (>=5) mas o item original que aponta
        # para eles foi rejeitado. Vamos tentar expandir esses pids também — se a
        # maioria dos URLs contiver o SKU, é o produto certo.
        _sku_check = str(sku).strip().lower() if _valido(sku) else ""
        for _pid_orfao, _token_orfao in _pids_ricos_orfaos.items():
            if _pid_orfao in _pids_ja_expandidos:
                continue  # já foi expandido pelo item normal
            _all_stores_orfao = _fetch_real_sellers(_pid_orfao, _token_orfao, regiao_cfg, api_key)
            if len(_all_stores_orfao) < 2:
                # PID vazio ou só com 1 seller que já está no item original → pular
                continue

            # Validação: maioria dos URLs OU nomes-de-loja deve conter o SKU
            # (para garantir que este pid representa o produto certo, não outro canónico).
            # Aceitar match em URL OU em nome da loja porque URLs sluggificados muitas vezes
            # omitem o SKU (ex: "lego-pacote-de-expansao-de-ponte" sem incluir o número).
            #
            # Threshold adaptativo:
            # - PIDs ricos (≥5 sellers): 30% (mais permissivo, peso estatístico)
            # - PIDs pequenos (2-4 sellers): 50% (mais rigoroso, evita falsos positivos)
            if _sku_check and len(_sku_check) >= 4:
                _com_sku = sum(
                    1 for s in _all_stores_orfao
                    if (
                        _sku_check in str(s.get("link", "")).lower()
                        or _sku_check in str(s.get("name", "")).lower()
                    )
                )
                _pct_sku = _com_sku / len(_all_stores_orfao)
                _threshold = 0.30 if len(_all_stores_orfao) >= 5 else 0.50
                if _pct_sku < _threshold:
                    print(f"[US-ORFAO] skip pid={_pid_orfao} sku_match={_pct_sku:.0%} (req={_threshold:.0%}, stores={len(_all_stores_orfao)})", flush=True)
                    continue
                print(f"[US-ORFAO] expandindo pid={_pid_orfao} stores={len(_all_stores_orfao)} sku_match={_pct_sku:.0%}", flush=True)
            else:
                # Sem SKU para validar — só aceitar PIDs ricos (>=5 stores)
                if len(_all_stores_orfao) < 5:
                    continue
                print(f"[US-ORFAO] expandindo pid={_pid_orfao} stores={len(_all_stores_orfao)} (sem SKU para validar)", flush=True)

            # Adicionar as stores válidas como concorrentes fortes
            for store in _all_stores_orfao:
                store_link = store.get("link", "")
                store_name = store.get("name", "")
                if not store_link or not store_name:
                    continue

                store_pseudo_title = (store_link + " " + (produto or "")).lower()
                store_item_compat = {
                    "source": store_name,
                    "link": store_link,
                    "title": store_pseudo_title,
                    "extensions": store.get("shipping", ""),
                    "delivery": store.get("shipping", ""),
                }

                if not vendedor_confiavel(store_item_compat, whitelist, blacklist):
                    continue
                if apenas_novos and not parece_produto_novo(store_item_compat):
                    continue
                if not coerente_com_tipo(store_item_compat, tipo_procurado):
                    continue

                _ep = store.get("extracted_price") or 0
                _et = store.get("extracted_total") or 0
                store_preco = max(_ep, _et) if (_ep or _et) else None
                _ship_str = str(store.get("shipping", ""))
                if store_preco and "+" in _ship_str:
                    _ship_val = parse_preco(_ship_str.replace("+", "").strip(), regiao_cfg["currency_format"])
                    if _ship_val and _ship_val > 0 and store_preco - _ship_val > 0:
                        store_preco = store_preco - _ship_val
                if store_preco is None or store_preco <= 0:
                    continue
                if custo:
                    if store_preco < preco_min_aceitavel or store_preco > preco_max_aceitavel:
                        continue

                concorrentes.append({
                    "preco": float(store_preco),
                    "loja": store_name,
                    "link": store_link,
                    "rating": None,
                    "reviews": 0,
                    "tag": "",
                    "titulo": "(orfão do product_id " + _pid_orfao + ")",
                    "_raw": {
                        "title": "(órfão do product_id " + _pid_orfao + ")",
                        "source": store_name,
                        "link": store_link,
                        "extensions": "", "delivery": "", "badge": "", "tag": "", "snippet": "",
                    },
                })

        # Cascata: só pára quando tem ≥3 lojas DIFERENTES (entre fortes E similares).
        # Senão, tenta a próxima consulta — porque consultas curtas (SKU+marca)
        # às vezes devolvem só 1-2 lojas, mas o nome completo + EAN podem trazer mais.
        if concorrentes or concorrentes_similares:
            _lojas_unicas = {str(c.get("loja", "")).strip().lower() for c in (concorrentes + concorrentes_similares)}
            if len(_lojas_unicas) >= 3:
                break

        time.sleep(0.3)

    # Deduplicar — uma loja só pode aparecer numa lista (fortes têm prioridade).
    # Dentro de cada lista, manter o de MENOR preço por loja.
    # Normalização robusta: usa o DOMÍNIO do link (mais fiável que o nome,
    # porque a SerpAPI varia: "Mercari" vs "mercari.com" vs "eBay - vendor123").
    import unicodedata
    from urllib.parse import urlparse

    def _norm_loja(s):
        s = unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]", "", s)

    def _dominio_do_link(link):
        """Extrai o domínio base do link: 'https://mercari.com/us/item/...' → 'mercari.com'.
        Remove subdomínios comuns (www, m, store) para colapsar variantes."""
        if not link:
            return ""
        try:
            host = urlparse(str(link)).netloc.lower()
            # Remover prefixos comuns (www., m., store., shop.)
            for pref in ("www.", "m.", "store.", "shop.", "us.", "global."):
                if host.startswith(pref):
                    host = host[len(pref):]
            return host
        except Exception:
            return ""

    def _chave_loja(c):
        """Devolve uma chave canónica para deduplicação.
        Prefere domínio do link (mais fiável), com fallback ao nome normalizado."""
        dom = _dominio_do_link(c.get("link", ""))
        if dom:
            return dom
        return _norm_loja(c.get("loja", ""))

    def _dedup_por_loja(lista):
        melhor = {}
        for c in lista:
            chave = _chave_loja(c)
            if not chave:
                continue
            if chave not in melhor or c["preco"] < melhor[chave]["preco"]:
                melhor[chave] = c
        return sorted(melhor.values(), key=lambda x: x["preco"])

    concorrentes = _dedup_por_loja(concorrentes)
    concorrentes_similares = _dedup_por_loja(concorrentes_similares)

    # === Detecção de drift e movimentação para similares ===
    # Quando vários concorrentes existem, preços muito abaixo do P25 são
    # provavelmente drift (snapshot SerpAPI desactualizado) ou listings que escaparam
    # aos filtros. Mover para "similares" para que o utilizador confirme antes
    # de afectarem decisões de preço.
    #
    # Estratégia mais robusta: usar Q1 (quartil baixo) em vez de mediana, e
    # aplicar threshold sobre Q1. Isto evita penalizar preço justo de loja oficial
    # quando há outliers altos (revendedores caros) a puxar a mediana para cima.
    if len(concorrentes) >= 4:
        precos = sorted([c["preco"] for c in concorrentes if c.get("preco") and c["preco"] > 0])
        if precos:
            q1_idx = len(precos) // 4
            q1 = precos[q1_idx]  # 25º percentil
            threshold = q1 * 0.60  # 40% abaixo de Q1 = muito suspeito
            fortes_filtrados = []
            for c in concorrentes:
                if c["preco"] < threshold:
                    # Drift suspeito → mover para similares
                    concorrentes_similares.append(c)
                else:
                    fortes_filtrados.append(c)
            concorrentes = fortes_filtrados

    # Re-dedup similares depois de inserções
    concorrentes_similares = _dedup_por_loja(concorrentes_similares)

    # Se uma loja apareceu nas duas listas, removê-la dos similares (a forte ganha)
    lojas_fortes = {_chave_loja(c) for c in concorrentes}
    concorrentes_similares = [c for c in concorrentes_similares if _chave_loja(c) not in lojas_fortes]

    return concorrentes, rejeitados_log, concorrentes_similares


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

    # Margem competitiva: 0,5% abaixo do concorrente é suficiente para ficar
    # visualmente mais barato no comparador, sem desperdiçar margem.
    # (Antes era 2% — descia margem desnecessariamente)
    preco_competitivo = max(round(menor * 0.995, 2), preco_minimo)
    preco_otimo = max(round(segundo * 0.995, 2), preco_minimo)
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


def calcular_status(custo, imposto, markup, margem_minima, menor_concorrente):
    """Determina o status MARKUP do produto: o teu PREÇO ALVO (custo + markup ideal)
    face ao menor concorrente. Responde: "se eu vendesse ao preço ambicioso, ficaria competitivo?"

    Hierarquia de avaliação:
    1. Sem dados → ❔
    2. Concorrente abaixo do custo+imposto → 🟥 Burn (impossível competir sem prejuízo)
    3. Concorrente abaixo do PREÇO MÍNIMO (custo+imposto+margem mínima) → 🟧 Chão acima do mercado
       (consegue vender mas só com margem mínima, sem nunca alcançar o markup alvo)
    4. Markup alvo ≥ 5% acima do menor concorrente → ⚠️ Caro
    5. Markup alvo entre ±5% do menor → 🟡 Risco
    6. Markup alvo ≥ 5% abaixo do menor → ✅ Vencendo (folga real para escolher entre preços)

    NOTA: este é o status "ambição" — o status "ação real" usa `calcular_status_mercado`
    aplicado ao Preço Sugerido (que pode ser inferior ao Preço Calculado se houver pressão de mercado)."""
    if menor_concorrente is None:
        return "❔ Sem dados", "sem_dados"

    fator_imposto = 1 / (1 - imposto) if imposto < 1 else 1
    custo_com_imposto = custo * fator_imposto
    preco_minimo = custo * (1 + margem_minima) * fator_imposto
    preco_alvo = custo * (1 + markup) * fator_imposto

    # Concorrente abaixo do custo (após imposto): impossível sem prejuízo
    if menor_concorrente < custo_com_imposto:
        return "🟥 Burn", "burn"

    # Concorrente abaixo do nosso chão: vendemos com margem mínima mas nunca atingimos o markup
    # (este era o caso oculto que confundia o "Diff vs Mercado %")
    if menor_concorrente < preco_minimo:
        return "🟧 Chão acima do mercado", "chao_alto"

    diff_pct = (preco_alvo - menor_concorrente) / menor_concorrente
    if diff_pct <= -0.05:
        return "✅ Vencendo", "vencendo"
    if abs(diff_pct) < 0.05:
        return "🟡 Risco", "risco"
    return "⚠️ Caro", "caro"


def calcular_status_mercado(preco_sugerido, menor_concorrente):
    """Determina o status MERCADO: o teu PREÇO SUGERIDO (o que vais realmente praticar)
    face ao menor concorrente. Responde: "vou conseguir vender ao preço recomendado?"

    Útil porque o Preço Sugerido pode já estar ajustado para baixo (ex: mercado obrigou),
    e o utilizador quer saber se a ação real é competitiva.

    Regras:
    - Sem dados → ❔
    - Sugerido ≥ 5% abaixo do menor concorrente → ✅ Vencendo
    - Sugerido entre -5% e +0,5% do menor → 🟡 Risco (margem fina vs mercado)
    - Sugerido > +0,5% do menor → ⚠️ Caro (acima do mercado)
    """
    if menor_concorrente is None or preco_sugerido is None:
        return "❔ Sem dados", "sem_dados"
    if menor_concorrente <= 0 or preco_sugerido <= 0:
        return "❔ Sem dados", "sem_dados"

    diff_pct = (preco_sugerido - menor_concorrente) / menor_concorrente
    if diff_pct <= -0.05:
        return "✅ Vencendo", "vencendo"
    if diff_pct <= 0.005:
        return "🟡 Risco", "risco"
    return "⚠️ Caro", "caro"


def recomendacao_investimento(status_codigo, score_procura, qtde_atual):
    """Recomendação accionável para o decisor de compra.
    Importante: o decisor não pode renegociar com o fornecedor (preço fixo);
    só pode (a) ajustar margens, (b) comprar/não comprar, ou (c) liquidar stock."""
    if status_codigo == "burn":
        # Concorrente abaixo do nosso custo+imposto: não há nada a fazer
        return "❌ Não comprar"
    if status_codigo == "chao_alto":
        # Custo+margem mínima já está acima do mercado
        # Se a procura é alta, vale considerar reduzir margem mínima para conseguir vender
        if score_procura >= 60:
            return "📉 Reduzir margem mínima"
        return "❌ Não comprar"
    if status_codigo == "sem_dados":
        return "❔ Sem dados de mercado"
    if score_procura >= 60 and status_codigo in ("vencendo", "risco"):
        return "🚀 Investir / Repor estoque"
    if score_procura >= 60 and status_codigo == "caro":
        # Markup alvo acima do mercado mas conseguimos undercut com margem aceitável
        return "✅ Investir com margem reduzida"
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
# 6b. BARREIRA DE AUTENTICAÇÃO + HANDLERS DE OAUTH
# =============================================================================
# 1) Se viemos do callback Bling (?code=&state=ID|TOKEN, sem pkce_v), o `state`
#    contém o sid da sessão — extrair e restaurar ANTES de qualquer outra coisa
_qs_init = st.query_params
if "code" in _qs_init and "state" in _qs_init and "pkce_v" not in _qs_init:
    _state_init = _qs_init.get("state", "")
    if "|" in _state_init:
        _sid_from_state, _ = _state_init.split("|", 1)
        if _sid_from_state and "sid" not in _qs_init:
            st.query_params["sid"] = _sid_from_state

# 2) Tentar restaurar sessão de ?sid= na URL (sobrevive a navegações)
_restaurar_sessao_de_sid()

# 3) Tentar processar callback Google (caso utilizador acabe de autorizar)
_processar_token_url()

# 4) Se não está autenticado, mostrar página de login
if not utilizador_autenticado():
    renderizar_pagina_login()
    st.stop()

# 5) Já autenticado — processar callback Bling se aplicável (usa ?code= + ?state=)
_handle_bling_oauth_callback()

# 5b) Hidratar session_state com preferências persistidas (1ª vez, ou após login)
if "_prefs_loaded" not in st.session_state:
    _prefs = _carregar_preferencias_user()
    if _prefs:
        # Chave SerpAPI
        if _prefs.get("serpapi_key"):
            st.session_state["api_key"] = _prefs["serpapi_key"]
        # Termos aceites por região (vão directamente para o checkbox)
        if _prefs.get("termos_aceites_br"):
            st.session_state["aceite_🇧🇷 Brasil"] = True
        if _prefs.get("termos_aceites_pt"):
            st.session_state["aceite_🇵🇹 Portugal"] = True
        if _prefs.get("termos_aceites_us"):
            st.session_state["aceite_🇺🇸 USA"] = True
        # Origem dados (radio)
        if _prefs.get("origem_dados"):
            st.session_state["origem_dados_pref"] = _prefs["origem_dados"]
        # Região default
        if _prefs.get("regiao_default"):
            st.session_state["regiao_default_pref"] = _prefs["regiao_default"]
        # Âmbito PT/EU
        if _prefs.get("scope_pt"):
            st.session_state["scope_pt_pref"] = _prefs["scope_pt"]
        # Modo de análise (Bling): custo_margem ou preco_venda
        if _prefs.get("modo_analise_bling"):
            st.session_state["modo_analise_bling_pref"] = _prefs["modo_analise_bling"]
    st.session_state["_prefs_loaded"] = True


# 6) Se houve falha a criar sessão persistente, avisar utilizador (visível)
_sid_warn = st.session_state.get("_sid_init_warning")
if _sid_warn:
    col_warn1, col_warn2 = st.columns([5, 1])
    with col_warn1:
        st.warning(f"⚠️ {_sid_warn}")
    with col_warn2:
        if st.button("🔄 Tentar de novo", key="btn_retry_sid"):
            sess = st.session_state.get("user_session") or {}
            if sess:
                sid_retry = _criar_sessao_persistente(sess)
                if sid_retry:
                    st.query_params["sid"] = sid_retry
                    st.session_state.pop("_sid_init_warning", None)
                    st.session_state.pop("_sid_save_error", None)
                    st.rerun()


# =============================================================================
# 7. SIDEBAR
# =============================================================================
with st.sidebar:
    # CSS para subir o conteúdo da sidebar.
    # Estratégia: aplicar transform negativo OU margin negativa no contentor
    # principal, independente de qual selector apanha — pelo menos um vai funcionar.
    st.markdown("""
    <style>
        /* === REDUZIR PADDING TOPO DA SIDEBAR === */
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] > div,
        [data-testid="stSidebar"] > div > div,
        [data-testid="stSidebar"] section,
        [data-testid="stSidebar"] [data-testid="stSidebarContent"],
        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
        section[data-testid="stSidebar"] > div:first-child,
        aside[data-testid="stSidebar"] > div:first-child {
            padding-top: 0 !important;
        }

        /* === SUBIR CONTEÚDO POR DEFEITO ===
           Aplica margem negativa para puxar a Região para cima.
           As regras :has() abaixo desligam isto quando algum expander está aberto. */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"]:first-of-type {
            margin-top: -4rem !important;
        }

        /* === DESACTIVAR SUBIDA QUANDO EXPANDER ESTÁ ABERTO ===
           O Streamlit usa <details open> ou aria-expanded="true" em variantes
           diferentes. Cobrimos os dois casos. */
        [data-testid="stSidebar"]:has(details[open])
            [data-testid="stVerticalBlock"]:first-of-type,
        [data-testid="stSidebar"]:has([aria-expanded="true"])
            [data-testid="stVerticalBlock"]:first-of-type,
        [data-testid="stSidebar"]:has([data-testid="stExpander"] > details[open])
            [data-testid="stVerticalBlock"]:first-of-type {
            margin-top: 0 !important;
        }

        /* === COMPACTAR CONTEÚDO === */
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            margin-top: 0.1rem !important;
            margin-bottom: 0.1rem !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
            font-size: 1.05rem !important;
            line-height: 1.2 !important;
        }
        [data-testid="stSidebar"] hr {
            margin-top: 0.3rem !important;
            margin-bottom: 0.3rem !important;
        }
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] [data-testid="stMarkdown"],
        [data-testid="stSidebar"] [data-testid="element-container"] {
            margin-bottom: 0.2rem !important;
        }
        [data-testid="stSidebar"] .stSelectbox,
        [data-testid="stSidebar"] .stTextInput,
        [data-testid="stSidebar"] .stRadio,
        [data-testid="stSidebar"] .stButton {
            margin-bottom: 0.3rem !important;
        }
    </style>
    """, unsafe_allow_html=True)

    st.header("🌎 Região")
    # Persistência: usa última região guardada como default
    _opcoes_pais = list(idiomas.keys())
    _pais_pref = st.session_state.get("regiao_default_pref")
    # Se a pref começa por "Portugal" ou contém "União Europeia", encontra opção certa
    _pais_default_idx = 0
    if _pais_pref:
        for i, k in enumerate(_opcoes_pais):
            if _pais_pref in k or k in _pais_pref:
                _pais_default_idx = i
                break

    pais_sel = st.selectbox(
        "Selecione:",
        _opcoes_pais,
        index=_pais_default_idx,
        key="pais_main",
    )

    if st.session_state.pais_anterior != pais_sel:
        st.session_state.df_final = None
        st.session_state.pop("_df_base_carregado", None)  # Reset catálogo ao mudar região
        st.session_state.pais_anterior = pais_sel
        # Guarda preferência (1 chamada Supabase só quando muda mesmo)
        if pais_sel != _pais_pref:
            _guardar_preferencia("regiao_default", pais_sel)
            st.session_state["regiao_default_pref"] = pais_sel

    t = idiomas[pais_sel]

    # Portugal busca sempre em toda a União Europeia (sem cobrança de IVA adicional
    # entre países da UE — faz sentido o utilizador ver opções de compra em PT/ES/DE/IT/FR/NL).
    # `scope_pt` mantido por compatibilidade com a BD, mas fixo em "União Europeia".
    scope_pt = "União Europeia"

    # Calcular regiao_id globalmente (usado em várias secções fora do botão Analisar)
    if "Brasil" in pais_sel:
        regiao_id = "BR"
    elif "Portugal" in pais_sel:
        regiao_id = "EU"
    else:
        regiao_id = "US"

    # Aviso para utilizadores da região US: ainda em fase experimental
    if regiao_id == "US":
        st.warning(
            "⚠️ **US market is experimental.** Some products (especially electronics "
            "and accessories) may return fewer competitors than expected due to how "
            "Google Shopping fragments product listings in the US market. "
            "Results for LEGO and physical products work well. "
            "Brazil and EU markets are fully supported.",
            icon="🧪",
        )

    st.divider()
    st.header("🔑 Chave API")
    api_key_input = st.text_input(t["label_chave"], type="password", value=st.session_state.api_key or "")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input.strip() or None
        if st.session_state.api_key:
            _guardar_preferencia("serpapi_key", st.session_state.api_key)
            st.success("Chave ativada e guardada!")
            # Forçar refresh do contador
            obter_creditos_serpapi.clear()
        else:
            _guardar_preferencia("serpapi_key", None)
            st.error("Chave vazia.")

    # ---------- Contador discreto de buscas restantes SerpAPI ----------
    if st.session_state.api_key:
        creditos = obter_creditos_serpapi(st.session_state.api_key)
        if creditos is not None:
            left = creditos["searches_left"]
            # Emoji muda conforme estado, mas tudo sempre como caption (uma linha)
            if left <= 0:
                st.caption(f"🔴 **0 buscas restantes** — chave esgotada")
            elif left < 25:
                st.caption(f"🟠 **{left}** buscas restantes")
            elif left < 75:
                st.caption(f"🟡 {left} buscas restantes")
            else:
                st.caption(f"🟢 {left} buscas restantes")

    st.divider()
    # Status do Supabase + Bling
    if supabase_ativo():
        st.success("📚 Histórico ativo (Supabase)")
    else:
        st.info("📚 Histórico desativado\n(configure SUPABASE_URL/KEY)")
    if bling_credenciais_disponiveis():
        if bling_conectado():
            st.caption("🛒 Bling conectado")
        else:
            st.caption("🛒 Bling pronto para conectar")
    else:
        st.caption("🛒 Bling não configurado")

    st.divider()
    st.markdown("""
    <div style='font-size: 0.85rem;'>
    <b>Status</b><br>
    ✅ Vencendo &nbsp; 🟡 Risco<br>
    ⚠️ Caro &nbsp; 🟧 Chão acima<br>
    🟥 Burn<br><br>
    <b>Procura</b><br>
    🔥 Muito Alta &nbsp; 📈 Alta<br>
    ➡️ Média &nbsp; 📉 Baixa<br><br>
    <b>Atratividade</b> = Procura × Margem ÷ 100
    </div>
    """, unsafe_allow_html=True)

    st.divider()
    with st.expander("✉️ Suporte"):
        with st.form("suporte_form", clear_on_submit=True):
            sn = st.text_input("Nome")
            se = st.text_input("Email")
            sm = st.text_area("Mensagem")
            if st.form_submit_button("Enviar"):
                if sm.strip() and enviar_email_log(sn, se, sm):
                    st.success("✅ Enviado")
                else:
                    st.error("❌ Falha no envio ou mensagem vazia")

    # Info do utilizador logado + botão logout — no fundo da sidebar
    # Espaço extra para compensar a margem negativa global da sidebar
    st.markdown("<div style='margin-top: 2.5rem;'></div>", unsafe_allow_html=True)
    st.divider()
    email = user_email_actual() or "(sem email)"
    nome = user_nome_actual() or email
    avatar = user_avatar_actual()

    col_av, col_logout = st.columns([3, 1])
    with col_av:
        if avatar:
            st.markdown(
                f"<img src='{avatar}' width='28' style='border-radius:50%;vertical-align:middle;'/> "
                f"<span style='font-size:0.85rem;'>{nome}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption(f"👤 {nome}")
    with col_logout:
        if st.button("Sair", key="btn_logout", help="Terminar sessão"):
            fazer_logout()
            st.rerun()


# =============================================================================
# 8. CORPO PRINCIPAL — ABAS
# =============================================================================
st.title(t["titulo"])

# Card discreto de ajuda — sempre acessível, opcional
# Tutoriais por idioma: BR (pt-BR), PT/EU (pt-PT), US (en)
TUTORIAL_PT_BR = """
**Como usar esta aplicação**

1. **Aceite os Termos de Uso** (logo abaixo deste tutorial)
2. **Insira a sua chave SerpAPI** na barra lateral (veja como obter mais abaixo)
3. **Escolha a origem dos dados:**
   - 📁 **Planilha** — carregue um Excel/CSV com os seus produtos (custo, EAN/SKU, etc.)
   - 🛒 **Bling** — se já tem catálogo no Bling V3, conecte e importe directamente (apenas Brasil)
4. **Para Bling, escolha o modo de análise:**
   - 💰 **Custo + margem** — calcula markup ideal a partir do custo (precisa preço de custo no Bling)
   - 🎯 **Preço de venda actual** — compara o seu preço de venda actual com o mercado (apenas precisa preço de venda)
5. **Seleccione os produtos** que quer analisar (cada análise consome 1 chamada SerpAPI)
6. **Configure** markup, imposto e margem mínima nos parâmetros
7. **Iniciar Análise** — a app pesquisa cada produto no Google Shopping e compara com concorrentes confiáveis

---

**🔑 Como obter chave SerpAPI**

1. Crie conta em [serpapi.com](https://serpapi.com) (plano gratuito: 100 buscas/mês)
2. No painel verá a sua **API Key** — copie
3. Cole na barra lateral e clique **Confirmar Chave**

⚠️ **Cada produto consome 1-3 buscas** (tentamos EAN → SKU → nome). Para 90 produtos pode consumir até ~270 buscas. No plano gratuito cabem ~30 produtos por mês.

---

**🛒 Como conectar o Bling (Brasil — ~30 min)**

> ⚠️ Requer plano **Bling Cobrança** ou superior (o plano gratuito do Bling não dá acesso ao painel de developers).

**Passo 1 — Aceder ao painel de developers do Bling**

1. Aceda a [developer.bling.com.br](https://developer.bling.com.br) e faça login com a sua conta Bling
2. Se for a primeira vez, o Bling pode pedir para activar o painel — siga as instruções no ecrã

**Passo 2 — Criar uma aplicação**

1. Clique em **Criar aplicativo** (ou **Nova aplicação**)
2. Preencha:
   - **Nome:** "Análise de Preços VemBrincar" (ou outro à sua escolha)
   - **Descrição:** "Análise de preços e concorrência"
   - **Categoria:** Privado (uso próprio)
   - **Link da política de privacidade:** (pode usar a URL desta app)
3. Em **Redirect URI**, cole **exactamente**:

   ```
   https://vembrincarcomagente-viabilidadedevendas.hf.space/
   ```

   *(importante: incluir a barra `/` no final)*

4. Em **Escopos**, marque apenas:
   - ✅ Produtos (Leitura e Escrita) — para ler catálogo e actualizar preços
   - ✅ Estoque (Leitura) — para saber quais produtos têm stock
5. Clique em **Salvar**

**Passo 3 — Copiar credenciais**

1. Após criar a aplicação, o Bling mostra **Client ID** e **Client Secret**
2. **Copie ambos para um sítio seguro** (o Client Secret só é mostrado uma vez)

**Passo 4 — Autorizar nesta app**

1. Volte a esta aplicação
2. Em **Fonte de dados**, escolha **🛒 Bling**
3. Clique em **🔐 Autorizar no Bling**
4. Será redireccionado para o Bling, faça login se necessário
5. Aceite as permissões da aplicação
6. Será redireccionado de volta — verá **"✅ Bling conectado"** na barra lateral

**Passo 5 — Importar catálogo**

1. Marque ou desmarque **"📦 Apenas produtos com stock positivo"** conforme preferir
2. Clique em **📥 Importar catálogo do Bling**
3. Pode demorar 1-3 minutos consoante o tamanho do catálogo

Os tokens ficam guardados — **só precisa autorizar uma vez** (até desconectar manualmente).

---

**🎯 Selecionar produtos antes da análise**

Após carregar o catálogo, aparece uma tabela onde pode:
- **Marcar/desmarcar** quais produtos analisar (use o checkbox geral ou marque um a um)
- **Editar o custo** (ou preço de venda, conforme o modo) directamente na tabela
- **Recarregar** o catálogo com **🔄 Reimportar**

> 💡 Cada produto seleccionado consome 1 chamada SerpAPI. Seleccione apenas os que precisam de análise.

---

**📤 Actualizar preços no Bling (após análise)**

Após a análise, no fim da página aparece uma secção para **enviar os preços sugeridos de volta ao Bling**:

1. Reveja os preços sugeridos (pode editar manualmente)
2. Marque os produtos que quer actualizar
3. Clique em **📤 Enviar preços para o Bling**
4. A app confirma quais foram actualizados com sucesso

---

**❓ Significado dos sinais**

**Status (modo Custo + margem):**
- ✅ **Vencendo** — markup alvo já está abaixo do menor concorrente (folga real)
- 🟡 **Risco** — preço quase igual ao concorrente
- ⚠️ **Caro** — markup acima do mercado, perde vendas
- 🟧 **Chão acima do mercado** — custo + margem mínima já está acima do mercado (não há como competir sem renegociar fornecedor)
- 🟥 **Burn** — concorrente abaixo do seu custo + imposto

**Status (modo Preço de venda actual):**
- ✅ **Vencendo** — preço actual ≤ menor concorrente
- 🟡 **Risco** — 0-5% acima do menor concorrente
- ⚠️ **Caro** — mais de 5% acima do menor concorrente

**Procura:** 🔥 Muito Alta · 📈 Alta · ➡️ Média · 📉 Baixa

**Atratividade:** índice 0-100 — use para priorizar quais produtos focar/comprar.

**Recomendação:** 🚀 Investir/Repor · ✅ Manter · 📉 Reduzir margem · 🔻 Liquidar · ⏸️ Aguardar · ❌ Não comprar

---

**ℹ️ Sobre precisão dos preços**

Os preços de concorrentes vêm do **Google Shopping** (via SerpAPI). Podem ter **1-5% de diferença** face ao preço actual na loja, devido a:
- Latência entre o Google e a loja
- Variações no mesmo listing (com/sem cupão, à vista/parcelado)

Use os valores como **referência estratégica**. Antes de mudar preço, confirme o preço actual clicando no link do concorrente.
"""

TUTORIAL_PT_PT = """
**Como utilizar esta aplicação**

1. **Aceite os Termos de Utilização** (logo abaixo deste tutorial)
2. **Introduza a sua chave SerpAPI** na barra lateral (veja como obter mais abaixo)
3. **Escolha a origem dos dados:**
   - 📁 **Folha de cálculo** — carregue um Excel/CSV com os seus produtos (custo, EAN/SKU, etc.)
4. **Seleccione os produtos** que quer analisar (cada análise consome 1 chamada SerpAPI)
5. **Configure** markup, imposto e margem mínima nos parâmetros
6. **Iniciar Análise** — a aplicação pesquisa cada produto no Google Shopping e compara com concorrentes da região

---

**🔑 Como obter chave SerpAPI**

1. Crie conta em [serpapi.com](https://serpapi.com) (plano gratuito: 100 pesquisas/mês)
2. No painel verá a sua **API Key** — copie
3. Cole na barra lateral e clique em **Confirmar Chave**

⚠️ **Cada produto consome 1-3 pesquisas** (tentamos EAN → SKU → nome). Para 90 produtos pode consumir até ~270 pesquisas.

---

**🎯 Seleccionar produtos antes da análise**

Após carregar o catálogo, aparece uma tabela onde pode:
- **Marcar/desmarcar** quais produtos analisar
- **Editar o custo** directamente na tabela
- **Recarregar** o catálogo com **🔄 Reimportar**

> 💡 Cada produto seleccionado consome 1 chamada SerpAPI.

---

**❓ Significado dos sinais**

**Status:**
- ✅ **A vencer** — markup alvo já está abaixo do menor concorrente
- 🟡 **Risco** — preço quase igual ao concorrente
- ⚠️ **Caro** — markup acima do mercado
- 🟧 **Chão acima do mercado** — custo + margem mínima já está acima do mercado
- 🟥 **Burn** — concorrente abaixo do seu custo + imposto

**Procura:** 🔥 Muito Alta · 📈 Alta · ➡️ Média · 📉 Baixa

**Atratividade:** índice 0-100 — use para priorizar produtos.

**Recomendação:** 🚀 Investir · ✅ Manter · 📉 Reduzir margem · 🔻 Liquidar · ⏸️ Aguardar · ❌ Não comprar

---

**ℹ️ Sobre precisão dos preços**

Os preços de concorrentes vêm do **Google Shopping** (via SerpAPI). Podem ter **1-5% de diferença** face ao preço actual na loja. Use como **referência estratégica** — antes de alterar preço, confirme clicando no link do concorrente.
"""

TUTORIAL_EN = """
**How to use this application**

1. **Accept the Terms of Use** (below this tutorial)
2. **Enter your SerpAPI key** in the sidebar (see how to get one below)
3. **Choose data source:**
   - 📁 **Spreadsheet** — upload an Excel/CSV with your products (cost, EAN/SKU, etc.)
4. **Select products** to analyze (each analysis consumes 1 SerpAPI call)
5. **Configure** markup, tax and minimum margin in parameters
6. **Start Analysis** — the app searches each product on Google Shopping and compares with trusted competitors

---

**🔑 How to get a SerpAPI key**

1. Create an account at [serpapi.com](https://serpapi.com) (free plan: 100 searches/month)
2. On the dashboard, you'll see your **API Key** — copy it
3. Paste it in the sidebar and click **Confirm Key**

⚠️ **Each product consumes 1-3 searches** (we try EAN → SKU → name). For 90 products this may use up to ~270 searches.

---

**🎯 Select products before analysis**

After loading the catalog, a table appears where you can:
- **Check/uncheck** which products to analyze
- **Edit the cost** directly in the table
- **Reload** the catalog with **🔄 Reimport**

> 💡 Each selected product consumes 1 SerpAPI call.

---

**❓ Signal meanings**

**Status:**
- ✅ **Winning** — target markup is already below the lowest competitor
- 🟡 **At risk** — price nearly equal to competitor
- ⚠️ **Expensive** — markup above market
- 🟧 **Floor above market** — cost + minimum margin is already above market
- 🟥 **Burn** — competitor below your cost + tax

**Demand:** 🔥 Very High · 📈 High · ➡️ Medium · 📉 Low

**Attractiveness:** 0-100 index — use to prioritize products.

**Recommendation:** 🚀 Invest · ✅ Hold · 📉 Reduce margin · 🔻 Liquidate · ⏸️ Wait · ❌ Don't buy

---

**ℹ️ About price accuracy**

Competitor prices come from **Google Shopping** (via SerpAPI). They may differ by **1-5%** from the current price in the store. Use as a **strategic reference** — before changing prices, confirm by clicking the competitor link.
"""

# Selecionar tutorial conforme região
if "Brasil" in pais_sel:
    _tutorial_label = "📚 Primeira vez aqui? Ver tutorial rápido"
    _tutorial_md = TUTORIAL_PT_BR
elif "Portugal" in pais_sel:
    _tutorial_label = "📚 Primeira vez aqui? Ver tutorial rápido"
    _tutorial_md = TUTORIAL_PT_PT
else:
    _tutorial_label = "📚 First time here? Quick tutorial"
    _tutorial_md = TUTORIAL_EN

with st.expander(_tutorial_label, expanded=False):
    st.markdown(_tutorial_md)


st.subheader("📋 Termos de Uso")
aceite_regiao = st.checkbox(t["termos_check"], key=f"aceite_{pais_sel}")
if aceite_regiao:
    # Persistir aceitação para esta região (uma vez aceite, fica para sempre)
    pais_para_campo = {
        "🇧🇷 Brasil": "termos_aceites_br",
        "🇵🇹 Portugal": "termos_aceites_pt",
        "🇺🇸 USA": "termos_aceites_us",
    }
    campo_db = pais_para_campo.get(pais_sel)
    # Só guarda se ainda não guardado nesta sessão (evita upsert a cada rerun)
    flag_session = f"_termo_guardado_{pais_sel}"
    if campo_db and not st.session_state.get(flag_session):
        _guardar_preferencia(campo_db, True)
        st.session_state[flag_session] = True
else:
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

        # Origem persistida em user_preferences — restaura escolha anterior
        opcoes_fonte = ["Planilha", "Bling (API V3)"] if "Brasil" in pais_sel else ["Planilha"]
        origem_pref = st.session_state.get("origem_dados_pref", "Planilha")
        index_default = opcoes_fonte.index(origem_pref) if origem_pref in opcoes_fonte else 0

        fonte = st.radio(
            "Fonte de dados:",
            opcoes_fonte,
            index=index_default,
            horizontal=True,
            key="fonte_radio",
        )
        # Guardar mudança (apenas se diferente do que está em BD)
        if fonte != origem_pref:
            _guardar_preferencia("origem_dados", fonte)
            st.session_state["origem_dados_pref"] = fonte
            st.session_state.pop("_df_base_carregado", None)  # Reset catálogo ao mudar fonte

        # Modo de análise: só aplicável a Bling (planilha mantém comportamento clássico)
        modo_analise = "custo_margem"  # default seguro para planilha + outras regiões
        if "Bling" in fonte:
            modos = {
                "💰 Custo + margem (clássico)": "custo_margem",
                "🎯 Preço de venda actual (compara com mercado)": "preco_venda",
            }
            modo_pref = st.session_state.get("modo_analise_bling_pref", "custo_margem")
            chave_default = next(
                (k for k, v in modos.items() if v == modo_pref), list(modos.keys())[0]
            )
            modo_escolhido = st.radio(
                "🧮 Modo de análise:",
                list(modos.keys()),
                index=list(modos.keys()).index(chave_default),
                horizontal=False,
                key="modo_analise_radio",
                help=(
                    "**Custo + margem**: usa o preço de custo do Bling e calcula margem real, markup, etc. "
                    "Útil se quer ver lucratividade.\n\n"
                    "**Preço de venda actual**: compara o preço de venda actual no Bling com o mercado. "
                    "Útil se quer ajustar preços para vencer concorrência."
                ),
            )
            modo_analise = modos[modo_escolhido]
            if modo_analise != modo_pref:
                _guardar_preferencia("modo_analise_bling", modo_analise)
                st.session_state["modo_analise_bling_pref"] = modo_analise
                st.session_state.pop("_df_base_carregado", None)  # Reset ao mudar modo

        # df_base é persistido em session_state após importação Bling ou upload de planilha.
        # Isto evita que o df se perca quando o user interage com selector (rerun).
        df_base = st.session_state.get("_df_base_carregado", pd.DataFrame())

        if "Bling" in fonte:
            if not bling_credenciais_disponiveis():
                st.error(
                    "🔌 **Bling não configurado.**\n\n"
                    "Adicione `BLING_CLIENT_ID` e `BLING_CLIENT_SECRET` aos Secrets do Streamlit Cloud "
                    "(estes valores são gerados ao criar uma 'Aplicação' no painel de developers do Bling)."
                )
            elif not supabase_ativo():
                st.error(
                    "📚 **Supabase necessário.** A integração Bling guarda os tokens de autenticação no "
                    "Supabase para não exigir nova autorização a cada sessão. Configure SUPABASE_URL/KEY primeiro."
                )
            elif not bling_conectado():
                # Ainda não há token válido — mostrar botão de autorização
                st.info(
                    "Para importar produtos do Bling, autorize a aplicação acima a aceder ao seu catálogo. "
                    "Vai ser redirecionado para o Bling, onde tem de fazer login e clicar em **Autorizar**. "
                    "Depois volta aqui automaticamente."
                )
                url_auth = bling_iniciar_autorizacao()

                if not url_auth or not url_auth.startswith("https://"):
                    st.error(
                        f"⚠️ Não foi possível gerar URL de autorização Bling. "
                        f"Verifique os secrets `BLING_CLIENT_ID` e `BLING_CLIENT_SECRET`. "
                        f"URL gerada: `{url_auth!r}`"
                    )
                else:
                    # target="_top" navega na mesma janela. A sessão Google é
                    # persistida via cookie encriptado, então sobrevive a esta
                    # navegação e ao callback Bling sem precisar de re-login.
                    st.markdown(
                        f"""
                        <a href="{url_auth}" target="_top" style="
                            display: inline-block;
                            padding: 0.5rem 1.2rem;
                            background-color: #FF4B4B;
                            color: white;
                            text-decoration: none;
                            border-radius: 0.5rem;
                            font-size: 0.95rem;
                            border: 1px solid #FF4B4B;
                            font-weight: 500;
                        ">🔐 Autorizar no Bling</a>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                # Conectado — mostrar status e botão para importar
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.success("✅ Bling conectado.")
                with col_b:
                    if st.button("🚪 Desconectar", help="Apagar tokens e exigir nova autorização"):
                        bling_desconectar()
                        st.rerun()

                apenas_stock = st.checkbox(
                    "📦 Apenas produtos com stock positivo",
                    value=True,
                    help="Ignora produtos com stock zero (mais rápido e foca em produtos vendáveis).",
                )

                if st.button("📥 Importar catálogo do Bling", type="primary"):
                    progresso = st.progress(0.0, text="A importar produtos...")
                    contador = st.empty()

                    def _cb(pagina, total):
                        # Estimativa visual: cada página são 100 produtos; cap de 50 páginas
                        pct = min(pagina / 50.0, 1.0)
                        progresso.progress(pct, text=f"Página {pagina} ({total} produtos)")
                        contador.caption(f"Recebidos {total} produtos até agora...")

                    produtos = bling_importar_catalogo(progresso_cb=_cb, apenas_com_stock=apenas_stock)
                    progresso.empty()
                    contador.empty()

                    if not produtos:
                        msg_extra = " (com filtro de stock activo)" if apenas_stock else ""
                        st.error(f"Nenhum produto retornado{msg_extra}. Verifique no Bling.")
                    else:
                        def _extrair_custo(p):
                            """Tenta vários campos do Bling V3 para encontrar o custo."""
                            for chave in ("precoCusto", "preco_custo", "custo"):
                                v = p.get(chave)
                                if v:
                                    try:
                                        f = float(v)
                                        if f > 0:
                                            return round(f, 2)
                                    except (TypeError, ValueError):
                                        pass
                            return 0.0

                        def _extrair_qtde(p):
                            est = p.get("estoque")
                            if isinstance(est, dict):
                                v = est.get("saldoVirtualTotal") or est.get("quantidade") or est.get("disponivel")
                                try:
                                    return max(float(v or 0), 1.0)
                                except (TypeError, ValueError):
                                    return 1.0
                            try:
                                return max(float(est or 0), 1.0) if est else 1.0
                            except (TypeError, ValueError):
                                return 1.0

                        df_base = pd.DataFrame([{
                            "Nome": i.get("nome", ""),
                            "Custo": _extrair_custo(i),
                            "Preço Venda Bling": float(i.get("preco", 0) or 0),
                            "Qtde": _extrair_qtde(i),
                            "EAN": i.get("codigoBarra", ""),
                            "SKU": i.get("codigo", ""),
                            "Linha": (i.get("categoria") or {}).get("nome", "Geral"),
                            "ID": i.get("id", 0),
                        } for i in produtos])
                        df_base["Custo"] = pd.to_numeric(df_base["Custo"], errors="coerce").fillna(0.0)
                        df_base["Preço Venda Bling"] = pd.to_numeric(
                            df_base["Preço Venda Bling"], errors="coerce"
                        ).fillna(0.0)

                        # Persistir em session_state para sobreviver a reruns do selector
                        st.session_state["_df_base_carregado"] = df_base.copy()

                        st.success(f"✅ {len(df_base)} produtos importados do Bling.")

                        # Warning condicional ao modo escolhido
                        if modo_analise == "preco_venda":
                            n_sem_preco_venda = int((df_base["Preço Venda Bling"] <= 0).sum())
                            if n_sem_preco_venda > 0:
                                st.warning(
                                    f"⚠️ **{n_sem_preco_venda} produto(s) sem preço de venda no Bling.** "
                                    f"Edite a coluna 'Preço Venda Bling' no selector abaixo para os analisar. "
                                    f"Produtos sem preço de venda serão automaticamente desmarcados."
                                )
                        else:
                            n_sem_custo = int((df_base["Custo"] <= 0).sum())
                            if n_sem_custo > 0:
                                st.warning(
                                    f"⚠️ **{n_sem_custo} produto(s) sem custo registado no Bling.** "
                                    f"Edite a coluna 'Custo' no selector abaixo para os analisar. "
                                    f"Produtos com custo zero serão automaticamente desmarcados."
                                )
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
                idx_m = identificar_coluna(cols, ["marca", "brand", "fabricante", "manufacturer"])

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

                # Marca: coluna opcional, melhora precisão para marcas que a app não detecta automaticamente
                opcoes_m = ["(Detectar automaticamente do nome)"] + cols
                col_m = st.selectbox(
                    "MARCA (opcional):",
                    opcoes_m,
                    index=(idx_m + 1) if idx_m >= 0 else 0,
                    help="Se preencher, a app usa esta marca em vez de tentar detectar do nome. "
                         "Útil quando vende várias marcas (LEGO, Playmobil, Pampers, etc.) "
                         "ou marcas pouco conhecidas. Se não preencher, a app deteta automaticamente.",
                )

                st.caption(
                    "💡 **SKU/REF** é o código do fabricante (ex: LEGO `10281`, Playmobil `70980`). "
                    "Quando preenchido, melhora muito a precisão da busca em mercados estrangeiros, "
                    "porque o nome muda entre idiomas mas o SKU é universal."
                )

                df_base = df_raw.copy().rename(columns={col_n: "Nome", col_c: "Custo", col_q: "Qtde"})
                df_base["EAN"] = df_raw[col_e] if col_e != "(Sem EAN)" else ""
                df_base["SKU"] = df_raw[col_s].astype(str) if col_s != "(Sem SKU)" else ""
                df_base["Linha"] = df_raw[col_l] if col_l != "(Sem categoria)" else "Geral"
                df_base["Marca"] = df_raw[col_m].astype(str) if col_m != "(Detectar automaticamente do nome)" else ""
                df_base["ID"] = 0

                df_base["Custo"] = limpar_custo(df_base["Custo"])
                df_base["Qtde"] = pd.to_numeric(df_base["Qtde"], errors="coerce").fillna(0)
                n_invalid = df_base["Custo"].isna().sum()
                df_base = df_base.dropna(subset=["Custo"])
                df_base = df_base[df_base["Custo"] > 0]
                if n_invalid > 0:
                    st.warning(f"⚠️ {n_invalid} linhas removidas (custo inválido ou zero).")

                # Persistir em session_state para sobreviver a reruns do selector
                st.session_state["_df_base_carregado"] = df_base.copy()

        # ------ Parâmetros + execução ------
        if not df_base.empty:
            st.divider()
            col_hdr1, col_hdr2 = st.columns([5, 1])
            with col_hdr1:
                st.header("🎯 Seleção de Produtos")
            with col_hdr2:
                if st.button("🔄 Reimportar", help="Voltar à tela de importação para recarregar o catálogo do zero"):
                    st.session_state.pop("_df_base_carregado", None)
                    st.rerun()

            st.caption(
                f"📦 **{len(df_base)} produtos carregados.** Selecione abaixo quais quer analisar. "
                "Cada produto consome 1 chamada SerpAPI — selecione apenas os que precisam de análise para economizar créditos."
            )

            # Coluna pivô para o modo escolhido
            coluna_pivot = "Preço Venda Bling" if modo_analise == "preco_venda" else "Custo"
            label_pivot = "Preço de venda" if modo_analise == "preco_venda" else "Custo"

            # DataFrame com coluna 'Analisar' (default: True para quem tem valor pivot > 0)
            df_seleccao = df_base.copy()
            # Garantir que a coluna pivot existe (planilha não traz "Preço Venda Bling")
            if coluna_pivot not in df_seleccao.columns:
                df_seleccao[coluna_pivot] = 0.0
            df_seleccao.insert(0, "Analisar", df_seleccao[coluna_pivot] > 0)

            colunas_visiveis = ["Analisar", "Nome", coluna_pivot, "Qtde"]
            if "SKU" in df_seleccao.columns:
                colunas_visiveis.insert(2, "SKU")

            # Checkbox master: marca/desmarca todos de uma vez
            marcar_todos = st.checkbox(
                f"🔘 Selecionar todos (com {label_pivot.lower()} > 0)",
                value=True,
                key="sel_todos_check",
                help=f"Quando activo, todos os produtos com {label_pivot.lower()} > 0 ficam marcados para análise. "
                     "Desactive para desmarcar todos. Depois pode marcar/desmarcar individualmente na tabela.",
            )
            df_seleccao["Analisar"] = (df_seleccao[coluna_pivot] > 0) if marcar_todos else False

            col_config = {
                "Analisar": st.column_config.CheckboxColumn(
                    "Analisar?", width="small", default=True,
                ),
                "Nome": st.column_config.TextColumn("Produto", disabled=True),
                coluna_pivot: st.column_config.NumberColumn(
                    label_pivot,
                    format=f"{t['moeda']} %.2f",
                    min_value=0.0,
                    help=f"Edite se o Bling não trouxe esse valor. {label_pivot} 0 desactiva análise.",
                ),
                "Qtde": st.column_config.NumberColumn("Stock", disabled=True, width="small"),
            }
            if "SKU" in colunas_visiveis:
                col_config["SKU"] = st.column_config.TextColumn("SKU", disabled=True, width="small")

            df_seleccao_editada = st.data_editor(
                df_seleccao[colunas_visiveis],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                column_config=col_config,
                key="produto_selector",
            )

            # Filtrar: só seleccionados E com valor pivot > 0
            mask = df_seleccao_editada["Analisar"] & (df_seleccao_editada[coluna_pivot] > 0)
            indices_seleccionados = df_seleccao_editada[mask].index
            # Aplicar valores editados ao df_base original
            df_base_filtrado = df_base.loc[indices_seleccionados].copy().reset_index(drop=True)
            df_base_filtrado[coluna_pivot] = df_seleccao_editada.loc[indices_seleccionados, coluna_pivot].values

            n_sel = len(df_base_filtrado)
            n_sem_valor_marcados = int(
                (df_seleccao_editada["Analisar"] & (df_seleccao_editada[coluna_pivot] <= 0)).sum()
            )
            st.caption(
                f"🎯 **{n_sel} produto(s) seleccionado(s) com {label_pivot.lower()} válido** para análise."
                + (f" ⚠️ {n_sem_valor_marcados} marcados mas sem {label_pivot.lower()} serão ignorados." if n_sem_valor_marcados > 0 else "")
            )

            if n_sel == 0:
                st.warning("Selecione pelo menos 1 produto para continuar.")
                st.stop()

            # A partir daqui, usamos df_base_filtrado em vez de df_base
            df_base = df_base_filtrado

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

            # ========== CACHE SerpAPI 24h ==========
            forcar_busca_serpapi = st.checkbox(
                "🔄 Forçar nova busca (ignorar cache)",
                value=False,
                help=(
                    "Por defeito, buscas idênticas feitas nas últimas 24h reutilizam o resultado em cache "
                    "(não consomem créditos SerpAPI). Marque esta caixa para forçar uma busca nova e fresca "
                    "(útil se houve promoção recente, lançamento, ou se queres validar dados actualizados)."
                ),
            )

            if st.button(t["btn_analisar"], type="primary"):
                if "Brasil" in pais_sel:
                    whitelist = WHITELIST["BR"]
                    blacklist = BLACKLIST_REGIONAL["BR"]
                    regiao_id = "BR"
                elif "Portugal" in pais_sel:
                    # Portugal busca em toda a UE (sem IVA adicional entre países UE).
                    # Modo aberto: aceita qualquer loja excepto blacklist (sem manter
                    # whitelist exaustiva — o universo de lojas EU é demasiado dinâmico).
                    whitelist = None
                    blacklist = BLACKLIST_REGIONAL["EU"]
                    regiao_id = "EU"
                else:
                    # USA: modo aberto (consistente com Portugal/UE)
                    # Aceita qualquer loja excepto blacklist — em vez de whitelist exaustiva.
                    # O universo de retalhistas US é enorme e dinâmico (LEGO.com, Barnes & Noble,
                    # BrickFever, legoland.com, GameStop, Nintendo, etc. — manter lista actualizada
                    # à mão é insustentável).
                    whitelist = None
                    blacklist = BLACKLIST_REGIONAL["US"]
                    regiao_id = "US"

                progress = st.progress(0.0, text="A analisar produtos...")
                registos = []
                total = len(df_base)
                rejeitados_total = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0, "irrelevante": 0, "internacional": 0, "acessorio": 0, "vendedor_naoconfiavel": 0, "serpapi_total": 0, "sem_preco": 0}

                for idx, (_, row) in enumerate(df_base.iterrows()):
                    progress.progress((idx + 1) / total, text=f"Analisando {idx + 1}/{total}: {row['Nome'][:50]}")
                    concorrentes, rej, concorrentes_similares = buscar_serpapi(
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
                        marca_override=row.get("Marca", ""),
                        forcar_busca=forcar_busca_serpapi,
                    )
                    for k, v in rej.items():
                        rejeitados_total[k] += v

                    precos_conc = [it["preco"] for it in concorrentes]
                    concorrentes_ordenados = sorted(concorrentes, key=lambda x: x["preco"]) if concorrentes else []
                    loja_lider = concorrentes_ordenados[0]["loja"] if concorrentes_ordenados else "Sem dados"
                    menor_concorrente = min(precos_conc) if precos_conc else None
                    mediana_mercado = (
                        sorted(precos_conc)[len(precos_conc)//2] if precos_conc else None
                    )
                    score, rotulo_procura = calcular_score_procura(concorrentes)

                    if modo_analise == "preco_venda":
                        # === MODO "PREÇO DE VENDA ACTUAL" (sem custo/margem como protagonistas) ===
                        preco_actual = float(row.get("Preço Venda Bling", 0) or 0)
                        custo_produto = float(row.get("Custo", 0) or 0)

                        # Sugerido: mantém actual se já vence, senão menor concorrente - 0,01
                        if menor_concorrente is None:
                            preco_sugerido = preco_actual
                            status_codigo = "sem_dados"
                            status_label = "⏳ Sem dados"
                        elif preco_actual <= menor_concorrente:
                            preco_sugerido = preco_actual  # já vence — mantém
                            status_codigo = "vencendo"
                            status_label = "✅ Vencendo"
                        else:
                            preco_sugerido = round(menor_concorrente - 0.01, 2)
                            # Status: % acima do mínimo
                            pct_acima = (preco_actual - menor_concorrente) / menor_concorrente * 100
                            if pct_acima <= 5:
                                status_codigo = "risco"
                                status_label = "🟡 Risco"
                            else:
                                status_codigo = "caro"
                                status_label = "⚠️ Caro"

                        # Diferença vs mercado (% positivo = mais caro que o mínimo)
                        diferenca_vs_mercado = None
                        if menor_concorrente:
                            diferenca_vs_mercado = round(
                                (preco_actual - menor_concorrente) / menor_concorrente * 100, 1
                            )

                        # Margem no preço sugerido (referência de lucro, mesmo neste modo)
                        # Fórmula: (preço_sugerido × (1 - imposto) - custo) / preço_sugerido × 100
                        margem_sugerido_pct = None
                        if custo_produto > 0 and preco_sugerido > 0:
                            lucro_unit = preco_sugerido * (1 - imposto) - custo_produto
                            margem_sugerido_pct = round(lucro_unit / preco_sugerido * 100, 1)

                        # Preço Mínimo (sem prejuízo) — preço que cobre custo + imposto, margem 0
                        # Fórmula: custo / (1 - imposto)
                        # Resultado: vender abaixo disto significa prejuízo
                        preco_minimo_seguro = None
                        if custo_produto > 0 and imposto < 1:
                            preco_minimo_seguro = round(custo_produto / (1 - imposto), 2)

                        recomendacao = recomendacao_investimento(status_codigo, score, row["Qtde"])

                        registos.append({
                            "Nome": row["Nome"],
                            "Linha": row.get("Linha", "Geral"),
                            "EAN": str(row.get("EAN", "")),
                            "SKU": str(row.get("SKU", "")),
                            "ID": row.get("ID", 0),
                            "Qtde": row["Qtde"],
                            "Custo": custo_produto,
                            "Preço Actual": preco_actual,
                            "Menor Concorrente": menor_concorrente,
                            "Preço Sugerido": preco_sugerido,
                            "Preço Mínimo": preco_minimo_seguro,
                            "Diferença vs Mercado %": diferenca_vs_mercado,
                            "Margem no Sugerido %": margem_sugerido_pct,
                            "_concorrentes": concorrentes_ordenados,
                            "_concorrentes_similares": concorrentes_similares,
                            "N Concorrentes": len(concorrentes),
                            "Status": status_label,
                            "_status_code": status_codigo,
                            "Score Procura": score,
                            "Procura": rotulo_procura,
                            "Recomendação": recomendacao,
                            "Atratividade": round(score, 1),  # sem margem, atratividade = score procura
                            "_loja_lider": loja_lider,
                            "_mediana_mercado": mediana_mercado,
                            "_modo": "preco_venda",
                        })

                    else:
                        # === MODO CLÁSSICO (custo + margem) ===
                        estrategias = calcular_estrategias_preco(
                            custo=row["Custo"], imposto=imposto, markup=markup,
                            margem_minima=margem_minima, precos_concorrencia=precos_conc,
                        )
                        # Status Markup: avalia o Preço Calculado (custo + markup ideal) vs mercado.
                        # Útil para perceber a "ambição teórica" e decidir negociar custo / mudar mix.
                        status_markup_label, status_markup_codigo = calcular_status(
                            custo=row["Custo"], imposto=imposto, markup=markup,
                            margem_minima=margem_minima,
                            menor_concorrente=estrategias["menor_concorrente"],
                        )
                        # Manter `status_codigo` como alias para compatibilidade com recomendacao
                        status_label = status_markup_label
                        status_codigo = status_markup_codigo
                        recomendacao = recomendacao_investimento(status_codigo, score, row["Qtde"])

                        if status_codigo == "vencendo":
                            preco_sugerido = estrategias["preco_otimo"]
                        elif status_codigo in ("risco", "caro"):
                            preco_sugerido = estrategias["preco_competitivo"]
                        elif status_codigo == "chao_alto":
                            preco_sugerido = estrategias["preco_minimo"]
                        elif status_codigo == "burn":
                            preco_sugerido = estrategias["preco_minimo"]
                        else:
                            preco_sugerido = estrategias["preco_alvo_markup"]

                        # Status Mercado: avalia o Preço Sugerido (acção real) vs mercado.
                        # Util porque após a app ajustar, a posição real pode ser diferente do Status Markup.
                        status_mercado_label, status_mercado_codigo = calcular_status_mercado(
                            preco_sugerido=preco_sugerido,
                            menor_concorrente=estrategias["menor_concorrente"],
                        )

                        lucro_unitario = preco_sugerido * (1 - imposto) - row["Custo"]
                        lucro_total = round(lucro_unitario * row["Qtde"], 2)
                        margem_real = (lucro_unitario / preco_sugerido * 100) if preco_sugerido > 0 else 0

                        # Pressão de mercado: quanto o Preço Sugerido ficou abaixo (ou acima) do Preço Calculado.
                        pressao_mercado = None
                        preco_markup_alvo = estrategias["preco_alvo_markup"]
                        if preco_markup_alvo and preco_sugerido:
                            pressao_mercado = round(
                                (preco_sugerido - preco_markup_alvo) / preco_markup_alvo * 100, 1
                            )

                        registos.append({
                            "Nome": row["Nome"],
                            "Linha": row.get("Linha", "Geral"),
                            "EAN": str(row.get("EAN", "")),
                            "SKU": str(row.get("SKU", "")),
                            "ID": row.get("ID", 0),
                            "Qtde": row["Qtde"],
                            "Custo": row["Custo"],
                            "Preço Calculado": estrategias["preco_alvo_markup"],
                            "Menor Concorrente": estrategias["menor_concorrente"],
                            "Preço Sugerido": preco_sugerido,
                            "Pressão Mercado %": pressao_mercado,
                            "_concorrentes": concorrentes_ordenados,
                            "_concorrentes_similares": concorrentes_similares,
                            "_mercado_competitivo": estrategias["mercado_competitivo"],
                            "N Concorrentes": len(concorrentes),
                            "Preço Mínimo": estrategias["preco_minimo"],
                            "Preço Competitivo": estrategias["preco_competitivo"],
                            "Preço Óptimo": estrategias["preco_otimo"],
                            "Margem Real %": round(margem_real, 1),
                            "Lucro Unitário": round(lucro_unitario, 2),
                            "Lucro Total": lucro_total,
                            "Status Markup": status_markup_label,
                            "Status Mercado": status_mercado_label,
                            "Status": status_label,  # mantido para compat com filtros / gráficos
                            "_status_code": status_codigo,
                            "_status_markup_code": status_markup_codigo,
                            "_status_mercado_code": status_mercado_codigo,
                            "Score Procura": score,
                            "Procura": rotulo_procura,
                            "Recomendação": recomendacao,
                            "Atratividade": round(score * max(margem_real, 0) / 100, 1),
                            "_loja_lider": loja_lider,
                            "_mediana_mercado": estrategias["mediana_mercado"],
                            "_modo": "custo_margem",
                        })

                progress.empty()
                df_resultado = pd.DataFrame(registos)
                st.session_state.df_final = df_resultado
                st.session_state.df_final.attrs["imposto"] = imposto
                st.session_state.df_final.attrs["markup"] = markup
                st.session_state.df_final.attrs["margem_minima"] = margem_minima
                st.session_state.df_final.attrs["regiao"] = regiao_id
                st.session_state.df_final.attrs["rejeitados"] = rejeitados_total
                st.session_state.df_final.attrs["timestamp"] = datetime.now()

                # Resumo dos filtros aplicados
                if any(rejeitados_total.values()):
                    msgs = []
                    if rejeitados_total.get("serpapi_total"):
                        msgs.append(f"📊 SerpAPI devolveu {rejeitados_total['serpapi_total']} resultados no total")
                    if rejeitados_total.get("vendedor_naoconfiavel"):
                        msgs.append(f"🏪 {rejeitados_total['vendedor_naoconfiavel']} rejeitados (vendedor fora da whitelist)")
                    if rejeitados_total.get("irrelevante"):
                        msgs.append(f"🎯 {rejeitados_total['irrelevante']} rejeitados (produto sem relação com o pesquisado)")
                    if rejeitados_total.get("usado"):
                        msgs.append(f"🧹 {rejeitados_total['usado']} rejeitados (produto não novo)")
                    if rejeitados_total.get("acessorio"):
                        msgs.append(f"🔌 {rejeitados_total['acessorio']} rejeitados (acessórios / produtos compatíveis)")
                    if rejeitados_total.get("internacional"):
                        msgs.append(f"🌐 {rejeitados_total['internacional']} rejeitados (compra internacional)")
                    if rejeitados_total.get("sem_preco"):
                        msgs.append(f"💸 {rejeitados_total['sem_preco']} rejeitados (sem preço)")
                    if rejeitados_total.get("outlier_baixo"):
                        msgs.append(f"📉 {rejeitados_total['outlier_baixo']} preços rejeitados (muito baixos — peças/avulsos)")
                    if rejeitados_total.get("outlier_alto"):
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

                # Forçar refresh do contador de créditos SerpAPI (consumiu agora)
                obter_creditos_serpapi.clear()

                st.rerun()

    # ----- Exibição de Resultados (após corrida) -----
    if st.session_state.df_final is not None:
        df = st.session_state.df_final.copy()
        moeda = t["moeda"]
        imposto_used = df.attrs.get("imposto", 0.04)

        st.divider()
        st.header("📊 Resultados da Análise")

        # Aviso de snapshot — preços capturados num momento específico podem mudar depois
        ts_analise = df.attrs.get("timestamp")
        if ts_analise:
            minutos_atras = int((datetime.now() - ts_analise).total_seconds() / 60)
            if minutos_atras < 1:
                idade = "agora mesmo"
            elif minutos_atras < 60:
                idade = f"há {minutos_atras} min"
            elif minutos_atras < 1440:
                idade = f"há {minutos_atras // 60}h{minutos_atras % 60:02d}"
            else:
                idade = f"há {minutos_atras // 1440} dias"
            st.caption(
                f"📸 **Snapshot tirado {idade}** ({ts_analise.strftime('%d/%m/%Y %H:%M')}) — "
                "preços, ratings e disponibilidade dos concorrentes podem ter mudado entretanto. "
                "Se um link mostrar preço diferente, o concorrente atualizou após a captura."
            )

        # ========== AVISO: Produtos com dados insuficientes ==========
        # Detectar produtos com menos de 3 concorrentes — sinal de que a SerpAPI não
        # conseguiu indexar bem o produto. Causas típicas:
        # - Sets antigos (descontinuados, pouca indexação no Google Shopping)
        # - Lançamentos muito recentes (ainda não indexados pelos marketplaces)
        # - Produtos de nicho / baixa procura
        if "N Concorrentes" in df.columns:
            df_poucos = df[df["N Concorrentes"] < 3]
            if not df_poucos.empty:
                num_problematicos = len(df_poucos)
                exemplos_skus = ", ".join(
                    str(s) for s in df_poucos["SKU"].head(5).tolist() if _valido(s)
                )
                if exemplos_skus:
                    exemplos_txt = f" Exemplos: **{exemplos_skus}**" + (
                        " ..." if num_problematicos > 5 else "."
                    )
                else:
                    exemplos_txt = ""
                st.warning(
                    f"⚠️ **{num_problematicos} produto(s) com dados insuficientes** "
                    f"(menos de 3 concorrentes detectados).{exemplos_txt}\n\n"
                    "**Possíveis causas:**\n"
                    "- 🕰️ **Sets antigos** (descontinuados ou com pouca indexação no Google Shopping)\n"
                    "- 🆕 **Lançamentos recentes** (ainda não indexados pelos marketplaces)\n"
                    "- 🎯 **Produtos de nicho** com baixa concorrência online\n\n"
                    "**Recomendação:** valida manualmente o preço de mercado nos sites principais "
                    "(LEGO oficial, Magalu, Amazon BR, Mercado Livre) e ajusta o **Preço Final** "
                    "no painel Bling antes de enviar."
                )

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

        # Métricas globais — adaptadas ao modo de análise (clássico vs preço de venda)
        modo_metricas = df_v["_modo"].iloc[0] if "_modo" in df_v.columns and len(df_v) > 0 else "custo_margem"

        if modo_metricas == "preco_venda":
            # Sem custo: usamos receita actual e receita potencial (com preço sugerido)
            receita_actual = float((df_v["Preço Actual"] * df_v["Qtde"]).sum()) if "Preço Actual" in df_v.columns else 0.0
            receita_sugerida = float((df_v["Preço Sugerido"] * df_v["Qtde"]).sum())
            ganho_potencial = receita_sugerida - receita_actual

            n_sem_stock = int((df_v["Qtde"] == 0).sum())
            n_total = len(df_v)
            n_vencendo = int((df_v["_status_code"] == "vencendo").sum()) if "_status_code" in df_v.columns else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric(
                "💰 Receita Actual",
                f"{moeda} {receita_actual:,.2f}",
                help="Soma de Preço Actual × Quantidade. Receita potencial mantendo preços actuais.",
            )
            m2.metric(
                "🎯 Receita Sugerida",
                f"{moeda} {receita_sugerida:,.2f}",
                help="Soma de Preço Sugerido × Quantidade. Receita potencial com preços optimizados.",
            )
            delta_pct = (ganho_potencial / receita_actual * 100) if receita_actual > 0 else 0.0
            m3.metric(
                "📈 Variação",
                f"{moeda} {ganho_potencial:+,.2f}",
                f"{delta_pct:+.1f}%",
                help="Diferença entre receita sugerida e actual. Pode ser negativa "
                     "(baixar preços para vencer) ou positiva (subir onde já vence).",
            )
            m4.metric(
                "✅ A Vencer",
                f"{n_vencendo} / {n_total}",
                help="Produtos cujo preço actual já está igual ou abaixo do menor concorrente.",
            )
        else:
            # Modo clássico (custo + margem)
            investimento = float((df_v["Custo"] * df_v["Qtde"]).sum())
            lucro_proj = float(df_v["Lucro Total"].sum())
            roi = (lucro_proj / investimento * 100) if investimento > 0 else 0.0

            receita_total = float((df_v["Preço Sugerido"] * df_v["Qtde"]).sum())
            margem_media = (lucro_proj / receita_total * 100) if receita_total > 0 else 0.0

            n_sem_stock = int((df_v["Qtde"] == 0).sum())
            n_total = len(df_v)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 Investimento", f"{moeda} {investimento:,.2f}",
                      help="Soma de Custo × Quantidade. Apenas produtos em stock.")
            m2.metric("📈 Lucro Projetado", f"{moeda} {lucro_proj:,.2f}",
                      help="Soma do Lucro Total da coluna. Apenas produtos em stock (Qtde > 0).")
            m3.metric("🎯 ROI", f"{roi:.1f}%",
                      help=f"Lucro Projetado ÷ Investimento × 100. "
                           f"Receita total estimada: {moeda} {receita_total:,.2f}")
            m4.metric("📐 Margem Média (ponderada)", f"{margem_media:.1f}%",
                      help="Margem ponderada pelo peso de cada produto (lucro total ÷ receita total). "
                           "Não é a média simples das margens individuais.")

        if n_sem_stock > 0:
            st.caption(
                f"ℹ️ Das {n_total} linhas analisadas, {n_sem_stock} têm stock zero — "
                "estas não contam para os valores acima mas mantêm Atratividade e Recomendação "
                "para você decidir se vale a pena trazer do fornecedor."
            )

        st.divider()
        st.subheader("📉 Análise Visual")

        # Filtrar opções de gráfico conforme modo de análise
        # No modo "preco_venda" não temos Lucro Total nem Margem, então escondemos
        # gráficos que dependem dessas métricas
        if modo_metricas == "preco_venda":
            opcoes_grafico = [
                "1. Distribuição por Status",
                "4. Top 20 — Atratividade (Procura)",
                "6. Distribuição de Atratividade por Categoria",
                "7. Posicionamento de Preço (Eu vs Mercado)",
                "8. Tabela: Recomendação por Categoria",
            ]
        else:
            opcoes_grafico = [
                "1. Distribuição por Status",
                "2. Lucro por Marketplace",
                "3. Lucro por Categoria",
                "4. Top 20 — Atratividade (Procura × Margem)",
                "5. Top 20 — Lucro Total Projetado",
                "6. Distribuição de Atratividade por Categoria",
                "7. Posicionamento de Preço (Eu vs Mercado)",
                "8. Tabela: Recomendação por Categoria",
            ]
        grafico = st.selectbox("Tipo de gráfico:", opcoes_grafico)

        color_map = {
            "✅ Vencendo": "#2ecc71", "🟡 Risco": "#f39c12",
            "⚠️ Caro": "#e67e22", "🟧 Chão acima do mercado": "#d35400",
            "🟥 Burn": "#e74c3c", "❔ Sem dados": "#95a5a6",
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
            # Top 20 produtos por Atratividade — barras horizontais ordenadas
            top = df_v.nlargest(20, "Atratividade")
            hover_data = {"Score Procura": True}
            if "Margem Real %" in df_v.columns:
                hover_data["Margem Real %"] = ":.1f"
            if "Lucro Total" in df_v.columns:
                hover_data["Lucro Total"] = ":.2f"
            elif "Preço Sugerido" in df_v.columns:
                hover_data["Preço Sugerido"] = ":.2f"
            fig = px.bar(
                top, x="Atratividade", y="Nome", orientation="h",
                color="Status", color_discrete_map=color_map,
                hover_data=hover_data,
                title="Top 20 produtos por Atratividade — onde priorizar a compra",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=600)
        elif grafico.startswith("5"):
            top = df_v.nlargest(20, "Lucro Total")
            fig = px.bar(
                top, x="Lucro Total", y="Nome", orientation="h",
                color="Status", color_discrete_map=color_map,
                title="Top 20 produtos por lucro projetado total",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=600)
        elif grafico.startswith("6"):
            # Distribuição da atratividade por categoria — boxplot
            fig = px.box(
                df_v, x="Linha", y="Atratividade", color="Linha", points="all",
                hover_name="Nome",
                title="Distribuição de Atratividade por categoria — onde concentrar o catálogo",
            )
            fig.update_layout(showlegend=False, xaxis_tickangle=-45, height=550)
        elif grafico.startswith("7"):
            amostra = df_v.head(15) if len(df_v) > 15 else df_v
            fig = go.Figure()
            if "Preço Actual" in df_v.columns:
                # Modo preço de venda: mostra Actual vs Sugerido vs Menor Concorrente
                fig.add_trace(go.Bar(name="Preço Actual no Bling", x=amostra["Nome"], y=amostra["Preço Actual"], marker_color="#f39c12"))
                fig.add_trace(go.Bar(name="Preço Sugerido", x=amostra["Nome"], y=amostra["Preço Sugerido"], marker_color="#3498db"))
                fig.add_trace(go.Bar(name="Menor Concorrente", x=amostra["Nome"], y=amostra["Menor Concorrente"], marker_color="#e74c3c"))
                fig.update_layout(barmode="group",
                                  title="Posicionamento: Actual vs Sugerido vs Concorrente (até 15 produtos)",
                                  xaxis_tickangle=-45, height=550)
            else:
                # Modo clássico
                fig.add_trace(go.Bar(name="Preço Calculado (alvo ideal)", x=amostra["Nome"], y=amostra["Preço Calculado"], marker_color="#9b59b6"))
                fig.add_trace(go.Bar(name="Preço Sugerido", x=amostra["Nome"], y=amostra["Preço Sugerido"], marker_color="#3498db"))
                fig.add_trace(go.Bar(name="Menor Concorrente", x=amostra["Nome"], y=amostra["Menor Concorrente"], marker_color="#e74c3c"))
                fig.update_layout(barmode="group", title="Pressão do mercado: Markup ideal vs Sugerido vs Concorrente (até 15 produtos)",
                                  xaxis_tickangle=-45, height=550)
        else:
            # Heatmap categoria × recomendação (texto, não scatter)
            tabela = (
                df_v.groupby(["Linha", "Recomendação"])
                .size().reset_index(name="N")
                .pivot(index="Linha", columns="Recomendação", values="N")
                .fillna(0).astype(int)
            )
            fig = px.imshow(
                tabela, text_auto=True, aspect="auto", color_continuous_scale="Blues",
                title="Quantos produtos por Categoria × Recomendação",
            )
            fig.update_layout(height=max(400, len(tabela) * 35))

        st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("📋 Tabela Detalhada")
        st.caption(
            "ℹ️ **Sobre os preços de concorrentes:** os valores apresentados vêm do Google Shopping (via SerpAPI) "
            "e podem ter 1-5% de diferença face ao preço actual na loja. "
            "Isto deve-se a: (1) latência entre o Google Shopping e a loja, "
            "(2) variações simultâneas no mesmo listing (com/sem cupão, à vista/parcelado, vendedor principal vs marketplace). "
            "Use os valores como **referência estratégica** — antes de mudar o preço, confirme o preço actual na loja."
        )

        # Modo de análise vem em cada linha do df (todas iguais dentro da mesma análise)
        modo_df = df_v["_modo"].iloc[0] if "_modo" in df_v.columns and len(df_v) > 0 else "custo_margem"

        if modo_df == "preco_venda":
            colunas_show = [
                "Nome", "Linha", "Qtde",
                "Custo", "Preço Actual", "Menor Concorrente",
                "Preço Sugerido", "Preço Mínimo",
                "Margem no Sugerido %", "Diferença vs Mercado %",
                "Status", "Procura", "Atratividade", "Recomendação",
                "N Concorrentes",
            ]
            col_config_tabela = {
                "Custo": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço de custo registado no Bling.",
                ),
                "Preço Actual": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço de venda actual no Bling.",
                ),
                "Menor Concorrente": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Menor preço entre os concorrentes confiáveis encontrados.",
                ),
                "Preço Sugerido": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Se já vence, mantém o preço actual. Senão, sugere menor concorrente - R$ 0,01.",
                ),
                "Preço Mínimo": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço mais baixo possível sem prejuízo (cobre apenas custo + imposto, margem zero).\n"
                         "Fórmula: Custo ÷ (1 - imposto).\n"
                         "Vender abaixo disto significa prejuízo.",
                ),
                "Margem no Sugerido %": st.column_config.NumberColumn(
                    format="%.1f %%",
                    help="Margem efectiva se vender pelo Preço Sugerido.\n"
                         "Fórmula: (Preço Sugerido × (1 - imposto) - Custo) ÷ Preço Sugerido × 100.\n"
                         "Negativa = prejuízo. 0% = empate. Positiva = lucro.",
                ),
                "Diferença vs Mercado %": st.column_config.NumberColumn(
                    "Δ Mercado",
                    format="%+.1f %%",
                    help="Quanto o preço actual está acima (+) ou abaixo (-) do menor concorrente.",
                ),
                "Atratividade": st.column_config.ProgressColumn(
                    "🎯 Atratividade",
                    format="%.0f",
                    min_value=0, max_value=100,
                    help="Score de procura (0-100). Use para priorizar produtos a focar.",
                ),
            }
        else:
            # Modo clássico (custo + margem)
            colunas_show = [
                "Nome", "Linha", "Qtde",
                "Custo", "Preço Calculado",
                "Menor Concorrente",
                "Preço Sugerido", "Margem Real %", "Pressão Mercado %",
                "Lucro Total",
                "Status Markup", "Status Mercado",
                "Procura", "Atratividade", "Recomendação",
                "N Concorrentes",
            ]
            col_config_tabela = {
                "Custo": st.column_config.NumberColumn(format=f"{moeda} %.2f"),
                "Preço Calculado": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço alvo IDEAL — calculado pela sua margem desejada, ignorando o mercado. "
                         "Fórmula: custo × (1 + markup) ÷ (1 - imposto).",
                ),
                "Menor Concorrente": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Menor preço entre os concorrentes confiáveis encontrados.",
                ),
                "Preço Sugerido": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço efectivo recomendado, considerando o mercado e a sua margem mínima.",
                ),
                "Status Markup": st.column_config.TextColumn(
                    "🎯 Markup",
                    help="Avalia o Preço CALCULADO (ambição teórica) vs Mercado.\n"
                         "Útil para planeamento: 'se vendesse ao preço ambicioso, ficaria competitivo?'\n"
                         "✅ Vencendo: markup já está abaixo do menor concorrente\n"
                         "🟡 Risco: markup quase igual ao concorrente\n"
                         "⚠️ Caro: markup acima do mercado — perde vendas\n"
                         "🟧 Chão alto: custo + margem mínima já acima do mercado\n"
                         "🟥 Burn: concorrente abaixo do seu custo — não há margem",
                ),
                "Status Mercado": st.column_config.TextColumn(
                    "📊 Mercado",
                    help="Avalia o Preço SUGERIDO (ação real recomendada) vs Mercado.\n"
                         "Reflecte a posição efectiva ao vender pelo preço sugerido.\n"
                         "✅ Vencendo: ≥5% abaixo do mercado\n"
                         "🟡 Risco: entre -5% e +0,5% do mercado\n"
                         "⚠️ Caro: mais de 0,5% acima do mercado",
                ),
                "Pressão Mercado %": st.column_config.NumberColumn(
                    "Δ Pressão",
                    format="%+.1f %%",
                    help="Quanto o Preço Sugerido se afasta do Preço Calculado, "
                         "por causa da concorrência.\n"
                         "• 0% = consigo praticar exactamente o preço que queria\n"
                         "• Negativo = mercado obrigou-me a baixar (perdi % do meu markup)\n"
                         "• Positivo = consigo vender ACIMA do meu cálculo (raro)",
                ),
                "Margem Real %": st.column_config.NumberColumn(
                    format="%.1f %%",
                    help="Margem efectiva sobre o Preço Sugerido, descontando imposto.\n"
                         "Fórmula: (Preço Sugerido × (1 - imposto) - Custo) ÷ Preço Sugerido × 100",
                ),
                "Lucro Total": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Lucro projetado para o stock actual.\n"
                         "Fórmula: (Preço Sugerido × (1 - imposto) - Custo) × Quantidade.\n"
                         "Se Qtde = 0, Lucro Total = 0 mesmo que a margem seja boa.",
                ),
                "Atratividade": st.column_config.ProgressColumn(
                    "🎯 Atratividade",
                    format="%.0f",
                    min_value=0, max_value=100,
                    help="Combina Procura e Margem em um índice 0-100. "
                         "Fórmula: Score Procura × Margem Real ÷ 100. "
                         "Use para priorizar produtos a comprar (não depende de stock).",
                ),
            }

        # Filtrar colunas que realmente existem no df (defensivo)
        colunas_show = [c for c in colunas_show if c in df_v.columns]

        st.dataframe(
            df_v[colunas_show],
            use_container_width=True,
            hide_index=True,
            column_config=col_config_tabela,
        )

        # ---------- ATUALIZAR PREÇOS NO BLING (apenas Brasil + Bling conectado) ----------
        if regiao_id == "BR" and bling_conectado():
            st.divider()
            st.subheader("📤 Atualizar preços no Bling")
            st.caption(
                "Selecione os produtos que pretende atualizar e ajuste o preço se necessário. "
                "Apenas os produtos marcados serão enviados ao Bling."
            )

            # Identificar coluna com ID Bling (se importação foi feita pelo Bling)
            tem_id_bling = "ID" in df_v.columns and df_v["ID"].notna().any()

            if not tem_id_bling and "SKU" not in df_v.columns:
                st.warning(
                    "⚠️ Sem coluna `ID` (importação Bling) nem `SKU` no catálogo, "
                    "não é possível identificar os produtos no Bling. "
                    "Use importação Bling ou inclua SKU na planilha."
                )
            else:
                # ---------- Buscar preços atuais do Bling ----------
                # Buscamos uma única vez por sessão de análise para evitar custo repetido.
                # Usa `_id_bling` se disponível; produtos sem ID não conseguem ser buscados.
                cache_key = "_bling_precos_atuais"
                ja_buscados = st.session_state.get(cache_key, {})

                # Calcular Preço Calculado por linha (já existe na coluna "Preço Calculado")
                if "Preço Calculado" in df_v.columns:
                    precos_calculados = df_v["Preço Calculado"].astype(float)
                else:
                    # fallback: usar Preço Sugerido se a coluna não existe
                    precos_calculados = df_v["Preço Sugerido"].astype(float)

                # Construir lista de IDs Bling para buscar
                ids_bling_serie = df_v.get("ID", pd.Series([None] * len(df_v)))
                ids_a_buscar = []
                for idx, id_b in enumerate(ids_bling_serie):
                    if id_b is None or (isinstance(id_b, float) and pd.isna(id_b)):
                        continue
                    chave = str(id_b)
                    if chave in ja_buscados:
                        continue
                    ids_a_buscar.append((idx, chave))

                if ids_a_buscar:
                    barra_preco = st.progress(0.0, text="🔍 A consultar preços atuais no Bling…")
                    total = len(ids_a_buscar)
                    for n, (_, chave) in enumerate(ids_a_buscar):
                        preco, _msg = bling_obter_preco_atual(chave)
                        ja_buscados[chave] = preco  # None se erro/sem preço
                        barra_preco.progress((n + 1) / total, text=f"🔍 A consultar… {n+1}/{total}")
                    barra_preco.empty()
                    st.session_state[cache_key] = ja_buscados

                # Construir coluna "Preço Atual Bling" a partir do cache
                precos_atuais = []
                for id_b in ids_bling_serie:
                    if id_b is None or (isinstance(id_b, float) and pd.isna(id_b)):
                        precos_atuais.append(None)
                        continue
                    precos_atuais.append(ja_buscados.get(str(id_b)))

                # Valor inicial do Preço Final:
                # = Preço Atual Bling se existe, senão Preço Calculado
                preco_final_inicial = []
                for p_atual, p_calc in zip(precos_atuais, precos_calculados):
                    if p_atual is not None and p_atual > 0:
                        preco_final_inicial.append(float(p_atual))
                    else:
                        preco_final_inicial.append(float(p_calc))

                # Calcular delta visual (Sugerido vs Atual Bling)
                # Cores reflectem IMPACTO FINANCEIRO, não direcção do preço:
                # 🟢 verde: Sugerido > Atual → posso subir preço, ganho margem extra
                # 🔴 vermelho: Sugerido < Atual → tenho de descer, perco margem
                # ⚪ branco: igual (variação < 0,5%)
                # — sem dados (produto novo no Bling ou sem ID)
                deltas = []
                for p_atual, p_sug in zip(precos_atuais, df_v["Preço Sugerido"].astype(float).values):
                    if p_atual is None or p_atual <= 0:
                        deltas.append("—")
                        continue
                    diff = p_sug - float(p_atual)
                    pct = (diff / float(p_atual)) * 100 if p_atual > 0 else 0
                    if abs(pct) < 0.5:
                        deltas.append("⚪ ≈")
                    elif diff > 0:
                        # Sugerido > Atual → ganho margem
                        deltas.append(f"🟢 {pct:+.1f}%")
                    else:
                        # Sugerido < Atual → perco margem
                        deltas.append(f"🔴 {pct:+.1f}%")

                # ---------- Construção/Reutilização do df_envio ----------
                # Problema anterior: a cada rerun reconstruíamos df_envio do zero,
                # o que perdia as edições do utilizador (Streamlit aplica edited_rows
                # do data_editor sobre o NOVO df, mas com os nossos resets, os edits
                # eram sobrescritos pelo valor inicial).
                #
                # Solução: guardar df_envio em session_state e SÓ reconstruir quando
                # a filtragem (lista de SKUs/IDs) muda. Caso contrário, reutilizamos
                # o estado já editado pelo utilizador.
                ids_atuais = [
                    str(i) if i is not None and not (isinstance(i, float) and pd.isna(i)) else None
                    for i in ids_bling_serie
                ]
                skus_atuais = [
                    str(s) if _valido(s) else "" for s in df_v.get("SKU", pd.Series([""] * len(df_v))).values
                ]
                # Hash da filtragem actual (ordem + identificadores)
                envio_hash = hash(tuple(zip(ids_atuais, skus_atuais)))

                envio_state_key = "_bling_df_envio_state"
                envio_hash_key = "_bling_df_envio_hash"

                # Decidir se podemos reutilizar o estado anterior
                reutilizar = (
                    envio_state_key in st.session_state
                    and st.session_state.get(envio_hash_key) == envio_hash
                )

                if reutilizar:
                    # Reutilizar df anterior (preserva edições do utilizador)
                    df_envio = st.session_state[envio_state_key].copy()
                    # Actualizar colunas read-only (Preço Atual Bling, Δ, Sugerido)
                    # caso tenham mudado por refresh do Bling
                    df_envio["Preço Atual Bling"] = [
                        (float(p) if p is not None else None) for p in precos_atuais
                    ]
                    df_envio["Δ"] = deltas
                    df_envio["Preço Sugerido"] = df_v["Preço Sugerido"].astype(float).values
                    df_envio["Status"] = df_v.get(
                        "Status Mercado", df_v.get("Status", "")
                    ).values
                else:
                    # Construir df_envio do zero
                    df_envio = pd.DataFrame({
                        "Enviar": False,  # checkbox por linha
                        "Nome": df_v["Nome"].values,
                        "SKU": df_v.get("SKU", pd.Series([""] * len(df_v))).values,
                        "Preço Atual Bling": [
                            (float(p) if p is not None else None) for p in precos_atuais
                        ],
                        "Δ": deltas,
                        "Preço Sugerido": df_v["Preço Sugerido"].astype(float).values,
                        "Preço Final": preco_final_inicial,
                        "Status": df_v.get("Status Mercado", df_v.get("Status", "")).values,
                    })
                    # Guardar ID se existir (em coluna escondida para identificar)
                    if tem_id_bling:
                        df_envio["_id_bling"] = df_v["ID"].values
                    # Resetar estado do data_editor (chaves antigas seriam aplicadas
                    # sobre linhas erradas)
                    if "bling_envio_editor" in st.session_state:
                        del st.session_state["bling_envio_editor"]

                # Garantir que coluna _id_bling existe se aplicável
                if tem_id_bling and "_id_bling" not in df_envio.columns:
                    df_envio["_id_bling"] = df_v["ID"].values

                # Guardar para próxima execução
                st.session_state[envio_state_key] = df_envio.copy()
                st.session_state[envio_hash_key] = envio_hash

                editado = st.data_editor(
                    df_envio,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Enviar": st.column_config.CheckboxColumn(
                            "Enviar?",
                            help="Marca-se automaticamente quando alteras o Preço Final. Desmarca se não quiseres enviar.",
                            default=False,
                            width="small",
                        ),
                        "Nome": st.column_config.TextColumn("Produto", disabled=True),
                        "SKU": st.column_config.TextColumn("SKU", disabled=True, width="small"),
                        "Preço Atual Bling": st.column_config.NumberColumn(
                            "💼 Atual Bling", format=f"{moeda} %.2f", disabled=True,
                            help="Preço actual no Bling (consultado agora). Vazio se produto não existe no Bling.",
                        ),
                        "Δ": st.column_config.TextColumn(
                            "Δ", disabled=True, width="small",
                            help="🟢 Posso subir preço (ganho margem) | 🔴 Tenho de descer (perco margem) | ⚪ ≈ sem alteração | — sem dados",
                        ),
                        "Preço Sugerido": st.column_config.NumberColumn(
                            "💡 Sugerido", format=f"{moeda} %.2f", disabled=True,
                            help="Preço recomendado pela análise. Considera mercado e margem mínima.",
                        ),
                        "Preço Final": st.column_config.NumberColumn(
                            "✏️ Final",
                            format=f"{moeda} %.2f",
                            help="Preço que será enviado ao Bling. Inicial = Atual Bling (se existe) ou Calculado. "
                                 "Edite para o Sugerido — a linha marca-se automaticamente.",
                            min_value=0.01,
                        ),
                        "Status": st.column_config.TextColumn("Status", disabled=True),
                        "_id_bling": None,  # ocultar
                    },
                    key="bling_envio_editor",
                )

                # ---------- Marca automática Enviar=True ao editar Preço Final ----------
                # Após o data_editor renderizar, lemos `edited_rows` (gerido pelo Streamlit).
                # Para cada linha onde Preço Final foi editado MAS o utilizador ainda não
                # mexeu na checkbox Enviar, adicionamos Enviar=True ao próprio edited_rows.
                # Fazemos rerun para a marca aparecer visualmente.
                #
                # Por que não cria loop infinito:
                # - Condição de marca: "Preço Final" in mudancas AND "Enviar" not in mudancas
                # - Após primeira marca, "Enviar" está em mudancas → condição False
                # - Se user desmarcar manualmente, "Enviar"=False em mudancas → condição False
                # - Se user voltar Preço Final ao inicial, a diff é pequena → condição False
                estado_editor_atual = st.session_state.get("bling_envio_editor", {})
                if isinstance(estado_editor_atual, dict):
                    edited_rows_atuais = estado_editor_atual.get("edited_rows", {})
                    marcou_alguma = False
                    for idx_chave, mudancas in list(edited_rows_atuais.items()):
                        try:
                            idx = int(idx_chave)
                        except (TypeError, ValueError):
                            continue
                        if idx < 0 or idx >= len(preco_final_inicial):
                            continue
                        # Marca apenas se:
                        # - Preço Final está nas mudanças
                        # - Enviar ainda não está (utilizador não interagiu com a checkbox)
                        # - O valor novo difere significativamente do inicial
                        if "Preço Final" in mudancas and "Enviar" not in mudancas:
                            novo_valor = mudancas["Preço Final"]
                            valor_inicial = preco_final_inicial[idx]
                            if novo_valor is not None and valor_inicial is not None:
                                try:
                                    if abs(float(novo_valor) - float(valor_inicial)) > 0.005:
                                        edited_rows_atuais[idx_chave]["Enviar"] = True
                                        marcou_alguma = True
                                except (TypeError, ValueError):
                                    pass
                    if marcou_alguma:
                        # Guardar de volta e forçar rerun para mostrar checkbox marcada
                        estado_editor_atual["edited_rows"] = edited_rows_atuais
                        st.session_state["bling_envio_editor"] = estado_editor_atual
                        st.rerun()

                # Resumo
                n_marcados = int(editado["Enviar"].sum())
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    if n_marcados == 0:
                        st.info("Nenhum produto selecionado. Marque a coluna 'Enviar?' nos produtos que pretende atualizar.")
                    else:
                        st.success(f"✅ {n_marcados} produto(s) selecionado(s) para atualização.")
                with col_b:
                    enviar_clicado = st.button(
                        "📤 Enviar ao Bling",
                        type="primary",
                        disabled=(n_marcados == 0),
                        use_container_width=True,
                    )

                if enviar_clicado:
                    seleccionados = editado[editado["Enviar"]]
                    progresso = st.progress(0.0, text="A enviar...")
                    status_area = st.empty()
                    resultados = []

                    for i, (_, linha) in enumerate(seleccionados.iterrows()):
                        nome = linha["Nome"]
                        sku = linha.get("SKU", "")
                        novo_preco = linha["Preço Final"]
                        id_bling = linha.get("_id_bling")

                        # Validar preço
                        if not novo_preco or novo_preco <= 0:
                            resultados.append({"Produto": nome, "Estado": "❌ Erro", "Detalhe": "Preço inválido"})
                            continue

                        # Obter ID Bling — directo ou via lookup por SKU
                        if not id_bling or (isinstance(id_bling, float) and pd.isna(id_bling)):
                            if not sku:
                                resultados.append({"Produto": nome, "Estado": "❌ Erro", "Detalhe": "Sem ID nem SKU"})
                                continue
                            status_area.caption(f"A procurar SKU `{sku}` no Bling...")
                            id_bling = bling_procurar_id_por_sku(sku)
                            if not id_bling:
                                resultados.append({"Produto": nome, "Estado": "❌ Não encontrado", "Detalhe": f"SKU `{sku}` não existe no Bling"})
                                continue

                        status_area.caption(f"A atualizar `{nome}` para {moeda} {novo_preco:.2f}...")
                        ok, msg = bling_atualizar_preco(int(id_bling), float(novo_preco))
                        resultados.append({
                            "Produto": nome,
                            "Estado": "✅ OK" if ok else "❌ Erro",
                            "Detalhe": msg,
                        })

                        progresso.progress((i + 1) / len(seleccionados), text=f"{i+1}/{len(seleccionados)}")

                    progresso.empty()
                    status_area.empty()

                    df_res = pd.DataFrame(resultados)
                    n_ok = (df_res["Estado"] == "✅ OK").sum()
                    n_erro = len(df_res) - n_ok

                    if n_ok > 0:
                        st.success(f"✅ {n_ok} produto(s) atualizado(s) com sucesso no Bling.")
                    if n_erro > 0:
                        st.warning(f"⚠️ {n_erro} produto(s) falharam — veja detalhes abaixo.")
                    st.dataframe(df_res, use_container_width=True, hide_index=True)

        # ---------- PAINEL DE VERIFICAÇÃO ----------
        st.divider()
        st.subheader("🔍 Painel de Verificação de Concorrentes")
        st.caption(
            "ℹ️ Os preços abaixo vêm do Google Shopping (via SerpAPI). Podem ter pequena variação "
            "face ao preço actual na loja (1-5%) devido a latência e variações no mesmo listing "
            "(cupões, à vista, vendedores marketplace). Clique no link do concorrente para confirmar antes de decidir."
        )
        st.markdown(
            "**👇 Escolha um produto na lista abaixo** para inspecionar todos os concorrentes "
            "confiáveis encontrados, com nome da loja, preço, avaliação e link para o anúncio."
        )

        produto_inspect = st.selectbox(
            "📦 Produto a inspecionar (clique para abrir a lista):",
            options=df_v["Nome"].tolist(),
            key="produto_inspect",
            help="Clique nesta caixa para ver todos os produtos analisados e escolher um.",
        )

        if produto_inspect:
            linha_inspect = df_v[df_v["Nome"] == produto_inspect].iloc[0]
            concorrentes_lista = linha_inspect.get("_concorrentes", []) or []
            similares_lista = linha_inspect.get("_concorrentes_similares", []) or []

            # Cabeçalho de contexto — adaptado ao modo de análise
            modo_linha = linha_inspect.get("_modo", "custo_margem")
            if modo_linha == "preco_venda":
                # Linha 1: financeiro
                ci1, ci2, ci3, ci4 = st.columns(4)
                ci1.metric(
                    "Custo",
                    f"{moeda} {linha_inspect.get('Custo', 0):,.2f}",
                    help="Preço de custo registado no Bling.",
                )
                ci2.metric(
                    "Preço Actual",
                    f"{moeda} {linha_inspect.get('Preço Actual', 0):,.2f}",
                    help="Preço de venda actualmente praticado no Bling.",
                )
                ci3.metric(
                    "Preço Sugerido",
                    f"{moeda} {linha_inspect['Preço Sugerido']:,.2f}",
                    help="Preço recomendado pela análise (mantém actual se já vence; senão menor concorrente - R$ 0,01).",
                )
                margem_val = linha_inspect.get("Margem no Sugerido %")
                if margem_val is not None and pd.notna(margem_val):
                    ci4.metric(
                        "Margem no Sugerido",
                        f"{margem_val:+.1f} %",
                        help="Margem se vender pelo Preço Sugerido. Negativa = prejuízo.",
                    )
                else:
                    ci4.metric("Margem no Sugerido", "—", help="Sem custo registado.")

                # Linha 2: referências de mercado
                cj1, cj2, cj3 = st.columns(3)
                menor_val = linha_inspect.get("Menor Concorrente")
                cj1.metric(
                    "Menor Concorrente",
                    f"{moeda} {menor_val:,.2f}" if menor_val else "—",
                )
                preco_min_val = linha_inspect.get("Preço Mínimo")
                cj2.metric(
                    "Preço Mínimo (sem prejuízo)",
                    f"{moeda} {preco_min_val:,.2f}" if preco_min_val else "—",
                    help="Preço mais baixo que pode praticar sem ter prejuízo. "
                         "Calcula custo + imposto, sem margem.",
                )
                cj3.metric("Concorrentes encontrados", len(concorrentes_lista))
            else:
                # Modo clássico
                ci1, ci2, ci3, ci4 = st.columns(4)
                ci1.metric("Custo", f"{moeda} {linha_inspect.get('Custo', 0):,.2f}")
                ci2.metric("Preço Calculado", f"{moeda} {linha_inspect.get('Preço Calculado', 0):,.2f}")
                ci3.metric("Preço Sugerido", f"{moeda} {linha_inspect['Preço Sugerido']:,.2f}")
                ci4.metric("Concorrentes encontrados", len(concorrentes_lista))

            if not concorrentes_lista:
                st.info("Sem concorrentes confiáveis encontrados para este produto.")
            else:
                # Construir tabela de concorrentes; fallback inteligente quando o link directo
                # não vem da SerpAPI:
                # 1) Se a loja for um marketplace conhecido, vai directo à busca interna do marketplace
                # 2) Senão, recorre ao Google Shopping da região (com ncr para evitar geo-redirect)
                MARKETPLACE_SEARCH_URL = {
                    # Brasil
                    "amazon.com.br": "https://www.amazon.com.br/s?k={q}",
                    "mercadolivre.com.br": "https://lista.mercadolivre.com.br/{q}",
                    "magazineluiza.com.br": "https://www.magazineluiza.com.br/busca/{q}/",
                    "magalu": "https://www.magazineluiza.com.br/busca/{q}/",
                    "americanas.com.br": "https://www.americanas.com.br/busca/{q}",
                    "submarino.com.br": "https://www.submarino.com.br/busca/{q}",
                    "shoptime.com.br": "https://www.shoptime.com.br/busca/{q}",
                    "casasbahia.com.br": "https://www.casasbahia.com.br/{q}/b",
                    "pontofrio.com.br": "https://www.pontofrio.com.br/{q}/b",
                    "carrefour.com.br": "https://www.carrefour.com.br/busca/{q}",
                    "fastshop.com.br": "https://www.fastshop.com.br/web/s/{q}",
                    "kabum.com.br": "https://www.kabum.com.br/busca/{q}",
                    "centauro.com.br": "https://www.centauro.com.br/busca?Ntt={q}",
                    "ribrinquedos.com.br": "https://www.ribrinquedos.com.br/busca?busca={q}",
                    "rihappy.com.br": "https://www.rihappy.com.br/{q}",
                    "shopee.com.br": "https://shopee.com.br/search?keyword={q}",
                    # Portugal
                    "worten.pt": "https://www.worten.pt/search?query={q}",
                    "fnac.pt": "https://www.fnac.pt/SearchResult/ResultList.aspx?SCat=0!1&Search={q}",
                    "elcorteingles.pt": "https://www.elcorteingles.pt/search/?s={q}",
                    "pcdiga.com": "https://www.pcdiga.com/catalogsearch/result/?q={q}",
                    "mediamarkt.pt": "https://mediamarkt.pt/pages/search-results-page?q={q}",
                    "auchan.pt": "https://www.auchan.pt/pt/pesquisa?q={q}",
                    "kuantokusta.pt": "https://www.kuantokusta.pt/search?q={q}",
                    # UE
                    "amazon.es": "https://www.amazon.es/s?k={q}",
                    "amazon.de": "https://www.amazon.de/s?k={q}",
                    "amazon.it": "https://www.amazon.it/s?k={q}",
                    "amazon.fr": "https://www.amazon.fr/s?k={q}",
                    "amazon.nl": "https://www.amazon.nl/s?k={q}",
                    "tradeinn.com": "https://www.tradeinn.com/searchresults?keywords={q}",
                    "kidinn.com": "https://www.kidinn.com/searchresults?keywords={q}",
                    "bol.com": "https://www.bol.com/nl/nl/s/?searchtext={q}",
                    "cdiscount.com": "https://www.cdiscount.com/search/10/{q}.html",
                    "fnac.com": "https://www.fnac.com/SearchResult/ResultList.aspx?Search={q}",
                    # USA
                    "amazon.com": "https://www.amazon.com/s?k={q}",
                    "ebay.com": "https://www.ebay.com/sch/i.html?_nkw={q}",
                    "walmart.com": "https://www.walmart.com/search?q={q}",
                    "target.com": "https://www.target.com/s?searchTerm={q}",
                    "bestbuy.com": "https://www.bestbuy.com/site/searchpage.jsp?st={q}",
                    "newegg.com": "https://www.newegg.com/p/pl?d={q}",
                }

                def _e_link_agregador_google(url):
                    """Detecta páginas de comparação do Google Shopping (frágeis, expiram)
                    em vez de links directos para o anúncio do vendedor."""
                    if not url:
                        return False
                    u = url.lower()
                    # Padrões típicos: google.com/shopping/, ?ibp=oshop, /aclk?, &prds=
                    return (
                        ("google." in u and ("/shopping/" in u or "ibp=oshop" in u or "tbm=shop" in u))
                        or "/aclk?" in u
                    )

                def _link_ou_fallback(c, nome_produto):
                    """Devolve (link, tipo) onde tipo é 'directo' (link válido a um produto)
                    ou 'sem_link' (não temos como dar link directo confiável).
                    Concorrentes 'sem_link' são filtrados no painel para evitar mostrar URLs
                    de busca interna que muitas vezes não encontram o produto."""
                    link_real = c.get("link") or ""
                    if link_real and not _e_link_agregador_google(link_real):
                        return link_real, "directo"
                    return "", "sem_link"

                rows = []
                for i, c in enumerate(concorrentes_lista):
                    link, tipo = _link_ou_fallback(c, produto_inspect)
                    if tipo != "directo":
                        continue  # sem link directo → não mostra
                    rows.append({
                        "#": len(rows) + 1,
                        "Loja": c["loja"],
                        "Preço": c["preco"],
                        "Rating": c.get("rating"),
                        "Reviews": c.get("reviews", 0),
                        "Link": link,
                    })
                df_conc = pd.DataFrame(rows)

                st.dataframe(
                    df_conc,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "#": st.column_config.NumberColumn(
                            "#", width="small", format="%d",
                            help="Posição (ordenado por preço crescente).",
                        ),
                        "Loja": st.column_config.TextColumn(
                            "Loja", width="medium",
                        ),
                        "Preço": st.column_config.NumberColumn(
                            "Preço", width="small", format=f"{moeda} %.2f",
                        ),
                        "Rating": st.column_config.NumberColumn(
                            "⭐", width="small", format="%.1f",
                        ),
                        "Reviews": st.column_config.NumberColumn(
                            "Avaliações", width="small", format="%d",
                        ),
                        "Link": st.column_config.LinkColumn(
                            "🔗 Anúncio", width="small",
                            display_text="abrir",
                            help="Abre o anúncio do concorrente. Concorrentes sem link directo "
                                 "ao produto não são mostrados.",
                        ),
                    },
                )

                if len(concorrentes_lista) <= 2:
                    st.warning(
                        f"⚠️ Apenas {len(concorrentes_lista)} concorrente(s) encontrado(s). "
                        "Poucos resultados podem indicar produto pouco distribuído ou que os filtros "
                        "rejeitaram resultados (consulte o resumo no topo da análise)."
                    )

                # ---- POSSÍVEIS SIMILARES ----
                # Produtos com a mesma marca, mas SKU diferente ou nome divergente.
                # Não entram no cálculo de Preço Sugerido/Status, mas o utilizador pode
                # querer verificá-los — talvez seja o mesmo produto renomeado, ou um
                # similar relevante para comparação.
                if similares_lista:
                    with st.expander(
                        f"🔍 Possíveis similares ({len(similares_lista)}) — verificar se algum é o produto que procuras"
                    ):
                        st.caption(
                            "⚠️ **Estes anúncios têm a marca certa mas título diferente do que pesquisas.** "
                            "Olha o **título do anúncio** — é o produto que a loja realmente listou. "
                            "Pode ser: (1) o mesmo produto com nome diferente, "
                            "(2) variação da linha (cor, tamanho), ou "
                            "(3) outro produto da marca.\n\n"
                            "💡 **O link vai à busca por **`SKU pesquisado`** na loja, não ao anúncio listado** — "
                            "se a loja tem o produto que tu queres, vais encontrá-lo lá; "
                            "se não tem, vais encontrar este similar."
                        )
                        rows_sim = []
                        for i, c in enumerate(similares_lista):
                            link, tipo = _link_ou_fallback(c, produto_inspect)
                            if tipo != "directo":
                                continue  # sem link directo → não mostra
                            rows_sim.append({
                                "#": len(rows_sim) + 1,
                                "Loja": c["loja"],
                                "Preço (?)": c["preco"],  # (?) indica preço a confirmar
                                "Link": link,
                            })
                        df_sim = pd.DataFrame(rows_sim)
                        st.dataframe(
                            df_sim,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "#": st.column_config.NumberColumn("#", width="small", format="%d"),
                                "Loja": st.column_config.TextColumn("Loja", width="medium"),
                                "Preço (?)": st.column_config.NumberColumn(
                                    "Preço (?)",
                                    format=f"{moeda} %.2f",
                                    width="small",
                                    help="O preço listado refere-se a um anúncio que NÃO é o produto que "
                                         "procuras (título e/ou SKU diferentes). Confirma no link.",
                                ),
                                "Link": st.column_config.LinkColumn(
                                    "🔗",
                                    width="small",
                                    display_text="abrir",
                                    help="Link directo do anúncio listado pela SerpAPI. "
                                         "Confirma se é o produto que procuras antes de comparar.",
                                ),
                            },
                        )

                # ---- DEBUG: ver campos crus da SerpAPI para cada concorrente ----
                # Útil para identificar como cada loja marca "produto internacional"
                # e ajustar as keywords/regras de filtragem.
                with st.expander("🔍 Debug: ver campos crus da SerpAPI (para ajustar filtros)"):
                    st.caption(
                        "Se algum dos concorrentes acima é 'produto internacional' mas escapou ao filtro, "
                        "expanda aqui e procure pelo nome da loja — vai ver exactamente os campos que a SerpAPI "
                        "devolveu para esse produto. Procure por texto que indique origem internacional."
                    )
                    for idx, c in enumerate(concorrentes_lista, 1):
                        raw = c.get("_raw") or {}
                        if not raw:
                            continue
                        with st.container(border=True):
                            st.markdown(f"**#{idx} — {c.get('loja', '?')} — {moeda} {c.get('preco', 0):.2f}**")
                            st.markdown(f"**title:** `{raw.get('title', '')[:200]}`")
                            st.markdown(f"**source:** `{raw.get('source', '')}`")
                            st.markdown(f"**link:** `{raw.get('link', '')[:200]}`")
                            st.markdown(f"**extensions:** `{raw.get('extensions', '')}`")
                            st.markdown(f"**delivery:** `{raw.get('delivery', '')}`")
                            st.markdown(f"**badge:** `{raw.get('badge', '')}`")
                            st.markdown(f"**tag:** `{raw.get('tag', '')}`")
                            if raw.get("snippet"):
                                st.markdown(f"**snippet:** `{raw.get('snippet', '')[:200]}`")

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
