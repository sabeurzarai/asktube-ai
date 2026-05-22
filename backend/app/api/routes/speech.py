from fastapi import APIRouter, File, HTTPException, UploadFile, status
from openai import AsyncOpenAI, OpenAIError

from app.core.config import settings

router = APIRouter()

# Whisper hallucinates these phrases on silence / very short audio.
_HALLUCINATIONS = {
    "you", "you.", "thank you", "thank you.", "thanks for watching.",
    "thanks for watching", "bye", "bye.", "goodbye.", "goodbye",
    "please subscribe", "subscribe", "like and subscribe",
    "see you next time.", "see you next time",
}

# Minimum audio payload - anything smaller is almost certainly silence.
_MIN_AUDIO_BYTES = 1_500


@router.post("/speech/transcribe")
async def transcribe_speech(audio: UploadFile = File(...)) -> dict[str, str]:
    """Transcribe browser-recorded audio via OpenAI Whisper.

    Used as a fallback when the browser Web Speech API is unavailable
    (network error, missing HTTPS, regional block, etc.).
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is required for speech transcription.",
        )

    audio_bytes = await audio.read()

    if len(audio_bytes) < _MIN_AUDIO_BYTES:
        return {"transcript": ""}

    filename = audio.filename or "speech.webm"
    content_type = audio.content_type or "audio/webm"
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        transcription = await client.audio.transcriptions.create(
            model=settings.whisper_model,
            file=(filename, audio_bytes, content_type),
            # Prompt steers Whisper toward search-query style output and away
            # from common hallucinated filler phrases.
            prompt="YouTube search query:",
        )
    except OpenAIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Speech transcription failed.",
        ) from exc

    text = transcription.text.strip()

    # Discard known Whisper hallucinations on silence
    if text.lower() in _HALLUCINATIONS:
        return {"transcript": ""}

    return {"transcript": text}
