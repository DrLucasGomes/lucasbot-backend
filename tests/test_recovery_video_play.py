from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import recovery_routes


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


app = FastAPI()
app.include_router(recovery_routes.router)
client = TestClient(app)


def instalar_servicos(
    monkeypatch,
    lead=None,
    kit_status=200,
    kit_exception=None,
    falhar_completed=False,
):
    estado = {}
    chamadas_kit = []

    def fake_get(url, params=None, **kwargs):
        assert "leads_vigor" in url
        manychat_id = str((params or {}).get("manychat_id", "")).replace("eq.", "", 1)
        if lead and str(lead.get("manychat_id")) == manychat_id:
            return FakeResponse(200, [lead])
        return FakeResponse(200, [])

    def fake_post(url, json=None, **kwargs):
        if recovery_routes.RECOVERY_TABLE in url:
            manychat_id = json["manychat_id"]
            if manychat_id in estado:
                return FakeResponse(409, {"code": "23505"}, "duplicate")
            estado[manychat_id] = {
                "status": "processing",
                "updated_at": datetime.now(timezone.utc),
            }
            return FakeResponse(201, [{"manychat_id": manychat_id, "status": "processing"}])

        if "api.convertkit.com" in url:
            chamadas_kit.append((url, json))
            if kit_exception:
                raise kit_exception
            return FakeResponse(kit_status, {"ok": kit_status < 300})

        raise AssertionError(f"POST inesperado: {url}")

    def fake_patch(url, params=None, json=None, **kwargs):
        assert recovery_routes.RECOVERY_TABLE in url
        manychat_id = params["manychat_id"].replace("eq.", "", 1)
        status_esperado = params["status"].replace("eq.", "", 1)
        registro = estado.get(manychat_id)
        if not registro or registro["status"] != status_esperado:
            return FakeResponse(200, [])

        limite = (params or {}).get("updated_at")
        if limite:
            cutoff = datetime.fromisoformat(limite.replace("lt.", "", 1))
            if registro["updated_at"] >= cutoff:
                return FakeResponse(200, [])

        if falhar_completed and json["status"] == "completed":
            return FakeResponse(503, {"error": "supabase offline"})

        registro["status"] = json["status"]
        registro["updated_at"] = datetime.now(timezone.utc)
        return FakeResponse(200, [{"manychat_id": manychat_id, "status": json["status"]}])

    monkeypatch.setattr(recovery_routes.requests, "get", fake_get)
    monkeypatch.setattr(recovery_routes.requests, "post", fake_post)
    monkeypatch.setattr(recovery_routes.requests, "patch", fake_patch)
    monkeypatch.setenv("CONVERTKIT_API_KEY", "kit-key")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "987")
    return estado, chamadas_kit


def lead(status=None, email="lead@example.com", manychat_id="123"):
    return {
        "id": "lead-id",
        "manychat_id": manychat_id,
        "email": email,
        "status_pagamento": status,
    }


def test_lead_elegivel_recebe_tag_e_fica_completed(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())

    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert chamadas == [
        (
            "https://api.convertkit.com/v3/tags/987/subscribe",
            {"api_key": "kit-key", "email": "lead@example.com"},
        )
    ]


@pytest.mark.parametrize("status", sorted(recovery_routes.STATUS_PAGOS))
def test_lead_pago_e_ignorado(monkeypatch, status):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead(status=status))
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado == {}
    assert chamadas == []


@pytest.mark.parametrize("email", [None, "", "sem-arroba", "a@b", "a @b.com"])
def test_lead_sem_email_valido_e_ignorado(monkeypatch, email):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead(email=email))
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado == {}
    assert chamadas == []


def test_lead_inexistente_e_ignorado(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch)
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado == {}
    assert chamadas == []


@pytest.mark.parametrize("src", ["123", "mc_", "mc_abc", "MC_123", "mc_12 3", ""])
def test_src_invalido_e_rejeitado_com_seguranca(src):
    resposta = client.post("/recovery/video-play", json={"src": src})
    assert resposta.status_code == 422
    assert "lead@example.com" not in resposta.text


