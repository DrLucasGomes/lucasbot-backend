import sys
import random
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


def lixo(rng):
    opcoes = [
        None, "", "   ", "null", "undefined", "{{campo}}", [], {}, True, False,
        "x" * 5000, "ç漢字🚀", -999999999, 10**30,
    ]
    return rng.choice(opcoes)


def test_fuzz_limpeza_payload_1000_casos_deterministicos():
    rng = random.Random(360)
    chaves = list(main.CAMPOS_PERMITIDOS) + ["admin", "role", "sql", "__proto__", "campo_invasor"]

    for i in range(1000):
        payload = {}
        for _ in range(rng.randint(0, 25)):
            payload[rng.choice(chaves)] = lixo(rng)
        if i % 3 == 0:
            payload["manychat_id"] = f"mc-fuzz-{i}"
        resultado = main.limpar_payload_supabase(payload)
        assert isinstance(resultado, dict)
        assert set(resultado).issubset(main.CAMPOS_PERMITIDOS)
        assert "admin" not in resultado
        assert "role" not in resultado
        assert "sql" not in resultado
        assert "__proto__" not in resultado
        assert "campo_invasor" not in resultado


def test_fuzz_tracking_500_estruturas_nao_quebra():
    rng = random.Random(361)
    for i in range(500):
        obj = {
            "nivel": [
                {"lixo": lixo(rng)},
                {"mais": {"valor": lixo(rng)}},
            ]
        }
        if i % 7 == 0:
            obj["nivel"].append({"tracking": {"src": f"mc_{i}", "utm_source": "manychat"}})
        tracking = main.extrair_tracking_kiwify(obj)
        assert isinstance(tracking, dict)
        assert set(tracking) == {
            "checkout_src", "checkout_utm_source", "checkout_utm_medium",
            "checkout_utm_campaign", "checkout_utm_content", "checkout_utm_term"
        }
        if i % 7 == 0:
            assert tracking["checkout_src"] == f"mc_{i}"


def test_fuzz_status_pagamento_pago_e_terminal_1000_combinacoes():
    rng = random.Random(362)
    pagos = list(main.STATUS_PAGOS)
    abandonos = list(main.STATUS_ABANDONO)
    for _ in range(1000):
        atual = rng.choice(pagos)
        novo = rng.choice(abandonos)
        variacoes_atual = [atual, atual.upper(), f" {atual} "]
        variacoes_novo = [novo, novo.upper(), f" {novo} "]
        resultado = main.status_pagamento_final(rng.choice(variacoes_atual), rng.choice(variacoes_novo))
        assert resultado in main.STATUS_PAGOS


def test_fuzz_manychat_id_500_strings_nao_levanta_excecao():
    rng = random.Random(363)
    alfabeto = string.ascii_letters + string.digits + "_-{} "+"ç漢🚀"
    for _ in range(500):
        tamanho = rng.randint(0, 200)
        valor = "".join(rng.choice(alfabeto) for _ in range(tamanho))
        resultado = main.manychat_id_valido(valor)
        assert isinstance(resultado, bool)
