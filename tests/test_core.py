import sys
from pathlib import Path

import pytest

# Garante que a raiz do repositorio (onde esta main.py) esteja no sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


@pytest.mark.parametrize("valor", [None, "", "   ", "none", "NULL", "undefined", "{{cuf_14421642}}", "abc{{x}}def"])
def test_valor_valido_rejeita_lixo(valor):
    assert main.valor_valido(valor) is False


@pytest.mark.parametrize("valor", ["Lucas", "0", 0, 45, "eric@yahoo.com", "facebook_direto"])
def test_valor_valido_aceita_valores_reais(valor):
    assert main.valor_valido(valor) is True


def test_limpar_telefone_remove_formatacao():
    assert main.limpar_telefone("+55 (49) 99974-4429") == "5549999744429"


def test_limpar_payload_remove_campos_nao_permitidos_e_placeholders():
    dados = {
        "manychat_id": "123",
        "idade": "45",
        "score": "7",
        "telefone": "+55 (49) 99974-4429",
        "campanha": "{{cuf_123}}",
        "campo_invasor": "nao_deve_entrar",
    }
    assert main.limpar_payload_supabase(dados) == {
        "manychat_id": "123",
        "idade": 45,
        "score": 7,
        "telefone": "5549999744429",
    }


def test_limpar_payload_descarta_numerico_invalido():
    dados = {"manychat_id": "123", "idade": "quarenta", "score": "x"}
    assert main.limpar_payload_supabase(dados) == {"manychat_id": "123"}


def test_extrair_manychat_id_do_src():
    assert main.extrair_manychat_id_do_src("mc_987654") == "987654"
    assert main.extrair_manychat_id_do_src("youtube_direto") is None


@pytest.mark.parametrize(
    "src,utm,esperado",
    [
        ("mc_123", None, "manychat"),
        (None, "manychat", "manychat"),
        ("youtube_direto", None, "youtube_direto"),
        (None, "youtube", "youtube_direto"),
        ("facebook_direto", None, "facebook_direto"),
        (None, "meta", "facebook_direto"),
        ("instagram_direto", None, "instagram_direto"),
        ("vsl", None, "pagina_vendas"),
        ("campanha_x", None, "rastreado_outro"),
        (None, None, "desconhecida"),
    ],
)
def test_classificar_origem_compra(src, utm, esperado):
    assert main.classificar_origem_compra(src, utm) == esperado


def test_buscar_valor_recursivo_em_objeto_profundo():
    dados = {"data": {"tracking": {"utm_campaign": "campanha_vigor"}}}
    assert main.buscar_valor_recursivo(dados, ["utm_campaign"]) == "campanha_vigor"


def test_extrair_tracking_de_url():
    dados = {
        "payment_url": "https://checkout.exemplo.com/pagar?src=facebook_direto&utm_source=facebook&utm_campaign=vigor"
    }
    tracking = main.extrair_tracking_kiwify(dados)
    assert tracking["checkout_src"] == "facebook_direto"
    assert tracking["checkout_utm_source"] == "facebook"
    assert tracking["checkout_utm_campaign"] == "vigor"


def test_tracking_chave_direta_tem_prioridade():
    dados = {
        "src": "mc_123456",
        "utm_source": "manychat",
        "payment_url": "https://checkout.exemplo.com/?src=facebook_direto&utm_source=facebook",
    }
    tracking = main.extrair_tracking_kiwify(dados)
    assert tracking["checkout_src"] == "mc_123456"
    assert tracking["checkout_utm_source"] == "manychat"


@pytest.mark.parametrize("valor", ["{{email}}", "prefixo{{campo}}", "{{campo}}sufixo", " undefined ", " NULL "])
def test_valor_valido_rejeita_placeholders_e_nulos_com_espacos(valor):
    assert main.valor_valido(valor) is False


@pytest.mark.parametrize("valor", [None, "", "none", "null", "undefined", "{{manychat_id}}"])
def test_manychat_id_valido_rejeita_identificadores_quebrados(valor):
    assert main.manychat_id_valido(valor) is False


def test_limpar_telefone_sem_digitos_retorna_none():
    assert main.limpar_telefone("telefone-invalido") is None


def test_limpar_payload_preserva_email_e_campos_de_negocio_validos():
    dados = {
        "email": "  eric@yahoo.com  ",
        "status_testosterona": "Baixa Confirmada",
        "tempo_sintoma": "3-12 meses",
        "risco": "Sim",
        "origem": "youtube",
    }
    assert main.limpar_payload_supabase(dados) == {
        "email": "eric@yahoo.com",
        "status_testosterona": "Baixa Confirmada",
        "tempo_sintoma": "3-12 meses",
        "risco": "Sim",
        "origem": "youtube",
    }


def test_limpar_payload_nao_aceita_campo_arbitrario_mesmo_com_valor_valido():
    assert main.limpar_payload_supabase({"admin": "true", "manychat_id": "42"}) == {"manychat_id": "42"}


@pytest.mark.parametrize("atual", ["paid", "approved", "order_approved", " PAID "])
@pytest.mark.parametrize("novo", ["abandoned", "cart_abandoned", " ABANDONED "])
def test_status_pago_nunca_e_rebaixado_por_abandono_atrasado(atual, novo):
    assert main.status_pagamento_final(atual, novo).strip().lower() in main.STATUS_PAGOS


@pytest.mark.parametrize("novo", ["paid", "approved", "order_approved"])
def test_status_abandonado_pode_subir_para_pago(novo):
    assert main.status_pagamento_final("abandoned", novo) == novo


def test_status_repetido_pago_permanece_pago():
    assert main.status_pagamento_final("paid", "paid") == "paid"


def test_status_sem_estado_anterior_aceita_novo_estado():
    assert main.status_pagamento_final(None, "abandoned") == "abandoned"


def test_tracking_recursivo_em_lista_profunda():
    dados = {"events": [{"metadata": {}}, {"metadata": {"utm_content": "video_17"}}]}
    assert main.buscar_valor_recursivo(dados, ["utm_content"]) == "video_17"


def test_tracking_url_extrai_utm_term():
    dados = {"url": "https://checkout.exemplo.com/?utm_term=erecao%20forte"}
    tracking = main.extrair_tracking_kiwify(dados)
    assert tracking["checkout_utm_term"] == "erecao forte"


def test_src_manychat_com_espacos_extrai_id():
    assert main.extrair_manychat_id_do_src("  mc_987654  ") == "987654"
