#!/bin/bash
set -e

mkdir -p /app/.streamlit

cat > /app/.streamlit/secrets.toml <<TOML
SUPABASE_URL = "${SUPABASE_URL:-}"
SUPABASE_ANON_KEY = "${SUPABASE_ANON_KEY:-}"
SUPABASE_KEY = "${SUPABASE_KEY:-}"
SUPABASE_JWT_SECRET = "${SUPABASE_JWT_SECRET:-}"
EMAIL_ORIGEM = "${EMAIL_ORIGEM:-}"
SENHA_APP = "${SENHA_APP:-}"
BLING_CLIENT_ID = "${BLING_CLIENT_ID:-}"
BLING_CLIENT_SECRET = "${BLING_CLIENT_SECRET:-}"
SITE_URL = "${SITE_URL:-}"
TOML

echo "Streamlit secrets.toml gerado a partir das variáveis de ambiente."
echo "Variáveis presentes:"
for var in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_KEY SUPABASE_JWT_SECRET BLING_CLIENT_ID SITE_URL; do
    if [ -n "${!var}" ]; then
        echo " - $var: ✓"
    else
        echo " - $var: ✗"
    fi
done

exec streamlit run app.py
