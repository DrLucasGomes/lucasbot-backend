import sys
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


def aplicar_sequencia(eventos):
    estado = None
    for evento in eventos:
        estado = main.status_pagamento_final(estado, evento)
    return estado


def test_stress_ordem_aleatoria_paid_e_abandoned_2000_vezes():
    rng = random.Random(360360)
    for _ in range(2000):
        eventos = ["paid"] * rng.randint(1, 8) + ["abandoned"] * rng.randint(1, 8)
        rng.shuffle(eventos)
        assert aplicar_sequencia(eventos) in main.STATUS_PAGOS


def test_stress_todos_status_pagamento_com_duplicatas():
    rng = random.Random(777)
    for _ in range(1000):
        pago = rng.choice(list(main.STATUS_PAGOS))
        eventos = [
            rng.choice(list(main.STATUS_ABANDONO)),
            pago,
            rng.choice(list(main.STATUS_ABANDONO)),
            pago,
            rng.choice(list(main.STATUS_ABANDONO)),
        ]
        rng.shuffle(eventos)
        assert aplicar_sequencia(eventos) in main.STATUS_PAGOS


def test_abandono_sem_pagamento_continua_abandono():
    assert aplicar_sequencia(["abandoned", "cart_abandoned", "abandoned"]) in main.STATUS_ABANDONO


def test_pago_repetido_100_vezes_permanece_terminal():
    assert aplicar_sequencia(["paid"] * 100) == "paid"
