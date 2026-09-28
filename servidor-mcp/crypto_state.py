import os
import time
import json
import hmac
import hashlib
import base64
from typing import Any, Tuple

SECRET_ENV = "REQUEST_STATE_SECRET"

def _get_secret() -> bytes:
    secret = os.getenv(SECRET_ENV, "")
    if len(secret.encode("utf-8")) < 32:
        raise ValueError(f"Variavel {SECRET_ENV} deve ter no minimo 32 bytes de entropia.")
    return secret.encode("utf-8")

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

def _b64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))

def seal_state(payload: dict[str, Any], ttl_seconds: int = 900) -> str:
    """Empacota os dados com expiração (padrão 15 min) e assinatura HMAC-SHA256."""
    secret = _get_secret()
    data = dict(payload)
    data["_exp"] = int(time.time()) + ttl_seconds
    
    # Serialização canônica (sem espaços extras, chaves ordenadas)
    serialized = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(serialized)
    
    signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)
    
    return f"{payload_b64}.{sig_b64}"

def unseal_state(token: str) -> Tuple[bool, dict[str, Any] | str]:
    """
    Verifica integridade e expiração.
    Retorna (True, payload_dict) se válido, ou (False, mensagem_erro) se violado/expirado.
    """
    try:
        secret = _get_secret()
        parts = token.split(".")
        if len(parts) != 2:
            return False, "Formato do token invalido"
        
        payload_b64, sig_b64 = parts
        expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return False, "Assinatura invalida ou token adulterado"
        
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if time.time() > payload.get("_exp", 0):
            return False, "Token expirado"
            
        return True, payload
    except Exception as e:
        return False, f"Falha na verificacao de integridade: {str(e)}"
