export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

export function getApiBase() {
  return API_BASE;
}

export function getWsBase() {
  return WS_BASE;
}

export interface YouTubeVideo {
  video_id: string;
  title: string;
  description: string;
  channel_id: string;
  channel_title: string;
  published_at: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  youtube_url: string;
}

export interface YouTubeSearchResponse {
  query: string;
  count: number;
  videos: YouTubeVideo[];
}

export type VideoDurationFilter = "any" | "under_10" | "under_30" | "under_60" | "over_60";

export async function searchVideos(
  query: string,
  maxResults = 10,
  durationFilter: VideoDurationFilter = "any"
): Promise<YouTubeSearchResponse> {
  const url = new URL(`${getApiBase()}/api/search`);
  url.searchParams.set("q", query);
  url.searchParams.set("max_results", String(maxResults));
  url.searchParams.set("duration_filter", durationFilter);

  const res = await fetch(url.toString());

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Search failed" }));
    throw new Error(typeof error.detail === "string" ? error.detail : "Search failed");
  }

  return res.json() as Promise<YouTubeSearchResponse>;
}

// -- Analytics ----------------------------------------------------------------

export interface AnalyticsEventPayload {
  event_type: string;
  session_id?: string | null;
  user_id?: string | null;
  page?: string | null;
  duration_ms?: number | null;
  metadata_json?: Record<string, unknown>;
}

export interface MetricPoint {
  label: string;
  value: number;
}

export interface AnalyticsDashboard {
  generated_at: string;
  overview: {
    daily_active_users: number;
    weekly_active_users: number;
    questions_today: number;
    videos_processed_today: number;
    avg_session_time_ms: number;
    avg_processing_time_ms: number;
    voice_usage_rate: number;
    search_success_rate: number;
  };
  ai_metrics: Record<string, MetricPoint[] | number>;
  pipeline_metrics: Record<string, MetricPoint[] | number>;
  ux_metrics: Record<string, number>;
  business_metrics: Record<string, number | MetricPoint[]>;
  recent_events: Array<{
    event_type: string;
    timestamp: string;
    page?: string | null;
    duration_ms?: number | null;
    metadata_json: Record<string, unknown>;
  }>;
}

export async function captureAnalyticsEvent(payload: AnalyticsEventPayload): Promise<void> {
  await fetch(`${getApiBase()}/api/analytics/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

export async function getAnalyticsDashboard(): Promise<AnalyticsDashboard> {
  const res = await fetch(`${getApiBase()}/api/analytics/dashboard`, { cache: "no-store" });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Analytics dashboard failed" }));
    throw new Error(typeof error.detail === "string" ? error.detail : "Analytics dashboard failed");
  }

  return res.json() as Promise<AnalyticsDashboard>;
}

// -- Ingest --------------------------------------------------------------------

export interface IngestResponse {
  video_id: string;
  collection_name: string;
  chunk_count: number;
  embedding_model: string;
  stored_chunk_ids: string[];
}

export async function ingestVideo(videoId: string): Promise<IngestResponse> {
  console.log(`[AskTube API] POST /api/videos/${videoId}/ingest`);
  const res = await fetch(`${getApiBase()}/api/videos/${videoId}/ingest`, {
    method: "POST",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Ingest failed" }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    console.error(`[AskTube API] Ingest failed ${res.status}: ${detail}`);
    throw new Error(`${res.status}: ${detail}`);
  }

  const data = await res.json() as IngestResponse;
  console.log(`[AskTube API] Ingest OK - ${data.chunk_count} chunks`);
  return data;
}

// -- Chat ----------------------------------------------------------------------

export interface TimestampCitation {
  chunk_id: string;
  video_id: string;
  start_seconds: number;
  end_seconds: number;
  timestamp: string;
  text: string;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  citations: TimestampCitation[];
}

export async function chatWithVideo(
  message: string,
  videoId: string,
  sessionId?: string
): Promise<ChatResponse> {
  const res = await fetch(`${getApiBase()}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      video_id: videoId,
      session_id: sessionId ?? null,
      top_k: 5,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Chat failed" }));
    throw new Error(typeof error.detail === "string" ? error.detail : "Chat failed");
  }

  return res.json() as Promise<ChatResponse>;
}

export interface AgentChatResponse {
  session_id: string;
  answer: string;
  citations: TimestampCitation[];
  tool_steps_used: string[];
}

export async function agentChatWithVideo(
  message: string,
  videoId: string | null,
  sessionId?: string
): Promise<AgentChatResponse> {
  const res = await fetch(`${getApiBase()}/api/agent/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      video_id: videoId ?? null,
      session_id: sessionId ?? null,
    }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Agent chat failed" }));
    throw new Error(typeof error.detail === "string" ? error.detail : "Agent chat failed");
  }

  return res.json() as Promise<AgentChatResponse>;
}

// -- Whisper speech-to-text ----------------------------------------------------

export async function transcribeSpeech(audioBlob: Blob): Promise<string> {
  const form = new FormData();
  form.append("audio", audioBlob, "speech.webm");
  const res = await fetch(`${getApiBase()}/api/speech/transcribe`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Transcription failed" }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Transcription failed");
  }
  const data = await res.json() as { transcript: string };
  return data.transcript;
}

// -- Utils ---------------------------------------------------------------------

export function decodeHtml(text: string): string {
  if (typeof document === "undefined") return text;
  const el = document.createElement("textarea");
  el.innerHTML = text;
  return el.value;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "--:--";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}
