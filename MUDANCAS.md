# Mudanças no `app.py` — Resumo das Correções e Melhorias

## 🆕 Sessão Maio 2026 (parte 3) — Correções Brasil + drift warning

### Bug crítico: preços incorretos no Brasil
A SerpAPI no Brasil devolve **valor de parcela** em `extracted_price` (ex: "12x de R$ 33,34" = R$ 33,34) e o **preço total real** em `extracted_total`. A app estava a usar `extracted_price`, mostrando R$ 33,34 quando o real era R$ 133,34.

**Solução:** usar `max(extracted_price, extracted_total)`. Quando há `shipping` explícito (formato "+ R$ X,XX"), descontar do total para obter preço base do produto. Mantém compatibilidade com mercados sem parcelas (EU/USA) onde os 2 são iguais.

### Aviso de drift na tabela
Nova coluna "⚠️" marca preços 25%+ abaixo da mediana — provável snapshot SerpAPI desactualizado.

## 🆕 Sessão Maio 2026 (parte 2) — Plano B: links directos universais

### Problema resolvido
A SerpAPI no engine `google_shopping` **não devolve link directo da loja** em PT/UE (devolve apenas link para Google Shopping). Resultado: links inúteis para o utilizador.

### Solução: Plano B com cache 30 dias

**1. Engine `google_immersive_product`:**
- Para cada item da SerpAPI com `product_id`, 2ª chamada usando `immersive_product_page_token`
- Devolve `product_results.stores[]` com `name`, `link`, `price`, `total`, `extracted_price`
- Até 13 lojas por `product_id` com `more_stores=1`

**2. Cache global Supabase (`cache_product_sellers`):**
- Chave: `product_id` da SerpAPI
- TTL: 30 dias
- Partilhada entre utilizadores (apenas URLs públicas, sem dados sensíveis)
- RLS: leitura aberta, escrita por autenticados

**3. Expansão automática:**
- Cada item forte da SerpAPI expande-se em N concorrentes (todas as stores do `product_id`)
- Resultado: 1-3 itens originais → 10-14 concorrentes com link directo ao produto

**4. Funcionamento:**
- ✅ Funciona para qualquer marca/categoria (não hard-coded para LEGO)
- ✅ Zero mapping manual de URLs
- ✅ Cache reduz chamadas SerpAPI nas análises seguintes
- ✅ Match seller vs source com normalização (acentos, espaços, TLDs)

### Aviso de drift de preço
- Coluna "⚠️" na tabela de concorrentes
- Marca preços 25%+ abaixo da mediana (provavelmente snapshot SerpAPI desactualizado)
- Tooltip explica ao utilizador para confirmar no link

### Notas importantes (Dezembro 2025)
- Google descontinuou o endpoint legado `google_product` ("The Google Product service is no longer offered by Google")
- Alternativa oficial: `google_immersive_product` (implementada)
- Google processou SerpAPI em Dezembro 2025 — serviço continua a funcionar mas tem futuro incerto

### Limpeza de filtros
- Removidos mappings de URLs inventados/não validados (capytoys, papelariaencantada com `/loja/`, marcelofonte.pt com DNS inexistente)
- Mantidos como fallback apenas URLs validados manualmente: Worten, Continente, Marcelo Fonte (Universo Encantado), Amazon ES/DE/IT/FR/NL/BR/COM
- Loja própria e revendedores particulares (eBay, Etsy, Wallapop, Vinted, OLX) blacklisted globalmente
- Loja "loja dos brindes" blacklisted (vende brindes corporativos, não LEGO/retalho)
- Loja "you get" blacklisted (não tem link directo fiável)

### Classificação de relevância (forte/fraco/rejeitar)
- Nova função `classificar_relevancia` substitui `titulo_relevante` (que vira wrapper)
- **forte**: marca + SKU exacto no título → tabela principal (decisões da app)
- **fraco**: marca confirmada mas SKU diferente → expander "Possíveis similares" (informativo)
- **rejeitar**: sem marca ou totalmente irrelevante → não mostra
- Decisões (Status, Preço Sugerido, métricas) usam APENAS fortes

### Expander "Possíveis similares"
- Mostra: #, Loja, Preço (?), Link
- Título oculto (sempre diferente, gera confusão)
- "(?)" no header do preço indica "a confirmar"
- Tooltips explicam que o preço pode não ser do produto procurado

### Filtros adicionais
- Equivalências PT-BR ↔ PT-PT ↔ EN: `buquê`↔`bouquet`, `icons`↔`creator`, etc.
- "Damaged Box", "Open Box", "Damaged packaging" rejeitados como "usado"
- Filtro anti-fallback Google: links `google.com/shopping/...` e `udm=28` rejeitados

## 🆕 Sessão Maio 2026 — SaaS-ready

