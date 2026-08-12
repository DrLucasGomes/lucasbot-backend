import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


client = TestClient(main.app)


def test_webhook_rejeita_sem_manychat_id(monkeypatch):
    chamadas = []

    def fake_post(*args, **kwargs):
        chamadas.append((args, kwargs))
        return FakeResponse(201, [])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post("/webhook", json={"email": "teste@example.com"})
    dados = resposta.json()

    assert dados["status"] == "erro"
    assert dados["detalhe"] == "manychat_id nao encontrado"
    assert chamadas == []


def test_webhook_upsert_limpa_payload_e_normaliza(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        capturado["url"] = url
        capturado["json"] = json
        capturado["headers"] = headers
        capturado["timeout"] = timeout
        return FakeResponse(201, [{"id": 123, **json}])

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "adicionar_lead_convertkit", lambda email: None)

    resposta = client.post(
        "/webhook",
        json={
            "manychat_id": " 123456 ",
            "email": " teste@example.com ",
            "idade": "45",
            "score": "7",
            "telefone_whatsapp": "+55 (49) 99974-4429",
            "campanha": "{{cuf_999}}",
            "campo_invasor": "nao",
        },
    )

    dados = resposta.json()

    assert dados["status"] == "sucesso"
    assert dados["code"] == 201
    assert capturado["url"].endswith("/rest/v1/leads_vigor?on_conflict=manychat_id")
    assert capturado["json"] == {
        "manychat_id": "123456",
        "email": "teste@example.com",
        "idade": 45,
        "score": 7,
        "telefone_whatsapp": "5549999744429",
    }
    assert "resolution=merge-duplicates" in capturado["headers"]["Prefer"]


def test_webhook_com_email_agenda_convertkit(monkeypatch):
    emails = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(201, [{"id": 1}])

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "adicionar_lead_convertkit", lambda email: emails.append(email))

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "abc123", "email": "lead@example.com"},
    )

    dados = resposta.json()
    assert dados["status"] == "sucesso"
    assert dados["convertkit_lead_agendado"] is True
    assert emails == ["lead@example.com"]


def test_webhook_sem_email_nao_agenda_convertkit(monkeypatch):
    emails = []

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(201, [{"id": 1}])

    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(main, "adicionar_lead_convertkit", lambda email: emails.append(email))

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "abc123", "score": 5},
    )

    dados = resposta.json()
    assert dados["status"] == "sucesso"
    assert dados["convertkit_lead_agendado"] is False
    assert emails == []


def test_webhook_supabase_401_retorna_erro_supabase(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(
            401,
            {"message": "Unregistered API key", "hint": "Double check the provided API key"},
        )

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "abc123", "email": "lead@example.com"},
    )

    dados = resposta.json()
    assert dados["status"] == "erro_supabase"
    assert dados["code"] == 401
    assert dados["convertkit_lead_agendado"] is False
    assert dados["resposta_supabase"]["message"] == "Unregistered API key"


def test_webhook_descarta_score_idade_invalidos_e_placeholders(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        capturado["json"] = json
        return FakeResponse(201, [json])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={
            "manychat_id": "999",
            "score": "cinco",
            "idade": "{{idade}}",
            "origem": "YouTube",
            "campanha": "undefined",
            "risco": "Nao",
        },
    )

    assert resposta.json()["status"] == "sucesso"
    assert capturado["json"] == {
        "manychat_id": "999",
        "origem": "YouTube",
        "risco": "Nao",
    }


def test_webhook_preserva_zero_em_score_e_idade(monkeypatch):
    capturado = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        capturado["json"] = json
        return FakeResponse(201, [json])

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "zero-test", "score": 0, "idade": 0},
    )

    assert resposta.json()["status"] == "sucesso"
    assert capturado["json"]["score"] == 0
    assert capturado["json"]["idade"] == 0


def test_webhook_excecao_de_rede_retorna_erro_critico(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("supabase indisponivel")

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "abc123", "email": "lead@example.com"},
    )

    dados = resposta.json()
    assert dados["status"] == "erro_critico"
    assert "supabase indisponivel" in dados["detalhe"]


def test_webhook_resposta_supabase_nao_json_eh_segura(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        return FakeResponse(500, ValueError("nao json"), "erro interno")

    monkeypatch.setattr(main.requests, "post", fake_post)

    resposta = client.post(
        "/webhook",
        json={"manychat_id": "abc123"},
    )

    dados = resposta.json()
    assert dados["status"] == "erro_supabase"
    assert dados["code"] == 500
    assert dados["resposta_supabase"] == "erro interno"
