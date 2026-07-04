const configuredApiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const API_BASE = configuredApiBase;
export const WS_BASE = API_BASE.replace(/^http/, "ws");

// Runtime fallback: when the bundle was built with a localhost API URL but the
// page is served from a public host, target that host instead — same-origin on
// HTTPS (the reverse proxy serves /api), direct backend port on plain HTTP.
function resolveApiBase() {
  if (typeof window === "undefined") return configuredApiBase;

  try {
    const configured = new URL(configuredApiBase);
    const isLocalConfiguredHost = configured.hostname === "localhost" || configured.hostname === "127.0.0.1";
    const isLocalBrowserHost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

    if (isLocalConfiguredHost && !isLocalBrowserHost) {
      if (window.location.protocol === "https:") {
        return window.location.origin;
      }
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
  } catch {
    return configuredApiBase;
  }

  return configuredApiBase;
}

export function getApiBase() {
  return resolveApiBase();
}

export function getWsBase() {
  return getApiBase().replace(/^http/, "ws");
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
  const res = await fetch(`${getApiBase()}/api/videos/${videoId}/ingest`, {
    method: "POST",
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Ingest failed" }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new Error(`${res.status}: ${detail}`);
  }

  return await res.json() as IngestResponse;
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