### Autenticação e sessão
- **Login Google PKCE manual** (Supabase Auth com `?code=`) — fluxo customizado
- **Sessão persistida via `?sid=`** na URL (sobrevive a iframe HF Spaces)
- **Bling OAuth** com state encoding (sid via callback)
- **JWT custom assinado** com `SUPABASE_JWT_SECRET` (HS256) para RLS

### Segurança (RLS — Phase 2)
- RLS activa em todas as tabelas: `user_sessions`, `user_preferences`, `bling_tokens`, `analises`, `historico_precos`
- Policies: `auth.jwt() ->> 'sub' = user_id` (com cast UUID→TEXT onde necessário)
- Defesa em profundidade: RLS + filtros Python `.eq("user_id", uid)`
- `user_id` adicionado a tabelas `analises` e `historico_precos`

### Bling V3 (Brasil)
- OAuth completo (autorizar, importar catálogo, actualizar preços)
- **2 modos de análise:**
  - Custo + margem (clássico)
  - Preço de venda actual (compara com mercado, sem precisar de custo)
- Atualização de preços via **PATCH** (não PUT — evita problema de campos customizados)
- Erro detalhado quando Bling rejeita

### Detecção de marca
- Lista expandida: ~50 marcas em 6 categorias (Brinquedos, Bebés, Higiene, Electrónica, Casa, Pet)
- Detecção automática no nome do produto
- Coluna **"Marca" opcional** na planilha (override da detecção)
- Marca usada nas consultas SerpAPI (`LEGO 10280` em vez de `10280`)
- Marca exigida no título dos resultados (filtra falsos positivos)

### Selector de produtos
- Após carregar catálogo, utilizador escolhe quais produtos analisar
- Checkbox geral para marcar/desmarcar todos
- Edição inline de custo/preço de venda
- Economia de chamadas SerpAPI

### Filtros SerpAPI
- **Whitelist regional** expandida (~50+ lojas confiáveis BR/PT/EU/US)
- **Detecção de vendedor** com normalização (acentos, espaços, TLDs)
- **Acessórios compatíveis** (kits LED, vasos, expositores) — rejeitados
- **Compra internacional** (frete + taxas) — rejeitados por região
- **Outliers de preço** com slider configurável (% do custo)

### Links de concorrentes
- LEGO.com → URL directa do produto: `lego.com/pt-pt/product/<SKU>`
- Outras lojas → URL de busca dentro da loja (com `marca + SKU`)
- Rejeitar links Google Shopping (`google.com/shopping/...`)
- Fallback para ~25 lojas portuguesas/europeias mapeadas

### Persistência de preferências
- Termos aceites
- Chave SerpAPI
- Origem dos dados (Planilha/Bling)
- **Região default** (BR/PT/EU/US)
- **Âmbito PT** (Apenas Portugal / União Europeia)
- **Modo análise Bling** (custo_margem / preco_venda)

### Tutorial multi-língua
- 3 versões: pt-BR, pt-PT, en (consoante região seleccionada)
- Guia completo do Bling (~30 min) para Brasil
- Nota sobre drift SerpAPI (~1-5%)

### Deploy
- **Hugging Face Spaces** (Docker)
- start.sh gera secrets.toml a partir de env vars
- Variáveis: SUPABASE_*, BLING_*, EMAIL_*, SITE_URL

## 🐛 Bugs corrigidos

### 1. SMTP com URL inválida
**Antes:** `smtplib.SMTP("://gmail.com", 587, timeout=10)` — esta string nunca podia conectar.
**Depois:** `smtplib.SMTP("smtp.gmail.com", 587, timeout=10)` — endereço correto.

### 2. Endpoint da API Bling errado
**Antes:** `requests.get("https://bling.com.br", ...)` — homepage do site, não API.
**Depois:** `requests.get("https://api.bling.com.br/Api/v3/produtos", ...)` com header `Accept: application/json`. ⚠️ Nota: a API V3 do Bling usa OAuth2, portanto é provável que o token simples já não funcione — testar com token gerado pelo fluxo OAuth.

### 3. Parsing de preço só funcionava em formato BR
**Antes:** `.replace('.','').replace(',','.')` — quebra para preços em formato US (`$1,234.56` virava `1.234.56`).
**Depois:** função `parse_preco()` consciente do formato regional (BR/EU usa vírgula decimal; US usa ponto decimal). Além disso, agora usamos preferencialmente o campo `extracted_price` da SerpAPI, que já vem como número.

### 4. Filtro de moeda excluía resultados válidos
**Antes:** `t["moeda"] in str(it.get('price',''))` — exigia que o símbolo da moeda estivesse na string. Em US o símbolo `$` aparecia em strings como "Was $X" e contaminava o resultado; em PT/BR muitos resultados vinham sem símbolo na string `price` (vinham apenas em `extracted_price`).
**Depois:** já não filtramos por moeda — confiamos no `extracted_price` da SerpAPI, que já está normalizado.

