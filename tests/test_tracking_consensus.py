import tracking_claim_routes as c


def click(origem, campanha, video, token):
    return {
        "origem": origem,
        "campanha": campanha,
        "video": video,
        "token": token,
    }


def test_um_click_recente_vira_inferencia_media():
    candidato, metodo, confianca = c.escolher_candidato_inferido([
        click("YouTube", "Vigor_YT_101", "101", "A")
    ])
    assert candidato["token"] == "A"
    assert metodo == "recent_unique_click"
    assert confianca == "medium"


def test_multiplos_clicks_mesma_campanha_permite_consenso():
    clicks = [
        click("YouTube", "Vigor_YT_101", "101", "NOVO"),
        click("YouTube", "Vigor_YT_101", "101", "ANTIGO"),
        click("youtube", "vigor_yt_101", "101", "OUTRO"),
    ]
    candidato, metodo, confianca = c.escolher_candidato_inferido(clicks)
    assert candidato["token"] == "NOVO"
    assert metodo == "recent_campaign_consensus"
    assert confianca == "high"


def test_multiplos_clicks_campanhas_diferentes_nao_atribui():
    clicks = [
        click("YouTube", "Vigor_YT_101", "101", "A"),
        click("Facebook", "Vigor_FB_108", "108", "B"),
    ]
    candidato, metodo, confianca = c.escolher_candidato_inferido(clicks)
    assert candidato is None
    assert metodo is None
    assert confianca is None


def test_mesma_origem_mas_video_diferente_nao_atribui():
    clicks = [
        click("YouTube", "Vigor_YT_101", "101", "A"),
        click("YouTube", "Vigor_YT_102", "102", "B"),
    ]
    candidato, metodo, confianca = c.escolher_candidato_inferido(clicks)
    assert candidato is None
    assert metodo is None
    assert confianca is None


def test_sem_click_nao_atribui():
    assert c.escolher_candidato_inferido([]) == (None, None, None)
