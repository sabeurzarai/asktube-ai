import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from openai import AsyncOpenAI, OpenAIError
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
from yt_dlp import YoutubeDL

from app.core.config import Settings, settings
from app.schemas.transcript import TranscriptResponse, TranscriptSegment


YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"

logger = logging.getLogger(__name__)

# Blocks are per-attempt with a rotating proxy, so a few retries convert a
# measured ~83% success rate into near-certainty. Only applied when a proxy is
# configured - see _fetch_with_block_retries.
_BLOCK_RETRY_ATTEMPTS = 3


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
            return await self._fetch_with_block_retries(video_id, options.language)
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
                detail=self._blocked_detail(),
            ) from exc

    async def _fetch_with_block_retries(self, video_id: str, language: str) -> TranscriptResponse:
        """Fetch the transcript, retrying a block only when a retry can differ.

        A rotating residential proxy draws a NEW exit IP per request, so a block
        is a property of one attempt rather than of the request: measured live on
        2026-08-07, 5 of 6 identical ingests succeeded while the sixth hit a
        flagged IP. Retrying turns that into near-certainty and costs nothing
        when the first attempt works.

        Without a proxy every attempt leaves from the same address, so a retry is
        a guaranteed-identical failure paid for in latency - hence the guard.
        Only block errors are retried; a missing caption track or a disabled
        transcript is not going to change between attempts.
        """
        attempts = _BLOCK_RETRY_ATTEMPTS if self._build_youtube_proxy_config() else 1

        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(
                    self._fetch_youtube_transcript, video_id, language
                )
            except (RequestBlocked, IpBlocked):
                if attempt == attempts:
                    raise
                logger.warning(
                    "Transcript request for %s was blocked on attempt %d of %d; "
                    "retrying to draw a different proxy exit IP.",
                    video_id,
                    attempt,
                    attempts,
                )

        raise AssertionError("unreachable: the loop either returns or raises")

    def _blocked_detail(self) -> str:
        """Explain the block without asserting a cause that was never checked.

        The two situations produce the SAME exception and need opposite advice.
        Until 2026-08-07 this message always said "configure a proxy" - so when
        a configured proxy's own exit IP got blocked, it told the operator to do
        something already done, and to retry, which could not help. The message
        has to know which case it is in.
        """
        if self._build_youtube_proxy_config() is None:
            return (
                "YouTube refused the transcript request from this server "
                "(datacenter IPs are frequently blocked), and no residential proxy "
                "is configured. Set WEBSHARE_PROXY_URL (or the "
                "WEBSHARE_PROXY_USERNAME/WEBSHARE_PROXY_PASSWORD pair) to route "
                "transcript requests through one, then retry."
            )

        return (
            "YouTube refused the transcript request even through the configured "
            f"residential proxy, on all {_BLOCK_RETRY_ATTEMPTS} attempts - so this is not a "
            "configuration problem. If the proxy username rotates (a '-rotate' "
            "suffix rather than a pinned '-DE-1'), each attempt already used a "
            "different exit IP, so the pool is broadly flagged: switch pool or wait, "
            "as these blocks are usually temporary. If it does NOT rotate, switch it "
            "to '-rotate' in WEBSHARE_PROXY_URL - one pinned IP is one ban away from "
            "an outage. Videos already ingested are unaffected: they are served from "
            "the database and never touch YouTube."
        )

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
