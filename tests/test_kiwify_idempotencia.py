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


def payload_cart(status, email="lead@example.com", manychat_id="777"):
    return {
        "cart": {
            "status": status,
            "email": email,
            "name": "Lead Teste",
            "phone": "+55 49 99999-0000",
            "product_name": "Protocolo Vigor 360",
            "custom_variables": {"manychat_id": manychat_id},
        }
    }


def payload_order(status="paid", email="lead@example.com", manychat_id="777"):
    return {
        "order": {
            "order_status": status,
            "Product": {"product_name": "Protocolo Vigor 360"},
            "Customer": {
                "full_name": "Lead Teste",
                "email": email,
                "mobile": "+55 49 99999-0000",
            },
            "custom_variables": {"manychat_id": manychat_id},
        }
    }


def instalar_supabase_em_memoria(monkeypatch):
    estado = {}
    chamadas_tag_manychat = []
    chamadas_convertkit = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        params = params or {}
        campos = [
            "manychat_id",
            "telefone",
            "telefone_whatsapp",
            "telefone_checkout_kiwify",
            "email",
        ]
        campo = next((c for c in campos if c in params), None)
        if not campo:
            return FakeResponse(200, [])

        valor = str(params[campo]).replace("eq.", "", 1)
        for mcid, registro in estado.items():
            candidato = mcid if campo == "manychat_id" else registro.get(campo)
            if candidato is not None and str(candidato) == valor:
                return FakeResponse(200, [{"id": 1, **registro, "manychat_id": mcid}])
        return FakeResponse(200, [])

    def fake_post(url, json=None, headers=None, timeout=None, **kwargs):
        if "leads_vigor" in url:
            mcid = str((json or {}).get("manychat_id", ""))
            registro = estado.setdefault(mcid, {})
            registro.update(json or {})
            return FakeResponse(200, [{"id": 1, **registro}])

        if "addTagByName" in url:
            chamadas_tag_manychat.append(json)
            return FakeResponse(200, {"status": "success"})

        return FakeResponse(200, {})

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.requests, "post", fake_post)
    monkeypatch.setattr(
        main,
        "gerenciar_tags_convertkit",
        lambda email, status: chamadas_convertkit.append((email, status)),
    )

    return estado, chamadas_tag_manychat, chamadas_convertkit


def test_abandono_duplicado_mantem_um_estado_final_coerente(monkeypatch):
    estado, _, chamadas_convertkit = instalar_supabase_em_memoria(monkeypatch)

    r1 = client.post("/kiwify", json=payload_cart("abandoned"))
    r2 = client.post("/kiwify", json=payload_cart("abandoned"))

    assert r1.json()["status"] == "processado"
    assert r2.json()["status"] == "processado"
    assert estado["777"]["status_pagamento"] == "abandoned"
    assert estado["777"]["email"] == "lead@example.com"
    assert chamadas_convertkit == [
        ("lead@example.com", "abandoned"),
        ("lead@example.com", "abandoned"),
    ]


def test_paid_duplicado_mantem_status_pago(monkeypatch):
    estado, chamadas_tag_manychat, chamadas_convertkit = instalar_supabase_em_memoria(monkeypatch)

    r1 = client.post("/kiwify", json=payload_order("paid"))
    r2 = client.post("/kiwify", json=payload_order("paid"))

    assert r1.json()["status"] == "sucesso_id_direto"
    assert r2.json()["status"] == "sucesso_id_direto"
    assert estado["777"]["status_pagamento"] == "paid"
    assert len(chamadas_tag_manychat) == 2
    assert chamadas_convertkit == [
        ("lead@example.com", "paid"),
        ("lead@example.com", "paid"),
    ]


def test_abandoned_depois_paid_nao_pode_rebaixar_comprador(monkeypatch):
    estado, _, _ = instalar_supabase_em_memoria(monkeypatch)

    pago = client.post("/kiwify", json=payload_order("paid"))
    atraso = client.post("/kiwify", json=payload_cart("abandoned"))

    assert pago.json()["status"] == "sucesso_id_direto"
    # O backend preserva o estado pago e pode reaplicar a protecao de comprador.
    assert atraso.json()["status"] in ["processado", "sucesso_id_direto"]

    # Regra critica: depois de pago, um webhook atrasado de abandono nao pode
    # transformar comprador em abandonado.
    assert estado["777"]["status_pagamento"] == "paid"


def test_abandoned_antes_paid_termina_como_pago(monkeypatch):
    estado, _, _ = instalar_supabase_em_memoria(monkeypatch)

    abandono = client.post("/kiwify", json=payload_cart("abandoned"))
    pago = client.post("/kiwify", json=payload_order("paid"))

    assert abandono.json()["status"] == "processado"
    assert pago.json()["status"] == "sucesso_id_direto"
    assert estado["777"]["status_pagamento"] == "paid"


def test_eventos_de_leads_diferentes_nao_se_misturam(monkeypatch):
    estado, _, _ = instalar_supabase_em_memoria(monkeypatch)

    client.post(
        "/kiwify",
        json=payload_cart("abandoned", email="a@example.com", manychat_id="111"),
    )
    client.post(
        "/kiwify",
        json=payload_order("paid", email="b@example.com", manychat_id="222"),
    )

    assert estado["111"]["email"] == "a@example.com"
    assert estado["111"]["status_pagamento"] == "abandoned"
    assert estado["222"]["email"] == "b@example.com"
    assert estado["222"]["status_pagamento"] == "paid"
