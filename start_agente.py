import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

def main():
    if not ENV_FILE.exists():
        print("Erro: Arquivo .env não encontrado. Rode o start_mcp.py primeiro.")
        sys.exit(1)

    env = os.environ.copy()
    for line in ENV_FILE.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, val = line.strip().split("=", 1)
            env[key] = val

    env["PYTHONPATH"] = str(BASE_DIR)
    print("Iniciando Agente A2A na porta 7300...")
    
    # Substitui o processo atual pelo Uvicorn (preserva TTY e sinais do terminal)
    os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "agente.app:app", "--port", "7300"], env)

if __name__ == "__main__":
    main()
