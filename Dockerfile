FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Permissões para o user 'user' (HF Spaces correm com este user, UID 1000)
RUN useradd -m -u 1000 user && \
    mkdir -p /app/.streamlit && \
    chown -R user:user /app
USER user

# Variáveis Streamlit
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=7860 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 7860

# Script de arranque que gera secrets.toml a partir das variáveis de ambiente
# (HF Spaces injecta secrets como env vars). Assim o st.secrets[...] do código
# original continua a funcionar sem alterações.
COPY --chown=user:user start.sh /app/start.sh

CMD ["/bin/bash", "/app/start.sh"]
