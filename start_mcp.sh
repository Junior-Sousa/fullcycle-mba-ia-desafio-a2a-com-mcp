#!/bin/bash
set -e

# Instala as dependências se necessário
pip install -q fastapi uvicorn httpx mcp pydantic

# Gera o arquivo .env se não existir
if [ ! -f ".env" ]; then
    echo "Gerando REQUEST_STATE_SECRET em .env..."
    python3 -c "import secrets; print(f'REQUEST_STATE_SECRET={secrets.token_hex(32)}')" > .env
fi

# Carrega as variáveis de ambiente
set -a
source .env
set +a

echo "Iniciando Servidor MCP na porta 7301..."
PYTHONPATH=servidor-mcp python3 -m uvicorn app:app --port 7301 --app-dir servidor-mcp
