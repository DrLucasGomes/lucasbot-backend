from datetime import datetime, timedelta, timezone

import tracking_origin as t


def test_token_e_url_safe_e_nao_vazio():
    token = t.gerar_token()
    assert isinstance(token, str)
    assert len(token) >= 10
    assert " " not in token


def test_hash_ip_e_deterministico_e_nao_expoe_ip():
    h1 = t.hash_ip("200.100.50.25", "segredo")
    h2 = t.hash_ip("200.100.50.25", "segredo")
    assert h1 == h2
    assert "200.100.50.25" not in h1


def test_montar_registro_click_preenche_campos_e_expiracao():
    agora = datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc)
    reg = t.montar_registro_click(
        origem="YouTube",
        campanha="YT_101",
        video="101",
        produto="Vigor360",
        utm_source="youtube",
        utm_medium="organic",
        utm_campaign="vigor_yt_101",
        token="ABC123",
        agora=agora,
    )

    assert reg["token"] == "ABC123"
    assert reg["origem"] == "YouTube"
    assert reg["campanha"] == "YT_101"
    assert reg["video"] == "101"
    assert reg["claimed"] is False
    assert reg["manychat_id"] is None
    assert reg["created_at"] == agora.isoformat()
    assert reg["expires_at"] == (agora + timedelta(minutes=t.TRACKING_TTL_MINUTES)).isoformat()


def test_url_whatsapp_carrega_token_na_mensagem():
    url = t.montar_url_whatsapp("+55 (49) 99999-9999", "TOK123", "VIGOR_YT_101")
    assert url.startswith("https://wa.me/5549999999999?")
    assert "TOK123" in url
    assert "VIGOR_YT_101" in url


def test_registro_expira_no_limite():
    agora = datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc)
    reg = t.montar_registro_click(origem="Facebook", token="X", agora=agora)
    assert t.registro_expirado(reg, agora + timedelta(minutes=29)) is False
    assert t.registro_expirado(reg, agora + timedelta(minutes=30)) is True


def test_claim_exato_marca_token_como_usado():
    agora = datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc)
    reg = t.montar_registro_click(origem="Instagram", token="XYZ", agora=agora)
    claim = t.claim_exato(reg, manychat_id="871284804", lead_id="lead-1", agora=agora + timedelta(seconds=10))

    assert claim["claimed"] is True
    assert claim["manychat_id"] == "871284804"
    assert claim["lead_id"] == "lead-1"
    assert claim["claim_method"] == "token"
    assert claim["claim_confidence"] == "exact"
    assert claim["claimed_at"] is not None
    assert reg["claimed"] is False
