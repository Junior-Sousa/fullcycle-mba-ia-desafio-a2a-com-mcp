import os
import sys
import time
import secrets
import subprocess
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

def stream_logs(pipe, prefix):
    """Lê linhas do pipe e imprime com o prefixo indicado"""
    for line in iter(pipe.readline, b''):
        # decodifica e imprime com prefixo sem pular duas linhas
        sys.stdout.write(f"{prefix} {line.decode('utf-8', errors='replace')}")
        sys.stdout.flush()

def setup():
    print("======================================================")
    print("1. Verificando dependências...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "fastapi", "uvicorn", "httpx", "mcp", "pydantic"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    print("2. Verificando ambiente (.env)...")
    if not ENV_FILE.exists():
        secret = secrets.token_hex(32)
        ENV_FILE.write_text(f"REQUEST_STATE_SECRET={secret}\n")
        print("   -> Arquivo .env gerado com REQUEST_STATE_SECRET.")
    else:
        print("   -> Arquivo .env já existe.")

def run_servers():
    print("======================================================")
    print("Iniciando Servidor MCP (porta 7301)...")
    
    env = os.environ.copy()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                key, val = line.strip().split("=", 1)
                env[key] = val

    env["PYTHONPATH"] = str(BASE_DIR / "servidor-mcp")
    mcp_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app:app", "--port", "7301", "--app-dir", "servidor-mcp"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    # Lança a thread para ler os logs do MCP
    threading.Thread(target=stream_logs, args=(mcp_proc.stdout, "[MCP]   "), daemon=True).start()

    print("Iniciando Agente A2A (porta 7300)...")
    env_agente = env.copy()
    env_agente["PYTHONPATH"] = str(BASE_DIR)
    agente_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "agente.app:app", "--port", "7300"],
        env=env_agente,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    # Lança a thread para ler os logs do Agente
    threading.Thread(target=stream_logs, args=(agente_proc.stdout, "[AGENTE]"), daemon=True).start()
    
    print("======================================================")
    print("Ambos os processos estão rodando!")
    print("Pressione CTRL+C para encerrar ambos simultaneamente.")
    print("")
    print("Agora abra outro terminal e execute o validador:")
    print("python3 validador/validar.py --agente http://localhost:7300 --mcp http://localhost:7301")
    print("======================================================")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nEncerrando servidores (MCP e Agente)...")
        mcp_proc.terminate()
        agente_proc.terminate()
        mcp_proc.wait()
        agente_proc.wait()
        print("Servidores encerrados com sucesso.")

if __name__ == "__main__":
    setup()
    run_servers()
