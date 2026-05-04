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


# =============================================================================
# 1. CONFIGURAÇÃO DA INTERFACE
# =============================================================================
st.set_page_config(page_title="IA Marketplace Global", layout="wide", page_icon="🌎")


# Handler do redirect OAuth do Bling — só executa se houver utilizador autenticado.
# Quando o utilizador autoriza no Bling, este redireciona para a app com `?code=...&state=...`
def _handle_bling_oauth_callback():
    qs = st.query_params
    if "code" in qs and "state" in qs:
        # Só faz sentido se o user já está autenticado (o Bling é por user)
        if not utilizador_autenticado():
            return
        codigo = qs["code"]
        state = qs["state"]
        state_esperado = st.session_state.get("bling_oauth_state")
        if state_esperado and state != state_esperado:
            st.error("⚠️ Estado OAuth inválido. Tente conectar novamente.")
            st.query_params.clear()
            return
        ok, msg = bling_trocar_codigo_por_tokens(codigo)
        if ok:
            st.success(f"✅ {msg}")
            st.session_state.pop("bling_oauth_state", None)
        else:
            st.error(f"❌ {msg}")
        st.query_params.clear()


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


def titulo_relevante(item, nome_produto, sku):
    """Verifica se o título do produto retornado tem relação com o produto pesquisado.
    Devolve True se houver match suficiente de palavras-chave significativas, False senão.
    Estratégia:
    1) Se o SKU aparece no título do resultado → match imediato (caso forte)
    2) Senão, calcular interseção de palavras significativas (≥ 3 chars, fora de stopwords)
       Exigir pelo menos 50% das palavras significativas do nome esperado no título retornado,
       OU pelo menos 2 palavras se o nome tiver poucas
    """
    titulo = str(item.get("title", "")).lower().strip()
    if not titulo:
        return False

    # Match por SKU (mais forte)
    if sku and str(sku).strip():
        sku_str = str(sku).strip().lower()
        # Match com palavra completa para evitar "10" matching em "1023"
        if re.search(rf"\b{re.escape(sku_str)}\b", titulo):
            return True

    if not nome_produto:
        return True  # Sem referência, aceita

    def _tokens(s):
        # Tokenizar: minúsculas, manter alfanuméricos, remover stopwords
        s = re.sub(r"[^\w\s]", " ", s.lower())
        return {w for w in s.split() if len(w) >= 3 and w not in STOPWORDS_RELEVANCIA}

    tokens_esperados = _tokens(nome_produto)
    if not tokens_esperados:
        return True

    tokens_titulo = _tokens(titulo)
    intersecao = tokens_esperados & tokens_titulo

    # Critérios:
    # - Se nome tem ≤3 palavras significativas, exigir pelo menos 1 em comum
    # - Senão exigir pelo menos 50% das palavras esperadas presentes
    if len(tokens_esperados) <= 3:
        return len(intersecao) >= 1
    return len(intersecao) / len(tokens_esperados) >= 0.5


# =============================================================================
# 4. AUTENTICAÇÃO + CLIENTE SUPABASE (multi-tenant via Supabase Auth + RLS)
# =============================================================================
# Estratégia: usamos a chave ANON do Supabase (segura para frontend) + access_token
# do utilizador autenticado via Google OAuth. As Row-Level Security policies
# aplicam-se automaticamente: cada user só vê os seus dados.

@st.cache_resource
def _get_anon_client():
    """Cliente Supabase com chave anónima (não autenticado)."""
    if not SUPABASE_AVAILABLE:
        return None
    try:
        url = st.secrets["SUPABASE_URL"]
        # SUPABASE_ANON_KEY é a chave 'publishable'/'anon' (segura para frontend),
        # diferente da service_role que dava acesso total
        key = st.secrets["SUPABASE_ANON_KEY"]
        return create_client(url, key)
    except (KeyError, FileNotFoundError):
        return None
    except Exception as e:
        st.warning(f"Falha ao conectar ao Supabase: {e}")
        return None


