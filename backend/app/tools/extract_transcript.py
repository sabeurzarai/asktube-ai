from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.services.transcript_service import TranscriptFetchOptions, TranscriptService


class ExtractTranscriptInput(BaseModel):
    video_id: str = Field(description="YouTube video ID (e.g. 'dQw4w9WgXcQ')")
    language: str = Field(default="en", description="BCP-47 language code for the transcript")
    use_whisper_fallback: bool = Field(
        default=True,
        description="Fall back to Whisper transcription when no YouTube transcript is available",
    )


def make_extract_transcript_tool(service: TranscriptService) -> StructuredTool:
    async def _run(
        video_id: str,
        language: str = "en",
        use_whisper_fallback: bool = True,
    ) -> dict:
        options = TranscriptFetchOptions(language=language, use_whisper_fallback=use_whisper_fallback)
        result = await service.get_transcript(video_id=video_id, options=options)
        return result.model_dump()

    return StructuredTool.from_function(
        coroutine=_run,
        name="extract_transcript",
        description=(
            "Fetch the timestamped transcript for a YouTube video by its video ID. "
            "Returns transcript segments with start/end times and the full concatenated text."
        ),
        args_schema=ExtractTranscriptInput,
    )
