---
title: Viabilidade de Vendas
emoji: 🌎
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# Viabilidade de Vendas

SaaS de análise de preços e concorrência para lojas online.
Compara o seu catálogo com concorrentes confiáveis usando SerpAPI,
calcula margens, recomendações de compra e projecções de lucro.

**Demo público:** https://huggingface.co/spaces/VemBrincarComAGente/viabilidadedevendas

## Funcionalidades

- **Análise multi-região:** Brasil (BR), Portugal (PT), União Europeia (EU), USA
- **Importação do catálogo:**
  - Planilha Excel/CSV com mapeamento automático de colunas
  - Bling V3 via OAuth (apenas Brasil)
- **Detecção automática de marca** a partir do nome (50+ marcas em 6 categorias)
- **Coluna "Marca" opcional** na planilha (override da detecção)
- **2 modos de análise (Bling):**
  - Custo + margem (clássico) — calcula markup ideal
  - Preço de venda actual — compara preço já praticado com mercado
- **Filtros inteligentes:**
  - Vendedor confiável por região (whitelist)
  - Produto novo (rejeita usado, open box, peças avulsas)
  - Acessórios compatíveis (kit luzes LED, vasos, etc.)
  - Compra internacional (frete + taxas)
  - Outliers de preço
- **Recomendações automáticas:** Investir, Manter, Reduzir margem, Liquidar, Aguardar, Não comprar
- **Atualização de preços no Bling** directamente da app
- **Histórico de análises** persistido em Supabase com RLS
- **Login Google** com sessão persistida via `?sid=`

## Arquitectura

- **Frontend:** Streamlit
- **Backend:** Supabase (PostgreSQL com RLS)
- **Auth:** Google OAuth (PKCE manual) + JWT custom para Supabase
- **Deploy:** Hugging Face Spaces (Docker)
- **Externos:** SerpAPI (Google Shopping), Bling V3 API

## Estrutura do projecto

```
.
├── app.py                  # Aplicação principal (Streamlit)
├── requirements.txt        # Dependências Python
├── Dockerfile              # Container HF Spaces
├── start.sh                # Script de arranque (gera secrets.toml)
├── planilha_exemplo.xlsx   # Template Excel para utilizadores
├── README.md               # Este ficheiro
└── MUDANCAS.md             # Histórico de alterações
```

## Variáveis de ambiente (HF Spaces Secrets)

| Variável | Descrição |
|---|---|
| `SUPABASE_URL` | URL do projecto Supabase |
| `SUPABASE_ANON_KEY` | Chave anónima Supabase |
| `SUPABASE_KEY` | Chave de service role |
| `SUPABASE_JWT_SECRET` | Legacy JWT Secret (para assinar JWTs custom) |
| `EMAIL_ORIGEM` | Email para envio de notificações |
| `SENHA_APP` | Password app do Gmail |
| `BLING_CLIENT_ID` | Client ID Bling V3 OAuth |
| `BLING_CLIENT_SECRET` | Client Secret Bling V3 OAuth |
| `SITE_URL` | URL pública da app (para callback OAuth) |

## Schema Supabase

Todas as tabelas têm RLS activa com policies que filtram por `auth.jwt() ->> 'sub'`:

- `user_sessions` — sessões persistidas via `sid`
- `user_preferences` — preferências por utilizador
- `bling_tokens` — tokens OAuth Bling por utilizador
- `analises` — registo de cada análise corrida
- `historico_precos` — snapshots de preços de concorrentes

## Como correr localmente

```bash
git clone https://github.com/djeanrj/An-lise-de-pre-os.git
cd An-lise-de-pre-os
pip install -r requirements.txt

mkdir -p .streamlit
cat > .streamlit/secrets.toml <<TOML
SUPABASE_URL = "..."
SUPABASE_ANON_KEY = "..."
# ... etc
TOML

streamlit run app.py
```

## Licença

MIT
