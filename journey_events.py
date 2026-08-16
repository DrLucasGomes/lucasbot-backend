from typing import Any
from uuid import UUID, uuid4

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from tracking_routes import SUPABASE_URL, headers_supabase

router = APIRouter(prefix="/journey", tags=["journey"])

ALLOWED_EVENT_NAMES = {
    "step_started",
    "step_answered",
    "fallback_triggered",
    "email_captured",
    "offer_clicked",
    "checkout_started",
    "purchase",
}


class JourneyEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: str | None = None
    journey_run_id: UUID | None = None
    manychat_id: str
    event_name: str
    event_stage: str | None = None
    event_value: str | None = None
    source_system: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    dedupe_key: str

    @field_validator("manychat_id")
    @classmethod
    def validar_manychat_id(cls, valor: str) -> str:
        valor = str(valor).strip()
        if not valor:
            raise ValueError("manychat_id obrigatorio")
        return valor

    @field_validator("event_name")
    @classmethod
    def validar_event_name(cls, valor: str) -> str:
        valor = str(valor).strip()
        if valor not in ALLOWED_EVENT_NAMES:
            raise ValueError(
                "event_name invalido; valores permitidos: " + ", ".join(sorted(ALLOWED_EVENT_NAMES))
            )
        return valor

    @field_validator("source_system")
    @classmethod
    def validar_source_system(cls, valor: str) -> str:
        valor = str(valor).strip()
        if not valor:
            raise ValueError("source_system obrigatorio")
        return valor

    @field_validator("dedupe_key")
    @classmethod
    def validar_dedupe_key(cls, valor: str) -> str:
        valor = str(valor).strip()
        if not valor:
            raise ValueError("dedupe_key obrigatorio e nao vazio")
        return valor


def registrar_evento_jornada(payload: JourneyEventPayload) -> dict:
    dedupe_key = payload.dedupe_key
    corpo = {
        "lead_id": payload.lead_id,
        "journey_run_id": str(payload.journey_run_id) if payload.journey_run_id else None,
        "manychat_id": payload.manychat_id,
        "event_name": payload.event_name,
        "event_stage": payload.event_stage.strip() if payload.event_stage else None,
        "event_value": payload.event_value.strip() if payload.event_value else None,
        "source_system": payload.source_system,
        "dedupe_key": dedupe_key,
        "metadata": payload.metadata or {},
    }

    try:
        resposta = requests.post(
            f"{SUPABASE_URL}/rest/v1/journey_events",
            json=corpo,
            headers={**headers_supabase(), "Prefer": "return=representation"},
            timeout=3,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        return {
            "status": "journey_event_failed",
            "dedupe_key": dedupe_key,
            "detail": f"Falha ao persistir evento: {str(exc)}",
            "idempotent": False,
        }

    if resposta.status_code in (200, 201, 204):
        return {
            "status": "accepted",
            "dedupe_key": dedupe_key,
            "idempotent": False,
            "payload": corpo,
        }

    payload_text = getattr(resposta, "text", "") or ""
    codigo_postgres = None
    try:
        payload_json = resposta.json()
        if isinstance(payload_json, dict):
            codigo_postgres = payload_json.get("code")
    except Exception:
        codigo_postgres = None

    if resposta.status_code == 409 and codigo_postgres == "23505":
        return {
            "status": "accepted",
            "dedupe_key": dedupe_key,
            "idempotent": True,
            "payload": corpo,
            "detail": "dedupe_key duplicado",
        }

    return {
        "status": "journey_event_failed",
        "dedupe_key": dedupe_key,
        "idempotent": False,
        "payload": corpo,
        "detail": payload_text[:1000] if payload_text else "Falha ao persistir evento",
    }


@router.post("/event")
def evento_jornada(payload: JourneyEventPayload):
    resultado = registrar_evento_jornada(payload)

    if resultado["status"] == "accepted":
        return {
            "status": "accepted",
            "idempotent": bool(resultado.get("idempotent")),
            "dedupe_key": resultado["dedupe_key"],
            "event_name": payload.event_name,
            "manychat_id": payload.manychat_id,
            "journey_run_id": str(payload.journey_run_id) if payload.journey_run_id else None,
        }

    return {
        "status": "journey_event_failed",
        "idempotent": False,
        "dedupe_key": resultado["dedupe_key"],
        "detail": resultado.get("detail"),
        "event_name": payload.event_name,
        "manychat_id": payload.manychat_id,
        "journey_run_id": str(payload.journey_run_id) if payload.journey_run_id else None,
    }


@router.post("/run")
def criar_execucao_jornada():
    return {"journey_run_id": str(uuid4())}
