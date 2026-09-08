# 📋 ESPECIFICAÇÃO TÉCNICA - Viabilidade de Vendas

**Versão:** Beta 1.0  
**Última atualização:** Setembro 2026  
**Status:** Em desenvolvimento

---

## 📌 RESUMO EXECUTIVO

Aplicação SaaS para análise de viabilidade comercial de produtos (inicialmente LEGO, agora genérica para qualquer categoria). Permite revendedores analisar preços de mercado, atratividade por região, integração com Bling (Brasil), e ranking de produtos por potencial de mercado.

---

## 🏗️ ARQUITETURA

### Stack Técnico
- **Frontend:** Streamlit (Python)
- **Backend:** Supabase (PostgreSQL + Auth)
- **APIs:** SerpAPI (busca Google), Google Trends (interesse), Bling (ERP Brasil)
- **Hospedagem:** Hugging Face Spaces + GitHub

### Credenciais/Chaves
- **Supabase:** `get_supabase_client()` (configurado via HF Secrets)
- **SerpAPI:** User traz sua própria chave (guarda em preferências)
- **Bling:** OAuth integrado (Brasil apenas)

---

## ✅ FUNCIONALIDADES IMPLEMENTADAS

### 1. AUTENTICAÇÃO & ONBOARDING BETA
- **Google OAuth** integrado (Supabase Auth)
- **Sistema de convite beta:** 20 códigos gerados, validação em `beta_invites`
- **Fluxo novo user:**
  1. Google OAuth
  2. Valida código convite (BETA-ABC123)
  3. Marca código como usado
  4. Auto-login com sessão persistente
- **Tabela:** `beta_invites` (code, used_by_email, used_at, expires_at=NULL)

### 2. ANÁLISE DE PRODUTOS
- **Upload:** Planilha Excel com SKU | Marca | Nome | Custo de Compra
- **Busca:** Google Shopping + Google Immersive Product (SerpAPI)
- **Processamento:**
  - Query: `"Marca SKU Nome"` → Google Shopping
  - Expansão: PIDs (product IDs) → URLs reais das lojas
  - Cache: 24h para queries, permanente para PIDs

### 3. FILTRAGEM & VALIDAÇÃO
- **Regiões:** Brasil, Portugal, USA (com domínios específicos: .com.br, .pt, .com)
- **Whitelist:** Apenas lojas confiáveis (LEGO.com, Amazon, FNAC, Continente, etc)
- **Blacklist:** Lojas internacionais, suspeitas, marketplaces não-confiáveis
- **Detecção de anúncios internacionais disfarçados:** Keywords como "building-toy", "brinquedo-de-ces"
- **Validação de compatibilidade:** Para LEGO, filtra acessórios vs produtos principais

### 4. PREÇOS & CÁLCULOS
- **Campos capturados:** Preço unitário + Frete
- **Cálculos:**
  - Preço total = Preço + Frete
  - Margem = (Preço total - Custo) / Preço total × 100
  - Lucro = Preço total - Custo
  - Atratividade = Procura × Margem ÷ 100

### 5. INTERNACIONALIZAÇÃO
- **Idiomas:** Português Brasil, Português Portugal, English (USA)
- **Região automática:** Brasil → pt-BR, Portugal → pt-PT, USA → en
- **Dicionário:** ~150 strings traduzidas em `idiomas` dict

### 6. BLING SYNC (Brasil apenas)
- **OAuth:** Integração com Bling ERP
- **Importação:** Lista de produtos do Bling
- **Mapeamento:** SKU local → Bling SKU
- **Nota:** Indisponível em Portugal e USA (Termos ajustados por região)

### 7. HISTÓRICO & PERSISTÊNCIA
- **Sessões:** `user_sessions` (Supabase) com tokens + user info
- **Preferências:** `user_preferences` (região default, Bling tokens, etc)
- **Histórico:** Cada análise guardada com timestamp

### 8. ÍNDICE DE ATRATIVIDADE (CURRENT)
- **Função:** `calcular_indice_potencial_mercado(search_volume, cpc, competition)`
- **Fórmula:** `(search_volume × 0.60) + (cpc × 0.25) + (competition × 0.15)`
- **Output:** Índice 0-100 + Nível (Muito Baixo, Baixo, Moderado, Alto, Muito Alto)
- **Usado:** Quando produto é lançamento / sem concorrentes

### 9. TERMOS & DOCUMENTOS LEGAIS
- **Documentos:** Privacidade, Termos de Uso, Cookies (por região)
- **Armazenamento:** Dict `DOCUMENTOS_LEGAIS` (PT-BR, PT-PT, EN)
- **Exibição:** Aba "📜 Documentos Legais" com expanders
- **Condicionais:** Bling mencionado só em BR (Termos ajustados)

### 10. TRADUÇÃO COMPLETA (EN)
- **43+ strings** implementadas
- **Helper:** `tx(key, default)` com fallback automático
- **Sem regressões:** Sistema antigo de preferências mantido

