from urllib.parse import parse_qs, urlsplit

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

import tracking_routes as tracking


class FakeResponse:
    status_code = 201
    text = "[]"


def make_client():
    app = FastAPI()
    app.include_router(tracking.router)
    return TestClient(app)


def test_montar_url_vsl_separa_campanha_de_token_unico():
    meta = tracking.interpretar_codigo("yt101")
    meta["utm_medium"] = "qrcode"

    url = tracking.montar_url_vsl(
        meta,
        "TOKEN_UNICO_123",
        base_url="https://drlucasgomes.com.br/protocolo-vigor-360/?foo=bar",
    )
    query = parse_qs(urlsplit(url).query)

    assert query["foo"] == ["bar"]
    assert query["src"] == ["qr_yt101"]
    assert query["utm_source"] == ["youtube"]
    assert query["utm_medium"] == ["qrcode"]
    assert query["utm_campaign"] == ["vigor_yt_101"]
    assert query["utm_content"] == ["yt101"]
    assert query["utm_term"] == ["TOKEN_UNICO_123"]


def test_vsl_tracking_registra_scan_e_redireciona(monkeypatch):
    salvo = {}

    def fake_montar_registro_click(**kwargs):
        salvo["kwargs"] = kwargs
        return {
            **kwargs,
            "token": "SCAN_TOKEN_123",
            "manychat_id": None,
            "lead_id": None,
            "claimed": False,
            "claim_method": None,
            "claim_confidence": None,
            "created_at": "2026-08-28T12:00:00+00:00",
            "expires_at": "2026-08-28T12:30:00+00:00",
            "claimed_at": None,
        }

    def fake_salvar_click(registro):
        salvo["registro"] = registro
        return FakeResponse()

    monkeypatch.setattr(tracking, "montar_registro_click", fake_montar_registro_click)
    monkeypatch.setattr(tracking, "salvar_click", fake_salvar_click)
    monkeypatch.setattr(tracking, "hash_ip", lambda ip, salt: "hash")
    monkeypatch.delenv("VSL_URL", raising=False)

    response = make_client().get("/v/yt101", follow_redirects=False)

    assert response.status_code == 302
    assert salvo["kwargs"]["utm_medium"] == "qrcode"
    assert salvo["registro"]["token"] == "SCAN_TOKEN_123"

    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["src"] == ["qr_yt101"]
    assert query["utm_term"] == ["SCAN_TOKEN_123"]


def test_falha_de_supabase_nao_bloqueia_vsl(monkeypatch):
    def fake_montar_registro_click(**kwargs):
        return {
            **kwargs,
            "token": "SCAN_TOKEN_456",
            "manychat_id": None,
            "lead_id": None,
            "claimed": False,
            "claim_method": None,
            "claim_confidence": None,
            "created_at": "2026-08-28T12:00:00+00:00",
            "expires_at": "2026-08-28T12:30:00+00:00",
            "claimed_at": None,
        }

    monkeypatch.setattr(tracking, "montar_registro_click", fake_montar_registro_click)
    monkeypatch.setattr(
        tracking,
        "salvar_click",
        lambda registro: (_ for _ in ()).throw(requests.RequestException("offline")),
    )
    monkeypatch.setattr(tracking, "hash_ip", lambda ip, salt: "hash")
    monkeypatch.delenv("VSL_URL", raising=False)

    response = make_client().get("/v/ig22", follow_redirects=False)

    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["src"] == ["qr_ig22"]
    assert query["utm_source"] == ["instagram"]
    assert query["utm_medium"] == ["qrcode"]
    assert query["utm_term"] == ["SCAN_TOKEN_456"]


def test_codigo_invalido_retorna_404():
    response = make_client().get("/v/tiktok1", follow_redirects=False)
    assert response.status_code == 404
