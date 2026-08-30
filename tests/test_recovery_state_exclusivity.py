import asyncio

import pytest
from fastapi import BackgroundTasks, HTTPException

import recovery_state_exclusivity as state


class FakeResponse:
    def __init__(self, status_code=204):
        self.status_code = status_code


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def payload_order(event_type, status, payment_method, email="lead@example.com"):
    return {
        "order": {
            "webhook_event_type": event_type,
            "order_status": status,
            "payment_method": payment_method,
            "Customer": {"email": email},
        }
    }


def test_classifica_estados_relevantes():
    assert state.classificar_estado_recuperacao(
        payload_order("pix_created", "waiting_payment", "pix")
    ) == "pix_pending"
    assert state.classificar_estado_recuperacao(
        payload_order("billet_created", "waiting_payment", "boleto")
    ) == "boleto_pending"
    assert state.classificar_estado_recuperacao(
        payload_order("order_approved", "paid", "boleto")
    ) == "paid"
    assert state.classificar_estado_recuperacao(
        {"cart": {"status": "abandoned", "email": "lead@example.com"}}
    ) == "abandoned"


def test_pix_remove_pos_clique_abandono_e_boleto(monkeypatch):
    posts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "video")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.setenv("TAG_PIX_ID", "pix")
    monkeypatch.setenv("TAG_BOLETO_ID", "boleto")
    monkeypatch.setattr(
        state.requests,
        "post",
        lambda url, **kwargs: posts.append((url, kwargs)) or FakeResponse(204),
    )

    assert state.convergir_tags_kit("lead@example.com", "pix_pending") is True
    assert [url.rsplit("/", 2)[-2] for url, _ in posts] == [
        "video", "abandon", "boleto"
    ]
    assert all("/pix/" not in url for url, _ in posts)


def test_boleto_remove_pos_clique_abandono_e_pix(monkeypatch):
    posts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "video")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.setenv("TAG_PIX_ID", "pix")
    monkeypatch.setenv("TAG_BOLETO_ID", "boleto")
    monkeypatch.setattr(
        state.requests,
        "post",
        lambda url, **kwargs: posts.append(url) or FakeResponse(204),
    )

    assert state.convergir_tags_kit("lead@example.com", "boleto_pending") is True
    assert posts == [
        f"{state.KIT_BASE_URL}/tags/video/unsubscribe",
        f"{state.KIT_BASE_URL}/tags/abandon/unsubscribe",
        f"{state.KIT_BASE_URL}/tags/pix/unsubscribe",
    ]


def test_paid_remove_todas_recuperacoes(monkeypatch):
    posts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "video")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.setenv("TAG_PIX_ID", "pix")
    monkeypatch.setenv("TAG_BOLETO_ID", "boleto")
    monkeypatch.setattr(
        state.requests,
        "post",
        lambda url, **kwargs: posts.append(url) or FakeResponse(204),
    )

    assert state.convergir_tags_kit("lead@example.com", "paid") is True
    assert posts == [
        f"{state.KIT_BASE_URL}/tags/video/unsubscribe",
        f"{state.KIT_BASE_URL}/tags/abandon/unsubscribe",
        f"{state.KIT_BASE_URL}/tags/pix/unsubscribe",
        f"{state.KIT_BASE_URL}/tags/boleto/unsubscribe",
    ]


def test_abandono_remove_somente_pos_clique(monkeypatch):
    posts = []
    monkeypatch.setenv("CONVERTKIT_API_SECRET", "secret")
    monkeypatch.setenv("TAG_RECUPERACAO_VIDEO_ID", "video")
    monkeypatch.setenv("TAG_ABANDONO_ID", "abandon")
    monkeypatch.setenv("TAG_PIX_ID", "pix")
    monkeypatch.setenv("TAG_BOLETO_ID", "boleto")
    monkeypatch.setattr(
        state.requests,
        "post",
        lambda url, **kwargs: posts.append(url) or FakeResponse(204),
    )

    assert state.convergir_tags_kit("lead@example.com", "abandoned") is True
    assert posts == [f"{state.KIT_BASE_URL}/tags/video/unsubscribe"]


