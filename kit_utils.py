import os

import requests


KIT_BASE_URL = "https://api.convertkit.com/v3"
KIT_TIMEOUT_SECONDS = 5


def primeiro_nome(valor) -> str:
    if not isinstance(valor, str):
        return ""
    try:
        nome_normalizado = " ".join(valor.strip().split())
        return nome_normalizado.split(" ", 1)[0] if nome_normalizado else ""
    except Exception:
        return ""


def metadados_resposta_subscribe(resposta) -> tuple[bool, bool, bool]:
    try:
        corpo = resposta.json()
        json_valid = True
    except Exception:
        return False, False, False

    subscriber = {}
    if isinstance(corpo, dict):
        subscription = corpo.get("subscription")
        if isinstance(subscription, dict):
            subscriber = subscription.get("subscriber") or {}
        if not isinstance(subscriber, dict) or not subscriber:
            subscriber = corpo.get("subscriber") or {}
    if not isinstance(subscriber, dict):
        subscriber = {}

    subscriber_id_present = subscriber.get("id") is not None
    first_name_present = "first_name" in subscriber
    return json_valid, subscriber_id_present, first_name_present


def _subscriber_id_valido(subscriber_id):
    if isinstance(subscriber_id, bool):
        return None
    if isinstance(subscriber_id, int):
        return subscriber_id if subscriber_id > 0 else None
    if isinstance(subscriber_id, str):
        subscriber_id = subscriber_id.strip()
        return subscriber_id if subscriber_id else None
    return None


def extrair_subscriber_id(resposta):
    try:
        corpo = resposta.json()
        subscriber_id = corpo["subscription"]["subscriber"]["id"]
    except Exception:
        return None
    return _subscriber_id_valido(subscriber_id)


def atualizar_first_name_kit(subscriber_id, first_name) -> bool:
    print("[PIX E2E] stage=first_name_helper_entered")
    subscriber_id = _subscriber_id_valido(subscriber_id)
    first_name = primeiro_nome(first_name)
    api_secret = os.getenv("CONVERTKIT_API_SECRET")
    entradas_validas = subscriber_id is not None and bool(first_name) and bool(api_secret)
    print(f"[PIX E2E] stage=first_name_inputs_valid value={entradas_validas}")
    if not entradas_validas:
        return False

    try:
        print("stage=first_name_put_attempted", flush=True)
        resposta = requests.put(
            f"{KIT_BASE_URL}/subscribers/{subscriber_id}",
            json={"api_secret": api_secret, "first_name": first_name},
            timeout=KIT_TIMEOUT_SECONDS,
        )
        sucesso = resposta.status_code in (200, 201, 204)
        print(f"stage=first_name_put_completed success={sucesso}", flush=True)
        print(f"[PIX E2E] stage=first_name_put_completed success={sucesso}")
        print(
            "[Kit Subscriber] operation=update_first_name "
            f"status_http={resposta.status_code} success={sucesso}"
        )
        return sucesso
    except Exception as exc:
        print("stage=first_name_put_completed success=False", flush=True)
        print("[PIX E2E] stage=first_name_put_failed")
        print(
            "[Kit Subscriber] operation=update_first_name "
            f"failed={type(exc).__name__}"
        )
        return False