### 11. OTIMIZAÇÕES
- **Cache SerpAPI:** 5 expansões pagas/produto (limite cap)
- **Cache inteligente:** Reutiliza resultados dentro de 24h
- **Logs diagnóstico:** `[PLANO-B]`, `[US-OPT]`, `[PRECO-DBG]` para debug

### 12. SISTEMA ANTIGO DE SERPAPI KEY (MANTIDO)
- **Storage:** Preferências do user (`api_key`)
- **Recuperação:** Auto-carrega na primeira vez
- **Fluxo:** User insere chave na sidebar → guarda em preferências → persiste

### 13. RANKING DE ATRATIVIDADE POR REGIÃO ✅ IMPLEMENTADO
- **Nova aba:** "📊 Ranking de Atratividade" (entre Histórico e Documentos Legais)
- **Objetivo:** Prever quais produtos comprar para quais regiões, mesmo para lançamentos sem concorrência
- **Fonte de dados:** Google Trends (`pytrends`), não SerpAPI — evita gastar créditos do user
- **Método técnico (IMPORTANTE):**
  - Usa `interest_by_region()` — **UMA única chamada** ao Trends que devolve todos os
    estados do Brasil já normalizados/comparáveis entre si
  - ⚠️ NÃO fazer chamadas separadas por estado e depois média — o Trends normaliza
    0-100 dentro do universo pedido em cada chamada, logo comparar chamadas diferentes
    dá números incorrectos
  - **Estado filtrado** → valor directo daquele estado (da mesma chamada)
  - **Região filtrada** (Norte/Nordeste/Centro-Oeste/Sudeste/Sul) → **SOMA** dos valores
    dos estados daquela região (não é média — reflecte interesse agregado real da região)
  - **Sem filtro** → valor nacional agregado (`interest_over_time`)
- **Extração de palavras-chave:**
  - Função `extrair_palavras_chave(texto, marca, max_palavras)`
  - Remove: stop words PT (~150 palavras), números puros (SKU), nome da marca
  - Testado com casos reais: "Carro Esportivo Dodge Challenger SRT Hellcat" → 
    `['speed','champions','carro','esportivo','dodge','challenger','srt','hellcat']`
  - "do", "ao", "vs" corretamente removidos (confirmado com exemplos do user)
- **Termo de busca no Trends:** `"{marca} {4 primeiras keywords}"` (termos curtos funcionam melhor)
- **Filtros em cascata (UI):**
  - Região → Estado (Estado mostra só os da região escolhida)
  - Estado escolhido sem região → infere e mostra a região automaticamente
  - Reset Estado → volta ao ranking da Região (ou Nacional se região também vazia)
  - Reset Região → Estado volta a mostrar todos os 27
  - Users pode ir direto ao Estado sem escolher Região primeiro
- **Cache:** 24h por termo+geo (`st.cache_data`), evita chamadas repetidas ao Trends
- **Funções principais:**
  - `buscar_trends_por_estado(termo, geo_pais)` — 1 chamada, devolve nacional + por-estado
  - `geo_code_para_estado(estado)` — nome → código ISO (ex: "São Paulo" → "BR-SP")
  - `calcular_atratividade_regional(sku, marca, nome, regiao_br, estado_br, geo_pais)` — 
    calcula o valor certo (estado/soma região/nacional) para 1 produto
  - `calcular_ranking_atratividade_regiao(produtos, ...)` — processa lista completa,
    devolve DataFrame ordenado por Atratividade desc
- **Mapeamentos:**
  - `REGIOES_BRASIL` — 5 regiões → lista de estados
  - `ESTADO_PARA_REGIAO` — inverso, para inferir região a partir do estado
  - `GEO_CODES_BRASIL_ESTADOS` — nome do estado → código ISO 3166-2 (BR-SP, BR-RJ, etc)
  - `TODOS_OS_ESTADOS` — lista alfabética dos 27 estados
- **UI/Resultado:**
  - Upload da mesma planilha (SKU, Marca, Nome, Custo) — detecção automática de colunas
  - Tabela com coluna de progresso visual (Atratividade)
  - Top 3 destacado em métricas
  - Exportação CSV
- **Dependência adicionada:** `pytrends` (requirements.txt)
- **Limitação conhecida:** só implementado para Brasil (5 regiões + 27 estados). 
  Portugal/USA usam só nível nacional por agora (sem subdivisão regional).

---

## ❌ O QUE FALTA IMPLEMENTAR

### FASE 1 - RANKING DE ATRATIVIDADE POR REGIÃO — ✅ CONCLUÍDA (ver secção 13 acima)
Itens que ainda podem ser refinados dentro desta fase:
- [ ] Testar com casos reais de lançamento (planilha de LEGOs sem concorrência)
- [ ] Validar se `interest_by_region` devolve dados suficientes para termos muito de nicho
- [ ] Considerar extensão para Portugal (distritos) e USA (estados) no futuro
- [ ] Guardar histórico de rankings gerados (atualmente não persiste, só sessão)

