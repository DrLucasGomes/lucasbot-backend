import main


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


def test_buscar_lead_existente_prioriza_email_sobre_telefone(monkeypatch):
    consultas = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        consultas.append(dict(params or {}))

        if "email" in (params or {}):
            return FakeResponse(200, [{
                "id": 2001,
                "email": "novo@example.com",
                "telefone": None,
                "telefone_whatsapp": None,
                "telefone_checkout_kiwify": None,
                "manychat_id": None,
                "status_pagamento": None,
            }])

        if "telefone" in (params or {}):
            return FakeResponse(200, [{
                "id": 1411,
                "email": "comprador-antigo@example.com",
                "telefone": "5549988217155",
                "telefone_whatsapp": None,
                "telefone_checkout_kiwify": "5549988217155",
                "manychat_id": None,
                "status_pagamento": "paid",
            }])

        return FakeResponse(200, [])

    monkeypatch.setattr(main.requests, "get", fake_get)

    lead = main.buscar_lead_existente(
        manychat_id=None,
        telefone="5549988217155",
        email="novo@example.com",
    )

    assert lead["id"] == 2001
    assert lead["email"] == "novo@example.com"
    assert consultas == [{
        "email": "eq.novo@example.com",
        "select": "id,email,telefone,telefone_whatsapp,telefone_checkout_kiwify,manychat_id,status_pagamento",
    }]


def test_sem_email_continua_usando_manychat_e_telefone_como_fallback(monkeypatch):
    consultas = []

    def fake_get(url, params=None, headers=None, timeout=None, **kwargs):
        consultas.append(dict(params or {}))
        if "manychat_id" in (params or {}):
            return FakeResponse(200, [])
        if "telefone" in (params or {}):
            return FakeResponse(200, [{
                "id": 3001,
                "email": None,
                "telefone": "5549999999999",
                "telefone_whatsapp": None,
                "telefone_checkout_kiwify": None,
                "manychat_id": None,
                "status_pagamento": None,
            }])
        return FakeResponse(200, [])

    monkeypatch.setattr(main.requests, "get", fake_get)

    lead = main.buscar_lead_existente(
        manychat_id="123456",
        telefone="5549999999999",
        email=None,
    )

    assert lead["id"] == 3001
    assert "manychat_id" in consultas[0]
    assert "telefone" in consultas[1]
