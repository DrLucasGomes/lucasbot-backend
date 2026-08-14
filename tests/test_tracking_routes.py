import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tracking_routes


class FakeResponse:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


app = FastAPI()
app.include_router(tracking_routes.router)
client = TestClient(app)


def test_interpretar_codigo_youtube():
    meta = tracking_routes.interpretar_codigo("yt101")
    assert meta["origem"] == "YouTube"
    assert meta["campanha"] == "Vigor_YT_101"
    assert meta["video"] == "101"
    assert meta["produto"] == "Protocolo Vigor 360"


def test_interpretar_codigo_facebook():
    meta = tracking_routes.interpretar_codigo("FB108")
    assert meta["origem"] == "Facebook"
    assert meta["campanha"] == "Vigor_FB_108"


def test_codigo_invalido_retorna_404(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NUMBER", "5549999999999")
    resposta = client.get("/r/xyz", follow_redirects=False)
    assert resposta.status_code == 404


def test_sem_whatsapp_configurado_retorna_503(monkeypatch):
    monkeypatch.delenv("WHATSAPP_NUMBER", raising=False)
    resposta = client.get("/r/yt101", follow_redirects=False)
    assert resposta.status_code == 503


def test_redirect_grava_click_antes_de_abrir_whatsapp(monkeypatch):
    capturado = {}

    monkeypatch.setenv("WHATSAPP_NUMBER", "55 (49) 99999-9999")
    monkeypatch.setenv("TRACKING_IP_SALT", "segredo-teste")

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["json"] = json
        capturado["headers"] = headers
        return FakeResponse(201)

    monkeypatch.setattr(tracking_routes.requests, "post", fake_post)

    resposta = client.get(
        "/r/yt101",
        headers={"user-agent": "LucasBot-Test", "x-forwarded-for": "203.0.113.10"},
        follow_redirects=False,
    )

    assert resposta.status_code == 302
    assert capturado["url"].endswith("/rest/v1/click_sessions")
    assert capturado["json"]["origem"] == "YouTube"
    assert capturado["json"]["campanha"] == "Vigor_YT_101"
    assert capturado["json"]["claimed"] is False
    assert capturado["json"]["ip_hash"] is not None
    assert capturado["json"]["user_agent"] == "LucasBot-Test"

    location = resposta.headers["location"]
    assert location.startswith("https://wa.me/5549999999999?")
    assert "VIGOR" in location


def test_falha_supabase_nao_redireciona(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NUMBER", "5549999999999")
    monkeypatch.setattr(
        tracking_routes.requests,
        "post",
        lambda *a, **k: FakeResponse(500, "erro simulado"),
    )
    resposta = client.get("/r/yt101", follow_redirects=False)
    assert resposta.status_code == 502
    assert "Supabase 500" in resposta.json()["detail"]