### FASE 2 - COMERCIALIZAÇÃO
- [ ] Planos pagos (Stripe/MercadoPago)
- [ ] Sistema de códigos de convite com expiração
- [ ] Domínio próprio (não HF Space)
- [ ] Dashboard de admin (gestão de users, quotas, etc)

### FASE 3 - MELHORIAS UX
- [ ] Gráficos de atratividade por região
- [ ] Comparativas: "Melhor em qual região?"
- [ ] Sugestões automáticas: "Este produto é top 3 em Sudeste"
- [ ] Exportação de ranking (PDF/Excel)

---

## 📊 ESTRUTURA DE DADOS

### Planilha Input
```
SKU | Marca | Nome | Custo de Compra
77237 | LEGO | LEGO Speed Champions... | 150.00
21251 | LEGO | LEGO Minecraft... | 89.50
```

### Tabela: beta_invites
```
id | code | created_at | used_by_email | used_at | expires_at
uuid | BETA-ABC123DEF456 | 2026-09-06 | user@email.com | 2026-09-06 | NULL
```

### Tabela: user_settings (criada, ainda com uso limitado)
```
id | user_id | serpapi_key | created_at | updated_at
uuid | uuid | xxx_yyy_zzz | 2026-09-06 | 2026-09-06
```

### Tabela: user_preferences
```
user_id | regiao_default | serpapi_key | termos_aceites_br | scope_pt
uuid | BR | (preferências) | true | true
```

### Tabela: user_sessions
```
sid | user_id | user_session_json | created_at | updated_at
uuid | uuid | {...} | 2026-09-06 | 2026-09-06
```

---

## 🔑 DECISÕES TÉCNICAS

1. **Google OAuth obrigatório:** Simplifica auth, integra bem com Supabase
2. **SerpAPI com chave pessoal:** User controla gastos
3. **Cache 24h:** Balance entre frescura e economia de créditos
4. **Sistema antigo de preferências mantido:** Não substitui por user_settings (Trends ainda não implementado)
5. **Termos por região:** Compliance LGPD (BR), GDPR (PT/EU), CCPA (USA)
6. **Híbrido Trends + SerpAPI:** Trends = interesse, SerpAPI = concorrentes/preços

---

## 🐛 BUGS CONHECIDOS / RESOLVIDOS

| Bug | Status | Solução |
|-----|--------|---------|
| LEGO 10281 "Luz LED" filtrado incorretamente | ✅ RESOLVIDO | Expandir keywords LED |
| Simba 43243 anúncio internacional disfarçado | ✅ RESOLVIDO | Detectar keywords internacionais |
| Consumo SerpAPI descontrolado | ✅ RESOLVIDO | Cap 5 expansões/produto |
| 2 campos SerpAPI na sidebar | ✅ RESOLVIDO | Manter sistema antigo |
| Chave SerpAPI sumia se erro ao salvar | ✅ RESOLVIDO | Manter em session_state |
| Sem indicador de atratividade sem concorrentes | ✅ RESOLVIDO | Mostrar Índice de Potencial |

---

## 📱 FLUXO DO USER (Atual)

```
1. Abre app → Google OAuth
2. Novo user → valida código convite
3. Login → recupera SerpAPI key de preferências
4. Sidebar: escolhe Região
5. Upload: planilha com produtos
6. Clica: "Analisar"
7. App busca cada produto:
   - Google Shopping
   - Expansão de PIDs
   - Filtragem (whitelist/blacklist)
   - Cálculo de preços/margens
8. Resultado: tabela com concorrentes + preços
9. Se sem concorrentes: mostra Índice de Potencial
10. Histórico: guarda análise
```

---

## 🚀 PRÓXIMO PASSO (IMEDIATO)

**IMPLEMENTAR: Ranking de Atratividade por Região**

Entrada: planilha (SKU, Marca, Nome, Custo)
Saída: Ranking ordenado por atratividade na região selecionada

Ferramentas:
- Google Trends API (capturar interesse)
- Mapeamento geo (regiões/estados)
- Stop words PT (~100 palavras)
- Extração automática de keywords

---

## 📞 CONTATO / NOTAS

**User:** djeanrj (Lisboa, Portugal)  
**Organização:** VemBrincarComAGente (LEGO revendedor, agora genérico)  
**Status:** Beta para 20 users  
**SerpAPI:** Chaves pessoais dos users

---

## 📄 CHANGELOG

| Data | Versão | O quê |
|------|--------|-------|
| 2026-05-30 | 0.1 | Inicio desenvolvimento, bugs LEGO/filtros |
| 2026-06-09 | 0.2 | Otimização SerpAPI, GDPR/LGPD docs |
| 2026-06-30 | 0.3 | Tradução EN completa, onboarding beta |
| 2026-09-06 | 0.4 | Índice de atratividade, correção SerpAPI key |

---

**Documento centralizado. Consulte sempre antes de continuar desenvolvimento!**
