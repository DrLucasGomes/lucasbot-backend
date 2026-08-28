import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


def test_classifica_qrcode_por_canal():
    casos = [
        ("qr_yt101", "youtube", "qrcode", "youtube_qrcode"),
        ("qr_fb108", "facebook", "qrcode", "facebook_qrcode"),
        ("qr_ig22", "instagram", "qrcode", "instagram_qrcode"),
        ("qr_pdf101", "pdf", "qrcode", "pdf_qrcode"),
    ]

    for src, source, medium, esperado in casos:
        assert main.classificar_origem_compra(src, source, medium) == esperado


def test_prefixo_qr_e_suficiente_quando_medium_nao_vem():
    assert main.classificar_origem_compra("qr_pdf101", None, None) == "pdf_qrcode"
    assert main.classificar_origem_compra("qr_yt101", None, None) == "youtube_qrcode"


def test_qrcode_desconhecido_fica_explicito():
    assert main.classificar_origem_compra("qr_parceiro01", "parceiro", "qrcode") == "qrcode_outro"


def test_origens_diretas_continuam_iguais():
    assert main.classificar_origem_compra("youtube_direto", "youtube", "video") == "youtube_direto"
    assert main.classificar_origem_compra("facebook_direto", "facebook", "social") == "facebook_direto"
    assert main.classificar_origem_compra("instagram_direto", "instagram", "social") == "instagram_direto"
    assert main.classificar_origem_compra("pdf_direto", "pdf", "documento") == "pdf_direto"


def test_manychat_tem_precedencia():
    assert main.classificar_origem_compra("mc_123456", "manychat", "qrcode") == "manychat"


def test_payload_realista_kiwify_pdf_qr():
    payload = {
        "order": {
            "order_status": "paid",
            "TrackingParameters": {
                "src": "qr_pdf101",
                "utm_source": "pdf",
                "utm_medium": "qrcode",
                "utm_campaign": "vigor_pdf_101",
                "utm_content": "pdf101",
                "utm_term": "TOKEN_EXEMPLO",
            },
        }
    }

    tracking = main.extrair_tracking_kiwify(payload)

    assert tracking == {
        "checkout_src": "qr_pdf101",
        "checkout_utm_source": "pdf",
        "checkout_utm_medium": "qrcode",
        "checkout_utm_campaign": "vigor_pdf_101",
        "checkout_utm_content": "pdf101",
        "checkout_utm_term": "TOKEN_EXEMPLO",
    }
    assert main.classificar_origem_compra(
        tracking["checkout_src"],
        tracking["checkout_utm_source"],
        tracking["checkout_utm_medium"],
    ) == "pdf_qrcode"