### 5. Cálculo de margem com imposto hardcoded
**Antes:** `( (df_v['Preço Sugerido']*(1-0.04)) - df_v['Custo'] ) / df_v['Preço Sugerido']` — usava `0.04` em vez do imposto configurado pelo utilizador.
**Depois:** o imposto fica armazenado em `df.attrs["imposto"]` e é usado em todos os cálculos de margem real.

### 6. Fórmula de preço-alvo ignorava o imposto
**Antes:** `custo * (1 + markup)` — se o markup era 70% e o imposto 15%, o lucro real após imposto era apenas ~44%.
**Depois:** `custo * (1 + markup) / (1 - imposto)` — garante que o markup desejado é o lucro real após imposto.

### 7. `identificar_coluna` retornava 0 quando nada batia
**Antes:** retornava sempre `0` em caso de falha, fazendo o `selectbox` cair sempre na primeira coluna mesmo quando não havia match.
**Depois:** retorna `-1` por defeito; o caller decide o fallback explicitamente. Também faz match exato antes de match por substring para reduzir falsos positivos.

### 8. Heurística de "tendência" sem base real
**Antes:** `"📈 Ascendente" if any("sale" in str(it).lower() for it in validos) else "➡️ Flat"` — dizia "ascendente" sempre que houvesse uma palavra "sale" no JSON, o que é o oposto de tendência.
**Depois:** removido (era ruído). Em vez disso, calculamos um **Score de Procura 0-100** baseado em sinais reais (nº de vendedores, reviews acumuladas, presença de tags promocionais).

### 9. Falha numa busca derrubava a corrida toda
**Antes:** se a SerpAPI lançava exceção, o `for` parava sem feedback.
**Depois:** cada produto está dentro de `try/except` com warning específico, e a corrida continua.

### 10. Default `df_base['Mercado'] = round(row['Custo']*2.2, 2)` quando não havia dados
**Antes:** quando a busca não retornava nada, o app inventava `2.2x` o custo como "preço de mercado", o que falsificava todos os gráficos e métricas.
**Depois:** quando não há dados, `Menor Concorrente = None`, status fica `❔ Sem dados`, e a recomendação reflecte isso.

---

## ✨ Funcionalidades novas

### A. Planilha de exemplo descarregável
Botão "📥 Baixar planilha de exemplo" mostra um Excel com 12 produtos preenchidos, formatação profissional e uma aba de **Instruções**. O utilizador pode usar como template.

### B. Auto-detecção de colunas com fallback explícito
A função `identificar_coluna()` cobre mais variantes (`produto / nome / item / name / descrição / descricao`, etc.) e mostra ao utilizador o mapeamento sugerido — que pode corrigir antes de avançar. Há também uma pré-visualização dos dados carregados (`expander`).

### C. Limpeza automática de dados inválidos
Linhas com custo ausente, zero ou negativo são removidas e o utilizador é avisado quantas saíram.

### D. Whitelist + Blacklist por região
Em vez de só uma blacklist (que deixa passar tudo o que não for explicitamente proibido), agora há **whitelist regional** com os marketplaces sediados em cada zona:

- **Brasil:** Mercado Livre, Amazon BR, Magalu, Americanas, Casas Bahia, Fast Shop, Kabum, Centauro, etc.
- **Portugal-only:** Worten, Fnac PT, El Corte Inglés, PCDiga, Auchan, Mediamarkt PT, etc.
- **União Europeia:** PT + Espanha, Alemanha, Itália (incluindo `kidinn.com`, `vendiloshop.com`), França, Holanda + multipaís EU como `tradeinn.com`.
- **EUA:** Amazon, eBay, Walmart, Target, Best Buy, Newegg, B&H, etc.

O resultado é só mostrado se o vendedor estiver na whitelist da região E não estiver na blacklist. eBay continua como pediste: só elegível em US.

### E. Quatro estratégias de preço por produto
Em vez de "um preço sugerido", agora cada produto traz:

- **Preço Mínimo** — chão (custo + imposto + margem mínima configurável). Nunca vendemos abaixo disto.
- **Preço Competitivo** — 2% abaixo do concorrente mais barato confiável (se respeitar o chão).
- **Preço Óptimo** — 2% abaixo do **2º** mais barato. Maximiza margem mantendo competitividade real.
- **Preço Mediana** — preço de mercado (mediana dos concorrentes).

