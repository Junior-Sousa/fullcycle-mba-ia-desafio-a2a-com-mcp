import os
import sys
import secrets
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

def get_dependencies_from_pyproject():
    pyproject_path = BASE_DIR / "pyproject.toml"
    if not pyproject_path.exists():
        return []
    try:
        import tomllib
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("dependencies", [])
    except ImportError:
        import re
        content = pyproject_path.read_text(encoding="utf-8")
        deps = []
        in_deps = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("dependencies = ["):
                in_deps = True
                continue
            if in_deps:
                if line.startswith("]"):
                    break
                m = re.search(r'["\']([^"\']+)["\']', line)
                if m:
                    deps.append(m.group(1))
        return deps

def install_dependencies():
    print("Instalando/verificando dependências travadas a partir do pyproject.toml...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "."]
        )
    except subprocess.CalledProcessError:
        deps = get_dependencies_from_pyproject()
        if deps:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-q", *deps]
            )
        else:
            raise

def main():
    install_dependencies()

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
