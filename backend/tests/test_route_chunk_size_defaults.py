"""The two route defaults that determine chunk size for API callers.

Four call sites once hardcoded 1200 and ignored CHUNK_MAX_CHARS entirely, so
changing the setting silently did nothing on those paths. Two of them - the
`chunk_transcript` and `ingest_video` tools - already have guards in
`test_tools.py`. These are the other two, and they were the ones left untested.

The assertion is read from the OpenAPI schema rather than from the function
signature on purpose: the schema is what a client is told the default is, and
what FastAPI actually applies when the parameter is omitted. A signature check
would pass even if the parameter stopped being wired into the route.

The limit is worth stating plainly: because `Query(default=...)` is evaluated at
import time, this cannot catch a hardcoded literal that happens to equal the
current setting. It catches the regression that matters - the setting moving
while a call site stays behind - which is exactly what happened before.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def max_chunk_chars_default(path: str, method: str) -> int | None:
    """The default the OpenAPI schema advertises for max_chunk_chars."""
    operation = app.openapi()["paths"][path][method]
    for parameter in operation.get("parameters", []):
        if parameter["name"] == "max_chunk_chars":
            return parameter["schema"].get("default")
    return None


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/videos/{video_id}/chunks", "get"),
        ("/api/videos/{video_id}/ingest", "post"),
    ],
)
def test_route_default_chunk_size_follows_the_setting(path: str, method: str) -> None:
    assert max_chunk_chars_default(path, method) == settings.chunk_max_chars


def test_the_parameter_is_actually_exposed() -> None:
    """Guards the guard above: a missing parameter must not read as a pass.

    max_chunk_chars_default returns None when the parameter is absent, and None
    would only equal the setting if the setting were None - which it cannot be.
    This makes that reasoning explicit rather than relying on it.
    """
    assert max_chunk_chars_default("/api/videos/{video_id}/chunks", "get") is not None
    assert max_chunk_chars_default("/api/videos/{video_id}/ingest", "post") is not None
    assert isinstance(settings.chunk_max_chars, int)


def test_the_app_still_serves_its_schema() -> None:
    """The schema above is read from the app object; confirm it is the served one."""
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    parameters = response.json()["paths"]["/api/videos/{video_id}/chunks"]["get"]["parameters"]
    served = next(p for p in parameters if p["name"] == "max_chunk_chars")
    assert served["schema"]["default"] == settings.chunk_max_chars
