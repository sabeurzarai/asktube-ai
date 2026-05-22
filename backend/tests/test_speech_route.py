import io
import math
import struct
import wave
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wav_bytes(duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generate a minimal mono PCM WAV file (sine wave - not real speech)."""
    buf = io.BytesIO()
    n_frames = int(sample_rate * duration_seconds)
    with wave.open(buf, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_frames):
            value = int(32767 * math.sin(2 * math.pi * 440 * i / sample_rate))
            wf.writeframes(struct.pack("<h", value))
    return buf.getvalue()


def _mock_transcription(text: str) -> MagicMock:
    result = MagicMock()
    result.text = text
    return result


# ---------------------------------------------------------------------------
# Tests - happy path
# ---------------------------------------------------------------------------

def test_speech_transcribe_returns_transcript() -> None:
    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=_mock_transcription("  python tutorial  ")
        )
        mock_cls.return_value = mock_client

        client = TestClient(app)
        response = client.post(
            "/api/speech/transcribe",
            files={"audio": ("speech.wav", make_wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 200
    assert response.json()["transcript"] == "python tutorial"


def test_speech_transcribe_strips_whitespace() -> None:
    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=_mock_transcription("  hello world\n")
        )
        mock_cls.return_value = mock_client

        response = TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
        )

    assert response.json()["transcript"] == "hello world"


def test_speech_transcribe_passes_whisper_model_from_settings() -> None:
    captured: dict = {}

    async def fake_create(**kwargs):  # noqa: ANN002
        captured.update(kwargs)
        return _mock_transcription("ok")

    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(side_effect=fake_create)
        mock_cls.return_value = mock_client

        TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
        )

    assert captured["model"] in ("whisper-1", "whisper-large-v3")


def test_speech_transcribe_accepts_webm_content_type() -> None:
    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=_mock_transcription("webm audio")
        )
        mock_cls.return_value = mock_client

        # Use a real-sized payload (>1500 bytes) so the minimum size check passes
        response = TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("speech.webm", b"\x00" * 2000, "audio/webm")},
        )

    assert response.status_code == 200
    assert response.json()["transcript"] == "webm audio"


# ---------------------------------------------------------------------------
# Tests - error handling
# ---------------------------------------------------------------------------

def test_speech_transcribe_returns_503_without_api_key() -> None:
    from app.core.config import Settings
    from app.api.routes.speech import router

    with patch("app.api.routes.speech.settings", Settings(openai_api_key=None)):
        response = TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 503


def test_speech_transcribe_returns_502_on_openai_error() -> None:
    from openai import OpenAIError

    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=OpenAIError("API failure")
        )
        mock_cls.return_value = mock_client

        response = TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
        )

    assert response.status_code == 502


def test_speech_transcribe_returns_422_without_file() -> None:
    response = TestClient(app).post("/api/speech/transcribe")
    assert response.status_code == 422


def test_speech_transcribe_returns_empty_on_tiny_file() -> None:
    """Files under 1500 bytes are almost certainly silence - return empty string."""
    response = TestClient(app).post(
        "/api/speech/transcribe",
        files={"audio": ("tiny.wav", b"\x00" * 100, "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["transcript"] == ""


def test_speech_transcribe_filters_whisper_hallucination() -> None:
    """Known Whisper hallucinations on silence must be filtered to empty string."""
    for phrase in ["You.", "you", "Thank you.", "Thanks for watching."]:
        with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
            mock_client = MagicMock()
            mock_client.audio.transcriptions.create = AsyncMock(
                return_value=_mock_transcription(phrase)
            )
            mock_cls.return_value = mock_client

            response = TestClient(app).post(
                "/api/speech/transcribe",
                files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
            )

        assert response.json()["transcript"] == "", f"Expected empty for hallucination: {phrase!r}"


def test_speech_transcribe_passes_prompt_to_whisper() -> None:
    """Whisper must receive a prompt to reduce hallucination on short audio."""
    captured: dict = {}

    async def fake_create(**kwargs):  # noqa: ANN002
        captured.update(kwargs)
        return _mock_transcription("python tutorial")

    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(side_effect=fake_create)
        mock_cls.return_value = mock_client

        TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("s.wav", make_wav_bytes(), "audio/wav")},
        )

    assert "prompt" in captured, "Whisper must receive a prompt parameter"
    assert captured["prompt"]


# ---------------------------------------------------------------------------
# Live endpoint smoke test (uses real API key from .env)
# ---------------------------------------------------------------------------

def test_speech_transcribe_endpoint_is_reachable() -> None:
    """Confirm route is registered and reachable (mocked - no real API call)."""
    with patch("app.api.routes.speech.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=_mock_transcription("reachable")
        )
        mock_cls.return_value = mock_client

        r = TestClient(app).post(
            "/api/speech/transcribe",
            files={"audio": ("ping.wav", make_wav_bytes(), "audio/wav")},
        )

    assert r.status_code == 200
    assert "transcript" in r.json()
