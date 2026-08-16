from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

import journey_events


class FakeResponse:
    def __init__(self, status_code=201, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        return self._json_data or {}


app = FastAPI()
app.include_router(journey_events.router)
client = TestClient(app)


def test_post_journey_run_gera_uuid4_sem_acesso_externo(monkeypatch):
    def acesso_externo_inesperado(*args, **kwargs):
        raise AssertionError("/journey/run nao deve acessar servicos externos")

    monkeypatch.setattr(journey_events.requests, "get", acesso_externo_inesperado)
    monkeypatch.setattr(journey_events.requests, "post", acesso_externo_inesperado)

    resposta = client.post("/journey/run")

    assert resposta.status_code == 200
    journey_run_id = UUID(resposta.json()["journey_run_id"])
    assert journey_run_id.version == 4


def test_post_journey_run_gera_uuid_novo_a_cada_chamada():
    primeiro = client.post("/journey/run")
    segundo = client.post("/journey/run")

    assert primeiro.status_code == 200
    assert segundo.status_code == 200
    assert primeiro.json()["journey_run_id"] != segundo.json()["journey_run_id"]


def test_post_journey_event_grava_evento(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["json"] = json
        capturado["headers"] = headers
        return FakeResponse(201, json_data={"id": "evt-1"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "manychat_id": "mc_123",
            "event_name": "step_started",
            "event_stage": "lead_form",
            "event_value": "lead_form_opened",
            "source_system": "lucasbot",
            "dedupe_key": "evt-step-started-001",
            "metadata": {"step": "inicio"},
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "accepted"
    assert capturado["json"]["manychat_id"] == "mc_123"
    assert capturado["json"]["event_name"] == "step_started"
    assert capturado["json"]["dedupe_key"]
    assert capturado["json"]["journey_run_id"] is None
    assert resposta.json()["journey_run_id"] is None


def test_post_journey_event_preserva_journey_run_id(monkeypatch):
    capturado = {}
    journey_run_id = "2c240679-62aa-4bd8-a3bf-079938e84792"

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["json"] = json
        return FakeResponse(201, json_data={"id": "evt-run-1"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "journey_run_id": journey_run_id,
            "manychat_id": "mc_run",
            "event_name": "step_answered",
            "event_stage": "idade",
            "event_value": "45",
            "source_system": "manychat",
            "dedupe_key": "evt-step-answered-run-001",
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "accepted"
    assert resposta.json()["journey_run_id"] == journey_run_id
    assert capturado["json"]["journey_run_id"] == journey_run_id
    assert capturado["json"]["dedupe_key"] == "evt-step-answered-run-001"


def test_post_journey_event_rejeita_journey_run_id_invalido(monkeypatch):
    chamadas = []

    def fake_post(*args, **kwargs):
        chamadas.append((args, kwargs))
        return FakeResponse(201)

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "journey_run_id": "nao-e-uuid",
            "manychat_id": "mc_invalid_run",
            "event_name": "step_started",
            "source_system": "manychat",
            "dedupe_key": "evt-invalid-run-001",
        },
    )

    assert resposta.status_code == 422
    assert chamadas == []


def test_post_journey_event_409_23505_e_idempotente(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse(409, text='{"code":"23505"}', json_data={"code": "23505"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    payload = {
        "journey_run_id": "a93c03a7-91c2-4eea-8f53-dcc290f3dd8f",
        "manychat_id": "mc_456",
        "event_name": "email_captured",
        "event_stage": "capture",
        "event_value": "teste@example.com",
        "source_system": "lucasbot",
        "metadata": {"channel": "whatsapp"},
        "dedupe_key": "dup-key-01",
    }

    resposta = client.post("/journey/event", json=payload)

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "accepted"
    assert resposta.json()["idempotent"] is True
    assert resposta.json()["journey_run_id"] == payload["journey_run_id"]


def test_post_journey_event_409_sem_23505_e_falha_controlada(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse(409, text='{"code":"23503"}', json_data={"code": "23503"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "manychat_id": "mc_789",
            "event_name": "offer_clicked",
            "source_system": "lucasbot",
            "dedupe_key": "evt-offer-clicked-409",
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "journey_event_failed"


def test_post_journey_event_422_e_falha_controlada(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return FakeResponse(422, text="validation error")

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "manychat_id": "mc_422",
            "event_name": "checkout_started",
            "source_system": "lucasbot",
            "dedupe_key": "evt-checkout-started-422",
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "journey_event_failed"


def test_post_journey_event_erro_de_rede_retorna_200(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "journey_run_id": "cc886980-b908-40d4-9d13-9c44b437fd19",
            "manychat_id": "mc_999",
            "event_name": "purchase",
            "source_system": "lucasbot",
            "dedupe_key": "evt-purchase-network-failure",
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["status"] == "journey_event_failed"
    assert resposta.json()["journey_run_id"] == "cc886980-b908-40d4-9d13-9c44b437fd19"


def test_post_journey_event_payload_igual_com_dedupe_diferente_e_aceito(monkeypatch):
    chamadas = []

    def fake_post(url, json=None, headers=None, timeout=None):
        chamadas.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(201, json_data={"id": "evt-1"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    payload = {
        "manychat_id": "mc_same",
        "event_name": "step_started",
        "event_stage": "lead_form",
        "event_value": "same-value",
        "source_system": "lucasbot",
        "metadata": {"step": "inicio"},
    }

    primeiro = client.post("/journey/event", json={**payload, "dedupe_key": "evt-1"})
    segundo = client.post("/journey/event", json={**payload, "dedupe_key": "evt-2"})

    assert primeiro.status_code == 200
    assert segundo.status_code == 200
    assert len(chamadas) == 2
    assert chamadas[0]["json"]["dedupe_key"] == "evt-1"
    assert chamadas[1]["json"]["dedupe_key"] == "evt-2"


def test_post_journey_event_mock_confirma_timeout_3(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["timeout"] = timeout
        return FakeResponse(201, json_data={"id": "evt-timeout"})

    monkeypatch.setattr(journey_events.requests, "post", fake_post)

    resposta = client.post(
        "/journey/event",
        json={
            "manychat_id": "mc_timeout",
            "event_name": "fallback_triggered",
            "source_system": "lucasbot",
            "dedupe_key": "evt-timeout-03",
        },
    )

    assert resposta.status_code == 200
    assert capturado["timeout"] == 3


def test_post_journey_event_rejeita_payload_invalido():
    resposta = client.post(
        "/journey/event",
        json={
            "manychat_id": "",
            "event_name": "step_started",
            "source_system": "lucasbot",
            "dedupe_key": "",
        },
    )

    assert resposta.status_code == 422