O **Preço Sugerido** final é escolhido automaticamente baseado no status:
- Status ✅ Vencendo → usa Preço Óptimo (porque há gordura)
- Status 🟡 Risco / ⚠️ Caro → usa Preço Competitivo (precisa undercutar)
- Status 🟥 Burn → usa Preço Mínimo (chão; alerta para renegociar fornecedor)

### F. Score de Procura 0-100 (substitui "Procura: Alta/Média/Baixa")
Calculado a partir de:
- **Nº de vendedores únicos** (até 35 pontos) — mais vendedores = produto validado pelo mercado
- **Reviews acumuladas** (até 40 pontos, escala log) — popularidade real
- **Tags promocionais** (até 10 pontos) — produto em destaque
- **Bonus** (15 pontos) se há ≥3 vendedores E ≥50 reviews

Mapeado para rótulos: 🔥 Muito Alta / 📈 Alta / ➡️ Média / 📉 Baixa.

### G. Recomendação de investimento
Coluna **"Recomendação"** combina status + procura + stock atual:

- 🚀 **Investir / Repor estoque** — alta procura + preço competitivo
- ⚖️ **Renegociar fornecedor** — alta procura mas preço fica acima do mercado
- ✅ **Manter / Investir leve** — procura média, status verde
- 🔻 **Liquidar estoque** — procura baixa mas há stock parado
- ⏸️ **Aguardar / Não comprar** — procura baixa, sem stock
- ❌ **Não investir** — burn (não cobre custos)
- ❔ **Sem dados de mercado** — busca não retornou concorrentes confiáveis

### H. Status com 4 níveis (não 3)
Antes: ✅ / ⚠️ / 🟥. Agora: ✅ Vencendo / 🟡 **Risco** (preço a <5% do concorrente) / ⚠️ Caro / 🟥 Burn — exactamente o que pediste ("estou em risco quando o preço é praticamente igual ao do concorrente mais próximo").

### I. Gráficos novos (8 ao todo)
Os 5 originais foram mantidos e refinados, e adicionei 3:

- **6. Top 10 Oportunidades de Lucro** — barra horizontal com os produtos que mais lucro projectam (focar esforço aqui).
- **7. Posicionamento de Preço (Eu vs Mercado)** — barras agrupadas: Preço Sugerido vs Menor Concorrente vs Mediana. Vê-se de relance onde estás.
- **8. Cobertura de Estoque vs Procura** — scatter colorido pela recomendação. Onde reforçar / onde liquidar.

A **Matriz Investimento (Margem × Procura)** agora tem linhas de referência (margem 20%, procura 45) para identificar o quadrante "alta margem + alta procura".

### J. ROI projetado nas métricas
Adicionei uma 4ª métrica no topo: **ROI = Lucro Projetado / Investimento**. Mais útil que o lucro absoluto para comparar cenários.

### K. Pesquisa SerpAPI mais profissional
- Pesquisa primeiro por **EAN** (mais preciso) e só faz fallback para nome se EAN não retornar nada
- `num=30` em vez do default 10 — mais resultados para filtrar
- Match de domínio por `urlparse(link).netloc` — evita falsos positivos do filtro antigo (`'ebay' in link` apanhava qualquer URL com "ebay" em qualquer parte)
- Delay de 0.3s entre chamadas para não saturar a API
- Erros da API mostrados como warning sem matar a corrida

### L. Persistência do imposto/markup
Os parâmetros usados na corrida são guardados em `df.attrs` para que a métrica de margem real esteja sempre coerente com o que foi configurado.

---

## ⚠️ O que ficou de fora (e porquê)

- **Tendência de preço ao longo do tempo**: a SerpAPI dá só snapshot. Para ter tendência real seria preciso guardar histórico em base de dados (SQLite/Supabase) e correr a análise periodicamente. Posso ajudar a montar isto numa próxima iteração se quiseres.
- **Verificação real de "vendedor sediado na região"**: continuamos a fazer isto via domínio do site, que é uma boa heurística mas não é 100%. Verificação verdadeira exigia clicar em cada vendedor do Mercado Livre/Amazon e ler o endereço fiscal, o que é caro e frágil.
- **Bling V3 OAuth2**: deixei o endpoint correcto mas o fluxo OAuth completo (redirect, refresh token, etc.) não cabe num único `requests.get`. Se quiseres integrar mesmo, posso preparar um módulo separado.

---

## 🚀 Próximos passos sugeridos

1. **Cache de resultados** com `@st.cache_data` por `(EAN, região)` para não queimar créditos SerpAPI ao reanalisar.
2. **Histórico em base de dados** (SQLite local ou Supabase grátis) para teres tendência real de preços ao longo do tempo.
3. **Alertas por email** quando um produto ficar em status 🟥 Burn ou aparecer um novo concorrente abaixo do preço mínimo.
4. **Sincronização de volta para o Bling** (atualizar preços de venda automaticamente).
