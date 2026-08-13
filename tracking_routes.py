import os
import re

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from tracking_origin import hash_ip, montar_registro_click, montar_url_whatsapp

router = APIRouter()

SUPABASE_URL = "https://gwxcnczuwfrswhkzflaw.supabase.co"


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
        f"{SUPABASE_URL}/rest/v1/tracking_clicks",
        json=registro,
        headers=headers_supabase(),
        timeout=10,
    )


@router.get("/r/{codigo}")
def redirect_tracking(codigo: str, request: Request):
    """
    Registra o clique antes do WhatsApp abrir.
    Ex.: /r/yt101 -> tracking_clicks -> wa.me com token.
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
