def primeiro_nome(valor) -> str:
    if not isinstance(valor, str):
        return ""
    try:
        nome_normalizado = " ".join(valor.strip().split())
        return nome_normalizado.split(" ", 1)[0] if nome_normalizado else ""
    except Exception:
        return ""
