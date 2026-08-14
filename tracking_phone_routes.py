import os

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from tracking_origin import hash_ip, montar_registro_click, montar_url_whatsapp
from tracking_routes import SUPABASE_URL, headers_supabase, interpretar_codigo, extrair_ip

router = APIRouter()


def normalizar_telefone(valor: str) -> str | None:
    digitos = "".join(ch for ch in str(valor or "") if ch.isdigit())
    return digitos if len(digitos) >= 10 else None


def salvar_sessao(registro: dict):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        json=registro,
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code not in (200, 201, 204):
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")


def buscar_sessao(token: str):
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        params={"token": f"eq.{token}", "claimed": "eq.false", "select": "*", "limit": "1"},
        headers=headers_supabase(),
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")
    dados = r.json()
    return dados[0] if isinstance(dados, list) and dados else None


def salvar_telefone(token: str, telefone: str):
    # Exige retorno da linha alterada e depois relê a sessão. Assim só abrimos o
    # WhatsApp quando tivermos certeza de que o telefone realmente persistiu.
    headers = headers_supabase()
    headers["Prefer"] = "return=representation"

    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/click_sessions",
        params={"token": f"eq.{token}", "claimed": "eq.false"},
        json={"telefone": telefone},
        headers=headers,
        timeout=10,
    )
    if r.status_code not in (200, 204):
        raise HTTPException(status_code=502, detail=f"Supabase {r.status_code}: {r.text[:1000]}")

    try:
        alteradas = r.json()
    except Exception:
        alteradas = []

    if not isinstance(alteradas, list) or not alteradas:
        raise HTTPException(status_code=409, detail="telefone nao persistido: nenhuma linha atualizada")

    telefone_retornado = str(alteradas[0].get("telefone") or "")
    if telefone_retornado != telefone:
        raise HTTPException(status_code=409, detail="telefone nao persistido corretamente")

    confirmacao = buscar_sessao(token)
    if not confirmacao or str(confirmacao.get("telefone") or "") != telefone:
        raise HTTPException(status_code=409, detail="telefone nao confirmado apos gravacao")

    return confirmacao


@router.get("/p/{codigo}", response_class=HTMLResponse)
def pagina_tracking(codigo: str, request: Request):
    try:
        meta = interpretar_codigo(codigo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    registro = montar_registro_click(
        **meta,
        user_agent=request.headers.get("user-agent"),
        ip_hash=hash_ip(extrair_ip(request), os.getenv("TRACKING_IP_SALT", "")),
    )
    salvar_sessao(registro)

    return HTMLResponse(f"""
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Continuar no WhatsApp</title>
  <style>
    body{{font-family:Arial,sans-serif;max-width:520px;margin:48px auto;padding:0 20px;line-height:1.4}}
    input,button{{width:100%;box-sizing:border-box;padding:14px;font-size:18px;margin-top:12px}}
    button{{cursor:pointer;font-weight:700}}
    small{{display:block;margin-top:12px}}
  </style>
</head>
<body>
  <h2>Continuar no WhatsApp</h2>
  <p>Digite o número do WhatsApp que você usa para falar com o LucasBot.</p>
  <form method="get" action="/tracking/phone/{registro['token']}">
    <input name="telefone" inputmode="tel" autocomplete="tel" placeholder="Ex.: +55 49 99999-9999" required>
    <button type="submit">Abrir WhatsApp</button>
  </form>
  <small>Usaremos o número somente para associar sua origem ao atendimento.</small>
</body>
</html>
""")


@router.get("/tracking/phone/{token}")
def registrar_telefone_e_abrir_whatsapp(token: str, telefone: str):
    tel = normalizar_telefone(telefone)
    if not tel:
        raise HTTPException(status_code=400, detail="telefone invalido")

    sessao = buscar_sessao(token)
    if not sessao:
        raise HTTPException(status_code=404, detail="sessao nao encontrada ou ja utilizada")

    salvar_telefone(token, tel)

    numero_destino = os.getenv("WHATSAPP_NUMBER")
    if not numero_destino:
        raise HTTPException(status_code=503, detail="WHATSAPP_NUMBER nao configurado")

    destino = montar_url_whatsapp(numero_destino, token, mensagem_base="VIGOR")
    return RedirectResponse(url=destino, status_code=303)
