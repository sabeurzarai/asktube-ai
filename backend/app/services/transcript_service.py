import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from openai import AsyncOpenAI, OpenAIError
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
from yt_dlp import YoutubeDL

from app.core.config import Settings, settings
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


@dataclass(frozen=True)
class TranscriptFetchOptions:
    language: str = "en"
    use_whisper_fallback: bool = True


class TranscriptService:
    def __init__(self, config: Settings) -> None:
        self.config = config

    async def get_transcript(
        self,
        video_id: str,
        options: TranscriptFetchOptions,
    ) -> TranscriptResponse:
        try:
            return await asyncio.to_thread(
                self._fetch_youtube_transcript,
                video_id,
                options.language,
            )
        except (NoTranscriptFound, TranscriptsDisabled):
            if not options.use_whisper_fallback:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No YouTube transcript found for this video.",
                ) from None

            return await self._fetch_whisper_transcript(video_id=video_id, language=options.language)
        except CouldNotRetrieveTranscript as exc:
            # Covers RequestBlocked/IpBlocked and other retrieval failures.
            # YouTube routinely blocks datacenter IPs (EC2, Render, GCP) —
            # without this the error escaped as a bare 500, which also lacks
            # CORS headers, so browsers surfaced it as an opaque network error.
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "YouTube refused the transcript request from this server "
                    "(datacenter IPs are frequently blocked). Configure the "
                    "WEBSHARE_PROXY_USERNAME/WEBSHARE_PROXY_PASSWORD environment "
                    "variables to route transcript requests through a residential "
                    "proxy, then retry."
                ),
            ) from exc

    def _fetch_youtube_transcript(self, video_id: str, language: str) -> TranscriptResponse:
        # youtube-transcript-api v1.x: instantiate the API, use .list() instead of .list_transcripts()
        ytt = YouTubeTranscriptApi(proxy_config=self._build_youtube_proxy_config())
        transcript_list = ytt.list(video_id)

        try:
            transcript = transcript_list.find_transcript([language])
        except NoTranscriptFound:
            transcript = transcript_list.find_generated_transcript([language])

        fetched = transcript.fetch()
        segments = normalize_youtube_segments(fetched)

        if not segments:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript exists but did not contain usable segments.",
            )

        full_text = " ".join(
            str(get_segment_value(s, "text", "")).strip()
            for s in fetched
            if get_segment_value(s, "text", "")
        )

        return TranscriptResponse(
            video_id=video_id,
            language=getattr(transcript, "language_code", language),
            source="youtube_transcript_api",
            segment_count=len(segments),
            full_text=full_text,
            segments=segments,
        )

    async def _fetch_whisper_transcript(self, video_id: str, language: str) -> TranscriptResponse:
        if not self.config.openai_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "No YouTube transcript found and OPENAI_API_KEY is not configured "
                    "for Whisper fallback."
                ),
            )

        audio_path = await asyncio.to_thread(self._download_audio, video_id)
        client = AsyncOpenAI(api_key=self.config.openai_api_key)

        try:
            with audio_path.open("rb") as audio_file:
                transcription = await client.audio.transcriptions.create(
                    model=self.config.whisper_model,
                    file=audio_file,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                    language=language,
                )
        except OpenAIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Whisper transcription failed.",
            ) from exc

        segments = normalize_whisper_segments(transcription)
        full_text = get_transcription_text(transcription, segments)

        return TranscriptResponse(
            video_id=video_id,
            language=language,
            source="whisper",
            segment_count=len(segments),
            full_text=full_text,
            segments=segments,
        )

    def _download_audio(self, video_id: str) -> Path:
        output_dir = Path(self.config.audio_cache_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / f"{video_id}.%(ext)s")

        options: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "96",
                }
            ],
        }

        if self.config.ffmpeg_location:
            options["ffmpeg_location"] = self.config.ffmpeg_location

        try:
            with YoutubeDL(options) as downloader:
                downloader.download([YOUTUBE_WATCH_URL.format(video_id=video_id)])
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to download audio for Whisper fallback.",
            ) from exc

        audio_path = output_dir / f"{video_id}.mp3"
        if not audio_path.exists():
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Audio download completed but no audio file was produced.",
            )

        return audio_path

    def _build_youtube_proxy_config(self) -> GenericProxyConfig | WebshareProxyConfig | None:
        if self.config.webshare_proxy_url:
            proxy_url = self.config.webshare_proxy_url.strip()
            return GenericProxyConfig(http_url=proxy_url, https_url=proxy_url)

        if not self.config.webshare_proxy_username or not self.config.webshare_proxy_password:
            return None

        return WebshareProxyConfig(
            proxy_username=self.config.webshare_proxy_username,
            proxy_password=self.config.webshare_proxy_password,
            filter_ip_locations=self.config.webshare_proxy_location_list or None,
            retries_when_blocked=5,
        )


def normalize_youtube_segments(raw_segments: list[Any]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []

    for index, raw_segment in enumerate(raw_segments):
        text = str(get_segment_value(raw_segment, "text", "")).strip()
        start = float(get_segment_value(raw_segment, "start", 0.0))
        duration = float(get_segment_value(raw_segment, "duration", 0.0))

        if not text:
            continue

        segments.append(
            TranscriptSegment(
                index=len(segments),
                start_seconds=round(start, 3),
                end_seconds=round(start + duration, 3),
                duration_seconds=round(duration, 3),
                text=" ".join(text.split()),
            )
        )

    return segments


def normalize_whisper_segments(transcription: Any) -> list[TranscriptSegment]:
    raw_segments = get_transcription_segments(transcription)
    segments: list[TranscriptSegment] = []

    for raw_segment in raw_segments:
        text = str(get_segment_value(raw_segment, "text", "")).strip()
        start = float(get_segment_value(raw_segment, "start", 0.0))
        end = float(get_segment_value(raw_segment, "end", start))

        if not text:
            continue

        segments.append(
            TranscriptSegment(
                index=len(segments),
                start_seconds=round(start, 3),
                end_seconds=round(end, 3),
                duration_seconds=round(max(0.0, end - start), 3),
                text=" ".join(text.split()),
            )
        )

    return segments


def get_segment_value(segment: Any, key: str, default: Any) -> Any:
    if isinstance(segment, dict):
        return segment.get(key, default)

    return getattr(segment, key, default)


def get_transcription_segments(transcription: Any) -> list[Any]:
    if isinstance(transcription, dict):
        return transcription.get("segments", [])

    return getattr(transcription, "segments", []) or []


def get_transcription_text(transcription: Any, segments: list[TranscriptSegment]) -> str:
    if isinstance(transcription, dict):
        text = transcription.get("text")
    else:
        text = getattr(transcription, "text", None)

    if isinstance(text, str) and text.strip():
        return text.strip()

    return " ".join(segment.text for segment in segments).strip()


def get_transcript_service() -> TranscriptService:
    return TranscriptService(settings)
