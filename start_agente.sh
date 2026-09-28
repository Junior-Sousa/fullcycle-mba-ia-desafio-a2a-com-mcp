#!/bin/bash
set -e

if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

echo "Iniciando Agente A2A na porta 7300..."
PYTHONPATH=. python3 -m uvicorn agente.app:app --port 7300
