from types import SimpleNamespace

from app.core.config import Settings
from app.services.transcript_service import (
    TranscriptService,
    get_transcription_text,
    normalize_whisper_segments,
    normalize_youtube_segments,
)


def test_normalize_youtube_segments() -> None:
    segments = normalize_youtube_segments(
        [
            {"text": " hello   world ", "start": 1.23456, "duration": 2.5},
            {"text": "", "start": 4, "duration": 1},
            {"text": "next line", "start": 5, "duration": 1.25},
        ]
    )

    assert len(segments) == 2
    assert segments[0].index == 0
    assert segments[0].start_seconds == 1.235
    assert segments[0].end_seconds == 3.735
    assert segments[0].text == "hello world"
    assert segments[1].index == 1


def test_normalize_whisper_segments_from_object() -> None:
    transcription = SimpleNamespace(
        text="Full transcript",
        segments=[
            SimpleNamespace(text=" first ", start=0.0, end=1.5),
            SimpleNamespace(text="second", start=1.5, end=4.0),
        ],
    )

    segments = normalize_whisper_segments(transcription)

    assert len(segments) == 2
    assert segments[0].duration_seconds == 1.5
    assert get_transcription_text(transcription, segments) == "Full transcript"


def test_get_transcription_text_falls_back_to_segments() -> None:
    segments = normalize_whisper_segments(
        {
            "segments": [
                {"text": "alpha", "start": 0.0, "end": 1.0},
                {"text": "beta", "start": 1.0, "end": 2.0},
            ]
        }
    )

    assert get_transcription_text({}, segments) == "alpha beta"


def test_build_youtube_proxy_config_uses_webshare_credentials() -> None:
    service = TranscriptService(
        Settings(
            webshare_proxy_username="proxy-user",
            webshare_proxy_password="proxy-pass",
            webshare_proxy_locations="DE,US",
        )
    )

    proxy_config = service._build_youtube_proxy_config()

    assert proxy_config is not None
    proxy_url = proxy_config.to_requests_dict()["http"]
    assert proxy_url.startswith("http://proxy-user-DE-US-rotate:proxy-pass@")
    assert proxy_url.endswith("@p.webshare.io:80/")


def test_build_youtube_proxy_config_prefers_exact_proxy_url() -> None:
    service = TranscriptService(
        Settings(
            webshare_proxy_username="proxy-user",
            webshare_proxy_password="proxy-pass",
            webshare_proxy_url="http://proxy-user-GB-1:proxy-pass@p.webshare.io:80/",
        )
    )

    proxy_config = service._build_youtube_proxy_config()

    assert proxy_config is not None
    proxy_urls = proxy_config.to_requests_dict()
    assert proxy_urls["http"] == "http://proxy-user-GB-1:proxy-pass@p.webshare.io:80/"
    assert proxy_urls["https"] == "http://proxy-user-GB-1:proxy-pass@p.webshare.io:80/"


def test_build_youtube_proxy_config_is_optional() -> None:
    service = TranscriptService(Settings())

    assert service._build_youtube_proxy_config() is None