def test_wrapper_chama_handler_principal_uma_vez(monkeypatch):
    chamadas = []

    async def fake_inner(request, background_tasks):
        chamadas.append("inner")
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "comprador_ja_pago", lambda email: False)
    monkeypatch.setattr(state, "convergir_tags_kit", lambda email, estado: True)

    resposta = asyncio.run(
        state.webhook_kiwify_com_estado(
            FakeRequest(payload_order("pix_created", "waiting_payment", "pix")),
            BackgroundTasks(),
        )
    )

    assert resposta == {"status": "processado"}
    assert chamadas == ["inner"]


def test_comprador_pago_nao_reentra_em_pix(monkeypatch):
    chamadas = []

    async def fake_inner(request, background_tasks):
        chamadas.append("inner")
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "comprador_ja_pago", lambda email: True)

    resposta = asyncio.run(
        state.webhook_kiwify_com_estado(
            FakeRequest(payload_order("pix_created", "waiting_payment", "pix")),
            BackgroundTasks(),
        )
    )

    assert resposta["status"] == "ignorado_comprador_ja_pago"
    assert resposta["status_pagamento"] == "paid"
    assert resposta["evento_ignorado"] == "pix_pending"
    assert chamadas == []


def test_comprador_pago_nao_reentra_em_boleto(monkeypatch):
    chamadas = []

    async def fake_inner(request, background_tasks):
        chamadas.append("inner")
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "comprador_ja_pago", lambda email: True)

    resposta = asyncio.run(
        state.webhook_kiwify_com_estado(
            FakeRequest(payload_order("billet_created", "waiting_payment", "boleto")),
            BackgroundTasks(),
        )
    )

    assert resposta["status"] == "ignorado_comprador_ja_pago"
    assert resposta["evento_ignorado"] == "boleto_pending"
    assert chamadas == []


def test_comprador_pago_nao_reentra_em_abandono(monkeypatch):
    chamadas = []

    async def fake_inner(request, background_tasks):
        chamadas.append("inner")
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "comprador_ja_pago", lambda email: True)

    resposta = asyncio.run(
        state.webhook_kiwify_com_estado(
            FakeRequest({"cart": {"status": "abandoned", "email": "lead@example.com"}}),
            BackgroundTasks(),
        )
    )

    assert resposta["status"] == "ignorado_comprador_ja_pago"
    assert resposta["evento_ignorado"] == "abandoned"
    assert chamadas == []


def test_paid_novo_continua_processando_normalmente(monkeypatch):
    chamadas = []

    async def fake_inner(request, background_tasks):
        chamadas.append("inner")
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "comprador_ja_pago", lambda email: True)
    monkeypatch.setattr(state, "convergir_tags_kit", lambda email, estado: True)

    resposta = asyncio.run(
        state.webhook_kiwify_com_estado(
            FakeRequest(payload_order("order_approved", "paid", "pix")),
            BackgroundTasks(),
        )
    )

    assert resposta == {"status": "processado"}
    assert chamadas == ["inner"]


def test_falha_guard_paid_forca_503(monkeypatch):
    monkeypatch.setattr(
        state,
        "comprador_ja_pago",
        lambda email: (_ for _ in ()).throw(RuntimeError("supabase indisponivel")),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            state.webhook_kiwify_com_estado(
                FakeRequest(payload_order("pix_created", "waiting_payment", "pix")),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "paid_terminal_guard_unavailable"


def test_falha_cleanup_forca_503_para_reentrega(monkeypatch):
    async def fake_inner(request, background_tasks):
        return {"status": "processado"}

    monkeypatch.setattr(state, "webhook_kiwify_com_pix", fake_inner)
    monkeypatch.setattr(state, "convergir_tags_kit", lambda email, estado: False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            state.webhook_kiwify_com_estado(
                FakeRequest(payload_order("order_approved", "paid", "boleto")),
                BackgroundTasks(),
            )
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "recovery_state_not_converged"
