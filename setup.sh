#!/bin/bash
set -e

echo "Instalando dependências..."
pip install fastapi uvicorn httpx mcp pydantic

if [ ! -f ".env" ]; then
    echo "Gerando REQUEST_STATE_SECRET em .env..."
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "REQUEST_STATE_SECRET=$SECRET" > .env
    echo "Arquivo .env criado com sucesso."
else
    echo "Arquivo .env já existe."
fi

echo "Setup concluído!"
