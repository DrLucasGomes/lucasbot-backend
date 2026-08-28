import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
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


def test_montar_url_vsl_preserva_query_e_adiciona_tracking():
    meta = tracking_routes.interpretar_codigo("yt101")
    meta["utm_medium"] = "qrcode"

    destino = tracking_routes.montar_url_vsl(
        meta,
        "TOKEN_123456",
        "https://drlucasgomes.com.br/protocolo-vigor-360/?foo=bar",
    )

    parsed = urlparse(destino)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "drlucasgomes.com.br"
    assert parsed.path == "/protocolo-vigor-360/"
    assert query["foo"] == ["bar"]
    assert query["src"] == ["qr_yt101"]
    assert query["utm_source"] == ["youtube"]
    assert query["utm_medium"] == ["qrcode"]
    assert query["utm_campaign"] == ["vigor_yt_101"]
    assert query["utm_content"] == ["yt101"]
    assert query["utm_term"] == ["TOKEN_123456"]


def test_qr_vsl_grava_click_e_redireciona_com_token_unico(monkeypatch):
    capturado = {}
    monkeypatch.setenv("TRACKING_IP_SALT", "segredo-teste")
    monkeypatch.setenv("VSL_URL", "https://drlucasgomes.com.br/protocolo-vigor-360/")

    def fake_post(url, json=None, headers=None, timeout=None):
        capturado["url"] = url
        capturado["json"] = json
        return FakeResponse(201)

    monkeypatch.setattr(tracking_routes.requests, "post", fake_post)

    resposta = client.get(
        "/v/yt101",
        headers={"user-agent": "QR-Test", "x-forwarded-for": "203.0.113.20"},
        follow_redirects=False,
    )

    assert resposta.status_code == 302
    assert capturado["url"].endswith("/rest/v1/click_sessions")
    assert capturado["json"]["origem"] == "YouTube"
    assert capturado["json"]["campanha"] == "Vigor_YT_101"
    assert capturado["json"]["utm_medium"] == "qrcode"
    assert capturado["json"]["utm_content"] == "yt101"
    assert capturado["json"]["user_agent"] == "QR-Test"
    assert capturado["json"]["ip_hash"] is not None

    parsed = urlparse(resposta.headers["location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "drlucasgomes.com.br"
    assert query["utm_source"] == ["youtube"]
    assert query["utm_medium"] == ["qrcode"]
    assert query["utm_campaign"] == ["vigor_yt_101"]
    assert query["utm_content"] == ["yt101"]
    assert query["src"] == ["qr_yt101"]
    assert query["utm_term"] == [capturado["json"]["token"]]


def test_qr_vsl_codigo_invalido_retorna_404():
    resposta = client.get("/v/xyz", follow_redirects=False)
    assert resposta.status_code == 404


def test_qr_vsl_falha_supabase_nao_bloqueia_venda(monkeypatch):
    monkeypatch.setattr(
        tracking_routes.requests,
        "post",
        lambda *a, **k: FakeResponse(500, "erro simulado"),
    )

    resposta = client.get("/v/ig22", follow_redirects=False)
    assert resposta.status_code == 302
    query = parse_qs(urlparse(resposta.headers["location"]).query)
    assert query["utm_source"] == ["instagram"]
    assert query["utm_medium"] == ["qrcode"]
    assert query["utm_content"] == ["ig22"]


def test_qr_vsl_timeout_supabase_nao_bloqueia_venda(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("timeout simulado")

    monkeypatch.setattr(tracking_routes.requests, "post", timeout)

    resposta = client.get("/v/fb108", follow_redirects=False)
    assert resposta.status_code == 302
    query = parse_qs(urlparse(resposta.headers["location"]).query)
    assert query["utm_source"] == ["facebook"]
    assert query["utm_medium"] == ["qrcode"]


def test_qr_vsl_url_invalida_retorna_503(monkeypatch):
    monkeypatch.setenv("VSL_URL", "javascript:alert(1)")
    resposta = client.get("/v/yt101", follow_redirects=False)
    assert resposta.status_code == 503
