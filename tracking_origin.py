from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from urllib.parse import urlencode


TRACKING_TTL_MINUTES = 30
INFERENCE_WINDOW_SECONDS = 90


def gerar_token(tamanho_bytes: int = 9) -> str:
    """Gera token curto, URL-safe e imprevisivel."""
    return secrets.token_urlsafe(tamanho_bytes)


def hash_ip(ip: str | None, salt: str = "") -> str | None:
    if not ip:
        return None
    base = f"{salt}:{ip}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def extrair_token_mensagem(mensagem: str | None) -> str | None:
    """Extrai token de mensagens como 'VIGOR AbCd_123-xY'."""
    if not mensagem:
        return None
    match = re.search(r"\bVIGOR\s+([A-Za-z0-9_-]{10,64})\b", str(mensagem), flags=re.IGNORECASE)
    return match.group(1) if match else None


def montar_registro_click(
    *,
    origem: str,
    campanha: str | None = None,
    video: str | None = None,
    produto: str | None = None,
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    utm_content: str | None = None,
    utm_term: str | None = None,
    user_agent: str | None = None,
    ip_hash: str | None = None,
    agora: datetime | None = None,
    token: str | None = None,
):
    agora = agora or datetime.now(timezone.utc)
    token = token or gerar_token()

    return {
        "token": token,
        "origem": origem,
        "campanha": campanha,
        "video": video,
        "produto": produto,
        "utm_source": utm_source,
        "utm_medium": utm_medium,
        "utm_campaign": utm_campaign,
        "utm_content": utm_content,
        "utm_term": utm_term,
        "manychat_id": None,
        "lead_id": None,
        "claimed": False,
        "claim_method": None,
        "claim_confidence": None,
        "user_agent": user_agent,
        "ip_hash": ip_hash,
        "created_at": agora.isoformat(),
        "expires_at": (agora + timedelta(minutes=TRACKING_TTL_MINUTES)).isoformat(),
        "claimed_at": None,
    }


def montar_url_whatsapp(numero: str, token: str, mensagem_base: str = "VIGOR") -> str:
    """Monta wa.me mantendo token na mensagem pre-preenchida."""
    numero_limpo = "".join(ch for ch in str(numero) if ch.isdigit())
    texto = f"{mensagem_base} {token}".strip()
    return f"https://wa.me/{numero_limpo}?{urlencode({'text': texto})}"


def registro_expirado(registro: dict, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now(timezone.utc)
    expires_at = registro.get("expires_at")
    if not expires_at:
        return True
    exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return agora >= exp


def claim_exato(registro: dict, *, manychat_id: str, lead_id: str | None = None, agora: datetime | None = None) -> dict:
    agora = agora or datetime.now(timezone.utc)
    atualizado = dict(registro)
    atualizado.update({
        "manychat_id": str(manychat_id),
        "lead_id": lead_id,
        "claimed": True,
        "claim_method": "token",
        "claim_confidence": "exact",
        "claimed_at": agora.isoformat(),
    })
    return atualizado


def claim_inferido(registro: dict, *, manychat_id: str, agora: datetime | None = None) -> dict:
    """Marca atribuicao temporal conservadora quando existe um unico clique recente."""
    agora = agora or datetime.now(timezone.utc)
    atualizado = dict(registro)
    atualizado.update({
        "manychat_id": str(manychat_id),
        "claimed": True,
        "claim_method": "recent_unique_click",
        "claim_confidence": "medium",
        "claimed_at": agora.isoformat(),
    })
    return atualizado