def get_supabase_client():
    """Cliente Supabase com a sessão do utilizador actual.
    Devolve None se Supabase não estiver configurado ou se utilizador não estiver autenticado."""
    base = _get_anon_client()
    if base is None:
        return None
    sess = st.session_state.get("user_session")
    if sess and sess.get("access_token"):
        try:
            base.postgrest.auth(sess["access_token"])
        except Exception:
            pass
    return base


def supabase_ativo():
    """True se Supabase está configurado (não diz nada sobre auth do user)."""
    return _get_anon_client() is not None


def utilizador_autenticado():
    """True se há um utilizador logado nesta sessão."""
    return bool(st.session_state.get("user_session"))


def user_id_actual():
    """Devolve o UUID do utilizador autenticado, ou None."""
    sess = st.session_state.get("user_session") or {}
    return (sess.get("user") or {}).get("id")


def user_email_actual():
    """Devolve o email do utilizador autenticado, ou None."""
    sess = st.session_state.get("user_session") or {}
    return (sess.get("user") or {}).get("email")


def iniciar_login_google():
    """Devolve URL para o utilizador iniciar o login com Google via fluxo PKCE.
    PKCE devolve `?code=...` na URL (query param, não fragmento), o que o Streamlit
    consegue ler nativamente via st.query_params, sem precisar de hacks JavaScript."""
    sb = _get_anon_client()
    if sb is None:
        return None
    try:
        site_url = st.secrets.get("SITE_URL", "https://viabilidadedevendas.streamlit.app/")
        resp = sb.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": site_url,
                # PKCE: o Supabase devolve "?code=..." em vez de "#access_token=..."
                "flow_type": "pkce",
            },
        })
        return resp.url
    except Exception as e:
        st.error(f"Falha ao iniciar login Google: {e}")
        return None


def _processar_token_url():
    """Detecta o `code` retornado pelo Supabase após login OAuth (fluxo PKCE).
    Troca o code por uma sessão completa (access_token + refresh_token + user info)."""
    if utilizador_autenticado():
        return

    qs = st.query_params

    # FLUXO PKCE (preferido): Supabase devolve ?code=...
    if "code" in qs and "state" not in qs:  # Bling também usa state, este é só o do Supabase
        code = qs["code"]
        try:
            sb = _get_anon_client()
            if sb is None:
                return
            sess_resp = sb.auth.exchange_code_for_session({"auth_code": code})
            if sess_resp and sess_resp.session and sess_resp.user:
                st.session_state["user_session"] = {
                    "access_token": sess_resp.session.access_token,
                    "refresh_token": sess_resp.session.refresh_token,
                    "user": {
                        "id": sess_resp.user.id,
                        "email": sess_resp.user.email,
                        "name": (sess_resp.user.user_metadata or {}).get("full_name", ""),
                        "avatar": (sess_resp.user.user_metadata or {}).get("avatar_url", ""),
                    },
                }
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            # Se o code já foi usado ou expirou, simplesmente limpar
            err_msg = str(e).lower()
            if "code verifier" in err_msg or "invalid" in err_msg or "expired" in err_msg:
                st.query_params.clear()
            else:
                st.error(f"Falha ao validar login: {e}")
                st.query_params.clear()

    # FLUXO IMPLÍCITO (fallback): Supabase devolve ?access_token=... directamente
    # (caso a config ainda não esteja em PKCE no painel Supabase)
    elif "access_token" in qs and "refresh_token" in qs:
        try:
            sb = _get_anon_client()
            if sb is None:
                return
            user_resp = sb.auth.get_user(qs["access_token"])
            if user_resp and user_resp.user:
                st.session_state["user_session"] = {
                    "access_token": qs["access_token"],
                    "refresh_token": qs["refresh_token"],
                    "user": {
                        "id": user_resp.user.id,
                        "email": user_resp.user.email,
                        "name": (user_resp.user.user_metadata or {}).get("full_name", ""),
                        "avatar": (user_resp.user.user_metadata or {}).get("avatar_url", ""),
                    },
                }
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Falha ao validar sessão: {e}")
            st.query_params.clear()


