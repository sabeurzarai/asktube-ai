"use client";

const SESSION_KEY = "asktube.analytics.session_id";
const USER_KEY = "asktube.analytics.user_id";
const configuredApiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Kept separate from lib/api's resolver (tests stub "@/lib/api" wholesale),
// but the fallback rules must stay in sync with resolveApiBase there.
function resolveAnalyticsApiBase() {
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

interface AnalyticsEventPayload {
  event_type: string;
  session_id?: string | null;
  user_id?: string | null;
  page?: string | null;
  duration_ms?: number | null;
  metadata_json?: Record<string, unknown>;
}

function createId(prefix: string) {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

export function getAnalyticsSessionId() {
  if (typeof window === "undefined") return null;
  let value = window.sessionStorage.getItem(SESSION_KEY);
  if (!value) {
    value = createId("session");
    window.sessionStorage.setItem(SESSION_KEY, value);
  }
  return value;
}

export function getAnalyticsUserId() {
  if (typeof window === "undefined") return null;
  let value = window.localStorage.getItem(USER_KEY);
  if (!value) {
    value = createId("anon");
    window.localStorage.setItem(USER_KEY, value);
  }
  return value;
}

export function trackAnalyticsEvent(
  eventType: string,
  metadata: Record<string, unknown> = {},
  durationMs?: number
) {
  if (typeof window === "undefined" || typeof fetch === "undefined") return;
  const payload: AnalyticsEventPayload = {
    event_type: eventType,
    session_id: getAnalyticsSessionId(),
    user_id: getAnalyticsUserId(),
    page: window.location.pathname,
    duration_ms: durationMs ?? null,
    metadata_json: metadata,
  };
  void fetch(`${resolveAnalyticsApiBase()}/api/analytics/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => undefined);
}

export function markAnalyticsStart() {
  return performance.now();
}

export function elapsedAnalyticsMs(start: number) {
  return Math.max(0, performance.now() - start);
}
