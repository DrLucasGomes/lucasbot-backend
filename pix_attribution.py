"""Eventos analíticos fail-open da recuperação PIX, sem PII."""

import os

import requests


SUPABASE_URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
ATTRIBUTION_TIMEOUT_SECONDS = 3
ALLOWED_EVENTS = frozenset({"recovery_entered", "purchase_completed"})
_ATTRIBUTION_SESSION = requests.Session()


def registrar_evento_atribuicao_pix(order_id: str, event_name: str) -> bool:
    order_id = str(order_id).strip() if order_id is not None else ""
    if not order_id or event_name not in ALLOWED_EVENTS:
        return False

    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_key:
        return False

    try:
        resposta = _ATTRIBUTION_SESSION.post(
            f"{SUPABASE_URL}/rest/v1/recovery_pix_attribution_events",
            params={"on_conflict": "dedupe_key"},
            json={
                "order_id": order_id,
                "event_name": event_name,
                "dedupe_key": f"{event_name}:{order_id}",
            },
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=ignore-duplicates,return=minimal",
            },
            timeout=ATTRIBUTION_TIMEOUT_SECONDS,
        )
        if resposta.status_code in (200, 201, 204):
            return True
        print(
            "[PIX Attribution] "
            f"event={event_name} persistence_failed status_http={resposta.status_code}"
        )
    except Exception as exc:
        print(
            "[PIX Attribution] "
            f"event={event_name} persistence_failed error={type(exc).__name__}"
        )
    return False
