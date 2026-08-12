import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


class EmptyResponse:
    status_code = 200
    text = "[]"

    def json(self):
        return []


@pytest.fixture(autouse=True)
def bloquear_get_externo_por_padrao(monkeypatch):
    """Evita que testes sem mock explicito consultem Supabase/ManyChat reais."""
    monkeypatch.setattr(main.requests, "get", lambda *args, **kwargs: EmptyResponse())
