import os
import sys
import secrets
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

def main():
    print("Instalando/verificando dependências...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "httpx", "mcp", "pydantic"]
    )

    if not ENV_FILE.exists():
        secret = secrets.token_hex(32)
        ENV_FILE.write_text(f"REQUEST_STATE_SECRET={secret}\n")
        print("Arquivo .env gerado com REQUEST_STATE_SECRET.")

    env = os.environ.copy()
    for line in ENV_FILE.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, val = line.strip().split("=", 1)
            env[key] = val

    env["PYTHONPATH"] = str(BASE_DIR / "servidor-mcp")
    print("Iniciando Servidor MCP na porta 7301...")
    
    # Substitui o processo atual pelo Uvicorn (preserva TTY e sinais do terminal)
    os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "app:app", "--port", "7301", "--app-dir", "servidor-mcp"], env)

if __name__ == "__main__":
    main()
