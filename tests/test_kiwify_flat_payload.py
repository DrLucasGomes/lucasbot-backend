import recovery_state_exclusivity as state


def test_flattened_abandoned_cart_is_classified():
    payload = {
        "checkout_link": "MQqd0hF",
        "email": "testefinal@drlucasgomes.com.br",
        "product_id": "afb21890-23c5-11f1-a244-5b39f15e41aa",
        "status": "abandoned",
        "store_id": "dz22EPfjUgWizrS",
    }
    assert state.classificar_estado_recuperacao(payload) == "abandoned"
    assert state._email(payload) == "testefinal@drlucasgomes.com.br"


def test_nested_abandoned_cart_still_works():
    payload = {"cart": {"status": "abandoned", "email": "lead@example.com"}}
    assert state.classificar_estado_recuperacao(payload) == "abandoned"


def test_flattened_pix_order_is_classified():
    payload = {
        "webhook_event_type": "pix_created",
        "order_status": "waiting_payment",
        "payment_method": "pix",
        "Customer": {"email": "lead@example.com"},
    }
    assert state.classificar_estado_recuperacao(payload) == "pix_pending"
    assert state._email(payload) == "lead@example.com"


def test_flattened_boleto_and_paid_orders_are_classified():
    boleto = {
        "webhook_event_type": "billet_created",
        "order_status": "waiting_payment",
        "payment_method": "boleto",
        "Customer": {"email": "lead@example.com"},
    }
    paid = {
        "webhook_event_type": "order_approved",
        "order_status": "paid",
        "payment_method": "boleto",
        "Customer": {"email": "lead@example.com"},
    }
    assert state.classificar_estado_recuperacao(boleto) == "boleto_pending"
    assert state.classificar_estado_recuperacao(paid) == "paid"
