import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// analytics.ts reads NEXT_PUBLIC_API_URL at module load — set it before importing
process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";

// Dynamic import so we can re-import after clearing storage between tests
async function loadAnalytics() {
  vi.resetModules();
  return import("@/lib/analytics");
}

describe("getAnalyticsSessionId", () => {
  beforeEach(() => sessionStorage.clear());

  it("creates a session ID on first call", async () => {
    const { getAnalyticsSessionId } = await loadAnalytics();
    const id = getAnalyticsSessionId();
    expect(id).toMatch(/^session_/);
  });

  it("returns the same ID on subsequent calls", async () => {
    const { getAnalyticsSessionId } = await loadAnalytics();
    expect(getAnalyticsSessionId()).toBe(getAnalyticsSessionId());
  });

  it("persists across module reloads (same sessionStorage)", async () => {
    const { getAnalyticsSessionId } = await loadAnalytics();
    const first = getAnalyticsSessionId();
    const { getAnalyticsSessionId: again } = await loadAnalytics();
    expect(again()).toBe(first);
  });
});

describe("getAnalyticsUserId", () => {
  beforeEach(() => localStorage.clear());

  it("creates a user ID on first call", async () => {
    const { getAnalyticsUserId } = await loadAnalytics();
    const id = getAnalyticsUserId();
    expect(id).toMatch(/^anon_/);
  });

  it("persists in localStorage across reloads", async () => {
    const { getAnalyticsUserId } = await loadAnalytics();
    const first = getAnalyticsUserId();
    const { getAnalyticsUserId: again } = await loadAnalytics();
    expect(again()).toBe(first);
  });
});

describe("trackAnalyticsEvent", () => {
  let fetchSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    fetchSpy = vi.fn().mockResolvedValue(new Response());
    vi.stubGlobal("fetch", fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fires a POST to /api/analytics/events", async () => {
    const { trackAnalyticsEvent } = await loadAnalytics();
    trackAnalyticsEvent("test_event", { key: "value" });
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/analytics/events");
    expect(init.method).toBe("POST");

    const body = JSON.parse(init.body as string);
    expect(body.event_type).toBe("test_event");
    expect(body.metadata_json).toEqual({ key: "value" });
    expect(body.session_id).toMatch(/^session_/);
    expect(body.user_id).toMatch(/^anon_/);
    expect(body.page).toBe("/");
  });

  it("includes duration_ms when provided", async () => {
    const { trackAnalyticsEvent } = await loadAnalytics();
    trackAnalyticsEvent("timed_event", {}, 123.4);
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());

    const body = JSON.parse((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.duration_ms).toBeCloseTo(123.4);
  });

  it("sets duration_ms to null when not provided", async () => {
    const { trackAnalyticsEvent } = await loadAnalytics();
    trackAnalyticsEvent("no_duration");
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());

    const body = JSON.parse((fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.duration_ms).toBeNull();
  });

  it("swallows fetch errors silently", async () => {
    fetchSpy.mockRejectedValue(new Error("network error"));
    const { trackAnalyticsEvent } = await loadAnalytics();
    expect(() => trackAnalyticsEvent("failing_event")).not.toThrow();
  });
});

describe("markAnalyticsStart / elapsedAnalyticsMs", () => {
  it("returns a positive elapsed time", async () => {
    const { markAnalyticsStart, elapsedAnalyticsMs } = await loadAnalytics();
    const start = markAnalyticsStart();
    await new Promise((r) => setTimeout(r, 10));
    expect(elapsedAnalyticsMs(start)).toBeGreaterThan(0);
  });

  it("never returns a negative value", async () => {
    const { markAnalyticsStart, elapsedAnalyticsMs } = await loadAnalytics();
    const futureStart = performance.now() + 10_000;
    expect(elapsedAnalyticsMs(futureStart)).toBe(0);
  });
});
