#!/bin/bash
set -e

# 1. Garante o setup inicial
./setup.sh

# 2. Carrega as variáveis de ambiente
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

echo "======================================================"
echo "Iniciando Servidor MCP na porta 7301..."
PYTHONPATH=servidor-mcp python3 -m uvicorn app:app --port 7301 --app-dir servidor-mcp &
MCP_PID=$!

echo "Iniciando Agente A2A na porta 7300..."
PYTHONPATH=. python3 -m uvicorn agente.app:app --port 7300 &
AGENTE_PID=$!
echo "======================================================"

function cleanup() {
    echo ""
    echo "Encerrando servidores (MCP e Agente)..."
    kill $MCP_PID 2>/dev/null || true
    kill $AGENTE_PID 2>/dev/null || true
    wait $MCP_PID 2>/dev/null || true
    wait $AGENTE_PID 2>/dev/null || true
    echo "Servidores encerrados com sucesso."
}

# Captura o encerramento do script e limpa os background jobs
trap cleanup EXIT INT TERM

echo "Ambos os processos estão rodando!"
echo "Pressione CTRL+C para encerrar ambos simultaneamente."
echo ""
echo "Agora abra outro terminal e execute o validador:"
echo "python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301"

# Mantém o script rodando e segurando os processos
wait
