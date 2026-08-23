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
