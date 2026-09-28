#!/bin/bash
set -e

# Aguarda o start_mcp.sh gerar o .env, se rodarem juntos
if [ ! -f ".env" ]; then
    echo "Erro: Arquivo .env não encontrado. Rode o start_mcp.sh primeiro."
    exit 1
fi

# Carrega as variáveis de ambiente
set -a
source .env
set +a

echo "Iniciando Agente A2A na porta 7300..."
PYTHONPATH=. python3 -m uvicorn agente.app:app --port 7300
