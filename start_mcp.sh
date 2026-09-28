#!/bin/bash
set -e

if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

if [ -z "$REQUEST_STATE_SECRET" ]; then
    echo "Erro: REQUEST_STATE_SECRET não definido. Rode ./setup.sh primeiro."
    exit 1
fi

echo "Iniciando Servidor MCP na porta 7301..."
PYTHONPATH=servidor-mcp python3 -m uvicorn app:app --port 7301 --app-dir servidor-mcp