def fazer_logout():
    """Termina a sessão do utilizador localmente."""
    sb = _get_anon_client()
    if sb is not None:
        try:
            sb.auth.sign_out()
        except Exception:
            pass
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def renderizar_pagina_login():
    """Mostra a tela de login. Bloqueia o resto da app até o user autenticar."""
    st.title("🌎 Viabilidade de Vendas")
    st.markdown("### Análise de preços e concorrência para o seu catálogo")
    st.divider()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("#### Faça login para começar")
        st.write("")

        if not supabase_ativo():
            st.error(
                "🔌 Sistema de autenticação indisponível.\n\n"
                "Configure `SUPABASE_URL` e `SUPABASE_ANON_KEY` nos Secrets."
            )
            return

        url_google = iniciar_login_google()
        if url_google:
            # Botão que redireciona NA MESMA ABA (não abre nova).
            # link_button do Streamlit abriria nova aba (target="_blank"),
            # o que quebra o fluxo OAuth — o callback voltaria à aba nova,
            # não a esta onde a app está.
            if st.button("🔐 Entrar com Google", type="primary", use_container_width=True):
                st.markdown(
                    f"<meta http-equiv='refresh' content='0; url={url_google}'>"
                    f"<script>window.location.href = {url_google!r};</script>"
                    f"<p>A redirecionar para o Google...</p>",
                    unsafe_allow_html=True,
                )
                st.stop()
        st.caption(
            "Ao entrar, aceita os Termos de Utilização e a Política de Privacidade. "
            "Os seus dados (catálogo, análises) ficam isolados — só você os vê."
        )

        st.divider()
        with st.expander("ℹ️ Como funciona"):
            st.markdown("""
- Login com a sua conta Google (sem precisar criar nova senha)
- Carrega o seu catálogo (planilha Excel/CSV ou via Bling)
- Configura margens e impostos
- Analisa preços face a concorrentes confiáveis da região
- Histórico de análises guardado para ver tendências

Os seus dados são privados — outros utilizadores não os conseguem ver.
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
    Configurável via Secrets, com fallback para a URL pública conhecida."""
    try:
        return st.secrets["BLING_REDIRECT_URI"]
    except (KeyError, FileNotFoundError):
        return "https://viabilidadedevendas.streamlit.app/"


def bling_iniciar_autorizacao():
    """Devolve URL para o utilizador autorizar a aplicação no Bling."""
    import secrets as py_secrets  # nome local para não colidir com st.secrets
    state = py_secrets.token_urlsafe(16)
    st.session_state["bling_oauth_state"] = state

    params = {
        "response_type": "code",
        "client_id": st.secrets["BLING_CLIENT_ID"],
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
    """Persiste tokens no Supabase. payload vem do endpoint /oauth/token."""
    sb = get_supabase_client()
    if sb is None:
        return
    expires_in = int(payload.get("expires_in", 21600))  # default 6h
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    sb.table("bling_tokens").upsert({
        "id": 1,
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", ""),
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


def _bling_carregar_tokens():
    """Lê tokens do Supabase. Devolve dict ou None."""
    sb = get_supabase_client()
    if sb is None:
        return None
    try:
        r = sb.table("bling_tokens").select("*").eq("id", 1).limit(1).execute()
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
    """Apaga os tokens da BD. Próxima utilização exigirá nova autorização."""
    sb = get_supabase_client()
    if sb is not None:
        try:
            sb.table("bling_tokens").delete().eq("id", 1).execute()
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
            # Token expirado / revogado — tentar renovar uma vez
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
        return dados.get("data", []), 1  # total de páginas: Bling V3 não devolve, paginar até vazio
    except Exception as e:
        st.warning(f"Erro ao chamar Bling: {e}")
        return [], 0


def bling_importar_catalogo(progresso_cb=None):
    """Importa todos os produtos do Bling, paginando até esgotar.
    progresso_cb(pagina_atual, n_total_acumulado) é chamado entre páginas (opcional)."""
    todos = []
    pagina = 1
    while True:
        produtos, _ = bling_listar_produtos(pagina=pagina, limite=100)
        if not produtos:
            break
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
    rejeitados_log = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0, "irrelevante": 0}
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

            # Verificar relevância: o título do resultado deve ter relação com o produto pesquisado
            # Crucial porque a SerpAPI às vezes devolve produtos não relacionados quando o EAN
            # não está bem indexado para a região
            if not titulo_relevante(item, produto, sku):
                rejeitados_log["irrelevante"] += 1
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


def calcular_status(custo, imposto, markup, margem_minima, menor_concorrente):
    """Determina o status do produto face ao mercado.
    Hierarquia de avaliação:
    1. Sem dados → ❔
    2. Concorrente abaixo do custo+imposto → 🟥 Burn (impossível competir sem prejuízo)
    3. Concorrente abaixo do PREÇO MÍNIMO (custo+imposto+margem mínima) → 🟧 Chão acima do mercado
       (consegue vender mas só com margem mínima, sem nunca alcançar o markup alvo)
    4. Markup alvo ≥ 5% acima do menor concorrente → ⚠️ Caro
    5. Markup alvo entre ±5% do menor → 🟡 Risco
    6. Markup alvo ≥ 5% abaixo do menor → ✅ Vencendo (folga real para escolher entre preços)"""
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
# 1) Tentar processar token Google na URL (utilizador acabou de fazer login)
_processar_token_url()

# 2) Se não está autenticado, mostrar página de login e parar
if not utilizador_autenticado():
    renderizar_pagina_login()
    st.stop()

# 3) Já autenticado — processar callback Bling se aplicável
_handle_bling_oauth_callback()


# =============================================================================
# 7. SIDEBAR
# =============================================================================
with st.sidebar:
    # CSS para reduzir espaçamento entre secções na sidebar
    st.markdown("""
    <style>
        /* Reduzir margem dos divisores */
        section[data-testid="stSidebar"] hr {
            margin-top: 0.6rem !important;
            margin-bottom: 0.6rem !important;
        }
        /* Reduzir margem dos cabeçalhos */
        section[data-testid="stSidebar"] h2 {
            margin-top: 0.3rem !important;
            margin-bottom: 0.3rem !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }
        /* Reduzir padding em volta dos elementos */
        section[data-testid="stSidebar"] .stMarkdown {
            margin-bottom: 0.3rem !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Info do utilizador logado + botão logout
    email = user_email_actual() or "(sem email)"
    nome = (st.session_state.get("user_session", {}).get("user", {}) or {}).get("name", "")
    avatar = (st.session_state.get("user_session", {}).get("user", {}) or {}).get("avatar", "")

    col_av, col_logout = st.columns([3, 1])
    with col_av:
        if avatar:
            st.markdown(
                f"<img src='{avatar}' width='28' style='border-radius:50%;vertical-align:middle;'/> "
                f"<span style='font-size:0.85rem;'>{nome or email}</span>",
                unsafe_allow_html=True,
            )
        else:
            st.caption(f"👤 {nome or email}")
    with col_logout:
        if st.button("Sair", key="btn_logout", help="Terminar sessão"):
            fazer_logout()
            st.rerun()

    st.divider()
    st.header("🌎 Região")
    pais_sel = st.selectbox("Selecione:", list(idiomas.keys()), key="pais_main")

    if st.session_state.pais_anterior != pais_sel:
        st.session_state.df_final = None
        st.session_state.pais_anterior = pais_sel

    t = idiomas[pais_sel]

    scope_pt = "Apenas Portugal"
    if "Portugal" in pais_sel:
        scope_pt = st.radio("Âmbito:", ["Apenas Portugal", "União Europeia"])

    st.divider()
    st.header("🔑 Chave API")
    api_key_input = st.text_input(t["label_chave"], type="password", value=st.session_state.api_key or "")
    if st.button(t["btn_confirmar"]):
        st.session_state.api_key = api_key_input.strip() or None
        if st.session_state.api_key:
            st.success("Chave ativada!")
        else:
            st.error("Chave vazia.")

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


# =============================================================================
# 8. CORPO PRINCIPAL — ABAS
# =============================================================================
st.title(t["titulo"])

# Card discreto de ajuda — sempre acessível, opcional
with st.expander("📚 Primeira vez aqui? Ver tutorial rápido", expanded=False):
    st.markdown("""
**Como usar esta aplicação em 5 passos**

1. **Aceitar os Termos** — basta marcar a caixa abaixo do título.
2. **Inserir a sua chave SerpAPI** na barra lateral. Ainda não tem chave? Veja o passo seguinte.
3. **Carregar a planilha** com os seus produtos (ou importar do Bling se for plano pago) — pode descarregar uma planilha-modelo se ainda não tiver uma.
4. **Configurar margens e impostos** nos parâmetros da análise.
5. **Iniciar Análise** — vai pesquisar cada produto no Google Shopping e cruzar com concorrentes confiáveis da região seleccionada.

---

**🔑 Como obter chave SerpAPI**

1. Crie conta em [serpapi.com](https://serpapi.com) (plano gratuito: 100 buscas/mês)
2. Ao fazer login, no painel verá a sua **API Key** — copie-a
3. Cole na barra lateral e clique **Confirmar Chave**

⚠️ **Cada produto consome 1-3 buscas** (o algoritmo tenta primeiro EAN, depois SKU, depois nome). Para 90 produtos pode consumir até ~270 buscas. No plano gratuito só caberão ~30 produtos por mês.

---

**🛒 Como obter chave Bling V3 (OAuth2)**

⚠️ **Requer plano Bling Cobrança ou superior** — o plano gratuito não dá acesso ao painel de developers.

1. No Bling, ir a **Painel de developers** ([developer.bling.com.br](https://developer.bling.com.br))
2. Clicar em **Criar aplicativo**
3. Preencher:
   - **Nome:** "Análise de Preços"
   - **Categoria:** Privado / Uso próprio
   - **Redirect URI:** `https://viabilidadedevendas.streamlit.app/` (a URL desta app)
   - **Escopos:** apenas leitura de produtos e estoque
4. Após criar, copiar o **client_id** e **client_secret** que aparecem
5. Adicionar nos Secrets do Streamlit Cloud:

```toml
BLING_CLIENT_ID = "xxxxxx"
BLING_CLIENT_SECRET = "xxxxxx"
```

6. Voltar à app, escolher origem **Bling**, clicar em **Autorizar no Bling**

Os tokens ficam guardados no Supabase, portanto **só precisa autorizar uma vez** (até desconectar manualmente).

---

**❓ Significado dos sinais**

- **Status:** ✅ Vencendo (markup alvo abaixo do menor concorrente — folga real) · 🟡 Risco (preço quase igual a concorrente) · ⚠️ Caro (markup acima do mercado, perde venda) · 🟧 Chão acima do mercado (custo+margem mínima já está acima do mercado, não há como competir sem renegociar fornecedor) · 🟥 Burn (concorrente abaixo do seu custo+imposto)
- **Procura:** 🔥 Muito Alta · 📈 Alta · ➡️ Média · 📉 Baixa
- **Atratividade:** índice 0-100 que combina Procura × Margem. Use para priorizar quais produtos comprar do fornecedor.
- **Recomendação:** 🚀 Investir/Repor · ✅ Manter / Investir leve · ✅ Investir com margem reduzida · 📉 Reduzir margem mínima · 🔻 Liquidar · ⏸️ Aguardar · ❌ Não comprar
""")


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
                st.link_button("🔐 Autorizar no Bling", url_auth, type="primary")
            else:
                # Conectado — mostrar status e botão para importar
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.success("✅ Bling conectado.")
                with col_b:
                    if st.button("🚪 Desconectar", help="Apagar tokens e exigir nova autorização"):
                        bling_desconectar()
                        st.rerun()

                if st.button("📥 Importar catálogo do Bling", type="primary"):
                    progresso = st.progress(0.0, text="A importar produtos...")
                    contador = st.empty()

                    def _cb(pagina, total):
                        # Estimativa visual: cada página são 100 produtos; cap de 50 páginas
                        pct = min(pagina / 50.0, 1.0)
                        progresso.progress(pct, text=f"Página {pagina} ({total} produtos)")
                        contador.caption(f"Recebidos {total} produtos até agora...")

                    produtos = bling_importar_catalogo(progresso_cb=_cb)
                    progresso.empty()
                    contador.empty()

                    if not produtos:
                        st.error("Nenhum produto retornado. Verifique se há produtos cadastrados no Bling.")
                    else:
                        df_base = pd.DataFrame([{
                            "Nome": i.get("nome", ""),
                            "Custo": round(float(i.get("precoCusto", 0) or 0), 2),
                            "Qtde": float((i.get("estoque") or {}).get("quantidade", 1) or 1),
                            "EAN": i.get("codigoBarra", ""),
                            "SKU": i.get("codigo", ""),
                            "Linha": (i.get("categoria") or {}).get("nome", "Geral"),
                            "ID": i.get("id", 0),
                        } for i in produtos])
                        # Limpeza básica
                        df_base["Custo"] = pd.to_numeric(df_base["Custo"], errors="coerce")
                        n_invalid = df_base["Custo"].isna().sum() + (df_base["Custo"] <= 0).sum()
                        df_base = df_base[df_base["Custo"].notna() & (df_base["Custo"] > 0)]
                        st.success(f"✅ {len(df_base)} produtos importados (de {len(produtos)} recebidos do Bling).")
                        if n_invalid > 0:
                            st.caption(f"ℹ️ {n_invalid} produtos ignorados por terem custo zero ou inválido.")
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
                rejeitados_total = {"usado": 0, "outlier_baixo": 0, "outlier_alto": 0, "irrelevante": 0}

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
                        margem_minima=margem_minima,
                        menor_concorrente=estrategias["menor_concorrente"],
                    )
                    recomendacao = recomendacao_investimento(status_codigo, score, row["Qtde"])

                    if status_codigo == "vencendo":
                        preco_sugerido = estrategias["preco_otimo"]
                    elif status_codigo in ("risco", "caro"):
                        preco_sugerido = estrategias["preco_competitivo"]
                    elif status_codigo == "chao_alto":
                        # Mercado está abaixo do nosso chão. O melhor que podemos fazer é
                        # vender ao Preço Mínimo — perdemos competitividade mas garantimos
                        # margem mínima de subsistência.
                        preco_sugerido = estrategias["preco_minimo"]
                    elif status_codigo == "burn":
                        preco_sugerido = estrategias["preco_minimo"]
                    else:
                        preco_sugerido = estrategias["preco_alvo_markup"]

                    lucro_unitario = preco_sugerido * (1 - imposto) - row["Custo"]
                    lucro_total = round(lucro_unitario * row["Qtde"], 2)
                    margem_real = (lucro_unitario / preco_sugerido * 100) if preco_sugerido > 0 else 0

                    concorrentes_ordenados = sorted(concorrentes, key=lambda x: x["preco"]) if concorrentes else []
                    loja_lider = concorrentes_ordenados[0]["loja"] if concorrentes_ordenados else "Sem dados"

                    # Pressão de mercado: quanto o Preço Sugerido ficou abaixo (ou acima) do Preço Markup.
                    # Negativo = mercado obrigou-me a baixar o preço alvo
                    # Zero    = consigo vender exactamente pelo markup que queria
                    # Positivo = consigo vender ACIMA do meu markup (raro, mercado folgado)
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
                        "Qtde": row["Qtde"],
                        "Custo": row["Custo"],
                        "Preço Markup": estrategias["preco_alvo_markup"],
                        "Menor Concorrente": estrategias["menor_concorrente"],
                        "Preço Sugerido": preco_sugerido,
                        "Pressão Mercado %": pressao_mercado,
                        "_concorrentes": concorrentes_ordenados,
                        "_mercado_competitivo": estrategias["mercado_competitivo"],
                        "N Concorrentes": len(concorrentes),
                        "Preço Mínimo": estrategias["preco_minimo"],
                        "Preço Competitivo": estrategias["preco_competitivo"],
                        "Preço Óptimo": estrategias["preco_otimo"],
                        "Margem Real %": round(margem_real, 1),
                        "Lucro Unitário": round(lucro_unitario, 2),
                        "Lucro Total": lucro_total,
                        "Status": status_label,
                        "_status_code": status_codigo,
                        "Score Procura": score,
                        "Procura": rotulo_procura,
                        "Recomendação": recomendacao,
                        # Atratividade = Score Procura × Margem Real ÷ 100 (resultado 0-100)
                        # Ex: Procura 80 e margem 30% → 80*30/100 = 24
                        "Atratividade": round(score * max(margem_real, 0) / 100, 1),
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
                st.session_state.df_final.attrs["timestamp"] = datetime.now()

                # Resumo dos filtros aplicados
                if any(rejeitados_total.values()):
                    msgs = []
                    if rejeitados_total["irrelevante"]:
                        msgs.append(f"🎯 {rejeitados_total['irrelevante']} resultados rejeitados (produto sem relação com o pesquisado)")
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

        # Métricas globais — calculadas com cuidado para serem matematicamente coerentes
        investimento = float((df_v["Custo"] * df_v["Qtde"]).sum())
        lucro_proj = float(df_v["Lucro Total"].sum())
        # ROI sobre o investimento real (apenas itens que existem em stock)
        roi = (lucro_proj / investimento * 100) if investimento > 0 else 0.0

        # Margem média PONDERADA pelo peso do investimento de cada produto.
        # Antes estava a fazer média simples — produtos baratos pesavam tanto como caros,
        # o que inflava o número quando havia muitos produtos pequenos com margem alta.
        # Fórmula: lucro total / receita total (onde receita = preço sugerido × qtde)
        receita_total = float((df_v["Preço Sugerido"] * df_v["Qtde"]).sum())
        margem_media = (lucro_proj / receita_total * 100) if receita_total > 0 else 0.0

        # Aviso sobre produtos sem stock: contam para Atratividade/Recomendação,
        # mas não contam para Investimento/Lucro/ROI (porque ainda não os comprou)
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
                "estas não contam para Investimento/Lucro/ROI mas mantêm Atratividade e Recomendação "
                "para você decidir se vale a pena trazer do fornecedor."
            )

        st.divider()
        st.subheader("📉 Análise Visual")

        grafico = st.selectbox("Tipo de gráfico:", [
            "1. Distribuição por Status",
            "2. Lucro por Marketplace",
            "3. Lucro por Categoria",
            "4. Top 20 — Atratividade (Procura × Margem)",
            "5. Top 20 — Lucro Total Projetado",
            "6. Distribuição de Atratividade por Categoria",
            "7. Posicionamento de Preço (Eu vs Mercado)",
            "8. Tabela: Recomendação por Categoria",
        ])

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
            fig = px.bar(
                top, x="Atratividade", y="Nome", orientation="h",
                color="Status", color_discrete_map=color_map,
                hover_data={"Score Procura": True, "Margem Real %": ":.1f", "Lucro Total": ":.2f"},
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
            fig.add_trace(go.Bar(name="Preço Markup (alvo ideal)", x=amostra["Nome"], y=amostra["Preço Markup"], marker_color="#9b59b6"))
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

        colunas_show = [
            "Nome", "Linha", "Qtde",
            "Custo", "Preço Markup",
            "Menor Concorrente",
            "Preço Sugerido", "Margem Real %", "Pressão Mercado %",
            "Lucro Total",
            "Status", "Procura", "Atratividade", "Recomendação",
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
                    help="O preço alvo IDEAL — calculado pela sua margem desejada, ignorando o mercado. "
                         "Fórmula: custo × (1 + markup) ÷ (1 - imposto).",
                ),
                "Menor Concorrente": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Menor preço entre os concorrentes confiáveis encontrados.",
                ),
                "Preço Sugerido": st.column_config.NumberColumn(
                    format=f"{moeda} %.2f",
                    help="Preço efectivo a praticar, escolhido pelo algoritmo conforme o status.",
                ),
                "Pressão Mercado %": st.column_config.NumberColumn(
                    "Δ Pressão",
                    format="%+.1f %%",
                    help="Quanto o Preço Sugerido se afasta do Preço Markup desejado, "
                         "por causa da concorrência.\n"
                         "• 0% = consigo praticar exactamente o preço que queria\n"
                         "• Negativo = mercado obrigou-me a baixar (perdi % do meu markup)\n"
                         "• Positivo = consigo vender ACIMA do meu markup (raro)",
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
            },
        )

        # ---------- PAINEL DE VERIFICAÇÃO ----------
        st.divider()
        st.subheader("🔍 Painel de Verificação de Concorrentes")
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

            # Cabeçalho de contexto
            ci1, ci2, ci3, ci4 = st.columns(4)
            ci1.metric("Custo", f"{moeda} {linha_inspect['Custo']:,.2f}")
            ci2.metric("Preço Markup", f"{moeda} {linha_inspect['Preço Markup']:,.2f}")
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
                    link_real = c.get("link") or ""
                    # Se o "link directo" é uma página agregadora do Google, é frágil — ignorar
                    if link_real and not _e_link_agregador_google(link_real):
                        return link_real, "directo"

                    # Identificar marketplace pelo nome da loja
                    fonte = (c.get("loja") or "").lower()
                    for dominio, template in MARKETPLACE_SEARCH_URL.items():
                        if dominio in fonte:
                            return template.format(q=quote_plus(nome_produto)), "marketplace"

                    # Último recurso: Google Shopping da região
                    domain = t.get("domain", "google.com")
                    gl = t.get("gl", "us")
                    hl = (t.get("lang") or "en")[:2]
                    return (
                        f"https://www.{domain}/search?tbm=shop"
                        f"&q={quote_plus(nome_produto)}&gl={gl}&hl={hl}&ncr=1"
                    ), "google"

                rows = []
                for i, c in enumerate(concorrentes_lista):
                    link, tipo = _link_ou_fallback(c, produto_inspect)
                    rows.append({
                        "Posição": f"#{i+1}",
                        "Loja": c["loja"],
                        "Preço": c["preco"],
                        "Rating": c.get("rating"),
                        "Reviews": c.get("reviews", 0),
                        "Link": link,
                        "Tipo": {"directo": "✅ directo", "marketplace": "🛒 marketplace", "google": "🔍 Google"}[tipo],
                    })
                df_conc = pd.DataFrame(rows)

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
                            help="Abre o anúncio. Quando a SerpAPI não devolve link directo "
                                 "(comum em Amazon Buy Box), redireciona para a busca interna "
                                 "do marketplace ou, em último recurso, para o Google Shopping da região.",
                        ),
                        "Tipo": st.column_config.TextColumn(
                            "Tipo",
                            help=(
                                "✅ directo = link directo do anúncio na SerpAPI; "
                                "🛒 marketplace = sem link directo, abre busca interna do próprio marketplace "
                                "(mais fiável); "
                                "🔍 Google = sem link nem marketplace conhecido, abre busca no Google Shopping "
                                "regional."
                            ),
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
