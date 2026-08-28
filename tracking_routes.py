import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from tracking_origin import hash_ip, montar_registro_click, montar_url_whatsapp

router = APIRouter()

SUPABASE_URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"
TRACKING_TABLE = "click_sessions"
DEFAULT_VSL_URL = "https://drlucasgomes.com.br/protocolo-vigor-360/"


def interpretar_codigo(codigo: str) -> dict:
    """Converte codigos curtos (yt101, fb108, ig22) em metadados de origem."""
    texto = str(codigo or "").strip().lower()
    match = re.fullmatch(r"(yt|fb|ig)(\d+)", texto)
    if not match:
        raise ValueError("codigo de rastreamento invalido")

    canal, numero = match.groups()
    mapa = {
        "yt": "YouTube",
        "fb": "Facebook",
        "ig": "Instagram",
    }

    return {
        "origem": mapa[canal],
        "campanha": f"Vigor_{canal.upper()}_{numero}",
        "video": numero,
        "produto": "Protocolo Vigor 360",
        "utm_source": mapa[canal].lower(),
        "utm_medium": "social",
        "utm_campaign": f"vigor_{canal}_{numero}",
        "utm_content": texto,
        "utm_term": None,
    }


def headers_supabase() -> dict:
    chave = os.getenv("SUPABASE_KEY")
    return {
        "apikey": chave,
        "Authorization": f"Bearer {chave}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def extrair_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def salvar_click(registro: dict):
    return requests.post(
        f"{SUPABASE_URL}/rest/v1/{TRACKING_TABLE}",
        json=registro,
        headers=headers_supabase(),
        timeout=10,
    )


def montar_url_vsl(meta: dict, token: str, base_url: str | None = None) -> str:
    """Monta a URL da VSL preservando query existente e acrescentando tracking do QR."""
    destino_base = str(base_url or os.getenv("VSL_URL") or DEFAULT_VSL_URL).strip()
    parsed = urlsplit(destino_base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("VSL_URL invalida")

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({
        "src": f"qr_{meta['utm_content']}_{token}",
        "utm_source": meta.get("utm_source"),
        "utm_medium": meta.get("utm_medium"),
        "utm_campaign": meta.get("utm_campaign"),
        "utm_content": meta.get("utm_content"),
    })
    if meta.get("utm_term"):
        query["utm_term"] = meta["utm_term"]

    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query),
        parsed.fragment,
    ))


@router.get("/r/{codigo}")
def redirect_tracking(codigo: str, request: Request):
    """
    Registra o clique antes do WhatsApp abrir.
    Ex.: /r/yt101 -> click_sessions -> wa.me com token.
    """
    try:
        meta = interpretar_codigo(codigo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    numero = os.getenv("WHATSAPP_NUMBER")
    if not numero:
        raise HTTPException(status_code=503, detail="WHATSAPP_NUMBER nao configurado")

    ip_salt = os.getenv("TRACKING_IP_SALT", "")
    registro = montar_registro_click(
        **meta,
        user_agent=request.headers.get("user-agent"),
        ip_hash=hash_ip(extrair_ip(request), ip_salt),
    )

    resposta = salvar_click(registro)
    if resposta.status_code not in (200, 201, 204):
        # Branch de teste: devolve o erro real do Supabase para diagnostico.
        detalhe = resposta.text[:1500] if resposta.text else "sem corpo de resposta"
        print(f"[TRACKING] Supabase {resposta.status_code}: {detalhe}")
        raise HTTPException(
            status_code=502,
            detail=f"Supabase {resposta.status_code}: {detalhe}",
        )

    destino = montar_url_whatsapp(numero, registro["token"], mensagem_base="VIGOR")
    return RedirectResponse(url=destino, status_code=302)


@router.get("/v/{codigo}")
def redirect_vsl_tracking(codigo: str, request: Request):
    """
    Registra o escaneamento/clique do QR e abre a VSL com atribuicao preservada.
    Ex.: /v/yt101 -> click_sessions -> VSL com src unico + UTMs.

    Diferente de /r, falha de persistencia do tracking nao bloqueia a VSL:
    perder telemetria e preferivel a perder uma visita/venda.
    """
    try:
        meta = interpretar_codigo(codigo)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    meta = dict(meta)
    meta["utm_medium"] = "qrcode"

    ip_salt = os.getenv("TRACKING_IP_SALT", "")
    registro = montar_registro_click(
        **meta,
        user_agent=request.headers.get("user-agent"),
        ip_hash=hash_ip(extrair_ip(request), ip_salt),
    )

    try:
        destino = montar_url_vsl(meta, registro["token"])
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        resposta = salvar_click(registro)
        if resposta.status_code not in (200, 201, 204):
            detalhe = resposta.text[:500] if resposta.text else "sem corpo de resposta"
            print(f"[TRACKING VSL] Supabase {resposta.status_code}: {detalhe}")
    except requests.RequestException as exc:
        print(f"[TRACKING VSL] Falha ao persistir click: {type(exc).__name__}")

    return RedirectResponse(url=destino, status_code=302)