def test_email_arbitrario_no_payload_e_rejeitado():
    resposta = client.post(
        "/recovery/video-play",
        json={"src": "mc_123", "email": "atacante@example.com"},
    )
    assert resposta.status_code == 422


def test_chamada_duplicada_nao_reaplica_tag(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    primeira = client.post("/recovery/video-play", json={"src": "mc_123"})
    segunda = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert primeira.json() == segunda.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert len(chamadas) == 1


def test_processing_recente_nao_e_readquirido(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    estado["123"] = {
        "status": "processing",
        "updated_at": datetime.now(timezone.utc),
    }
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "processing"
    assert chamadas == []


def test_processing_stale_pode_ser_readquirido(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    estado["123"] = {
        "status": "processing",
        "updated_at": datetime.now(timezone.utc)
        - timedelta(minutes=recovery_routes.PROCESSING_STALE_MINUTES + 1),
    }
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert len(chamadas) == 1


def test_completed_nunca_e_readquirido(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    estado["123"] = {
        "status": "completed",
        "updated_at": datetime.now(timezone.utc) - timedelta(days=1),
    }
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert chamadas == []


def test_readquisicao_stale_continua_protegida_contra_concorrencia(monkeypatch):
    estado, _ = instalar_servicos(monkeypatch, lead=lead())
    estado["123"] = {
        "status": "processing",
        "updated_at": datetime.now(timezone.utc)
        - timedelta(minutes=recovery_routes.PROCESSING_STALE_MINUTES + 1),
    }
    assert recovery_routes.adquirir_processamento("123") is True
    assert recovery_routes.adquirir_processamento("123") is False


def test_failed_permite_retry_controlado(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    estado["123"] = {
        "status": "failed",
        "updated_at": datetime.now(timezone.utc),
    }
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert len(chamadas) == 1


def test_falha_http_do_kit_nao_quebra_endpoint(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead(), kit_status=503)
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.status_code == 200
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "failed"
    assert len(chamadas) == 1


def test_resposta_perdida_do_kit_fica_failed_e_pode_reaplicar(monkeypatch):
    estado, chamadas = instalar_servicos(
        monkeypatch,
        lead=lead(),
        kit_exception=TimeoutError("resposta perdida"),
    )
    primeira = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert primeira.json() == {"status": "processado"}
    assert estado["123"]["status"] == "failed"
    assert len(chamadas) == 1

    monkeypatch.setattr(
        recovery_routes,
        "aplicar_tag_recuperacao",
        lambda email: chamadas.append(("retry", email)) or True,
    )
    segunda = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert segunda.json() == {"status": "processado"}
    assert estado["123"]["status"] == "completed"
    assert chamadas[-1] == ("retry", "lead@example.com")


def test_configuracao_ausente_do_kit_marca_failed_sem_chamada(monkeypatch):
    estado, chamadas = instalar_servicos(monkeypatch, lead=lead())
    monkeypatch.delenv("TAG_RECUPERACAO_VIDEO_ID")
    resposta = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert resposta.json() == {"status": "processado"}
    assert estado["123"]["status"] == "failed"
    assert chamadas == []


def test_falha_ao_marcar_completed_nao_bloqueia_apos_janela_stale(monkeypatch):
    estado, chamadas = instalar_servicos(
        monkeypatch,
        lead=lead(),
        falhar_completed=True,
    )
    primeira = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert primeira.json() == {"status": "processado"}
    assert estado["123"]["status"] == "processing"
    assert len(chamadas) == 1

    estado["123"]["updated_at"] = datetime.now(timezone.utc) - timedelta(
        minutes=recovery_routes.PROCESSING_STALE_MINUTES + 1
    )
    segunda = client.post("/recovery/video-play", json={"src": "mc_123"})
    assert segunda.json() == {"status": "processado"}
    assert len(chamadas) == 2


def test_migration_define_estados_e_unicidade():
    migration = (Path(__file__).parents[1] / "sql" / "004_create_recovery_video_plays.sql").read_text(
        encoding="utf-8"
    ).lower()
    assert "manychat_id text not null unique" in migration
    assert "'processing', 'completed', 'failed'" in migration
    assert "updated_at" in migration
