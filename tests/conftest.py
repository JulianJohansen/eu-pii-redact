import os
import sys
from pathlib import Path

import pytest

# The API source lives next to this repo during development; tests run it in-process.
API_SRC = Path(os.environ.get("REDACT_API_SRC", Path(__file__).resolve().parents[2] / "redact-api" / "src"))


@pytest.fixture
def api_http():
    if not API_SRC.is_dir():
        pytest.skip(f"API source not found at {API_SRC} (set REDACT_API_SRC)")
    sys.path.insert(0, str(API_SRC))
    os.environ["PROXY_SECRET"] = "test-secret"
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, headers={"X-RapidAPI-Proxy-Secret": "test-secret"}) as client:
        yield client


@pytest.fixture
def redactor(api_http):
    from eu_pii_redact import Redactor
    return Redactor(http=api_http)
