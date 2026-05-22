from types import SimpleNamespace

from app.services.transcript_service import (
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
