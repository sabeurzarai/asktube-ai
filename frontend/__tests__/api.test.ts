import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  searchVideos,
  ingestVideo,
  chatWithVideo,
  agentChatWithVideo,
  transcribeSpeech,
  decodeHtml,
  formatDuration,
  API_BASE,
  type YouTubeSearchResponse,
  type IngestResponse,
  type ChatResponse,
  type AgentChatResponse,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// fetch mock helpers
// ---------------------------------------------------------------------------

function mockFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

function mockFetchError(body: unknown, status: number) {
  return vi.fn().mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve(body),
  });
}

function mockFetchNetworkFailure() {
  return vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
}

beforeEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// searchVideos
// ---------------------------------------------------------------------------

describe("searchVideos", () => {
  const successPayload: YouTubeSearchResponse = {
    query: "python tutorial",
    count: 1,
    videos: [
      {
        video_id: "abc123",
        title: "Learn Python",
        description: "A full course",
        channel_id: "ch1",
        channel_title: "Coding Channel",
        published_at: "2024-01-01T00:00:00Z",
        thumbnail_url: "https://img.youtube.com/vi/abc123/hqdefault.jpg",
        duration_seconds: 3600,
        youtube_url: "https://www.youtube.com/watch?v=abc123",
      },
    ],
  };

  it("calls the correct URL with default params", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await searchVideos("python tutorial");

    const [calledUrl] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    const url = new URL(calledUrl);
    expect(url.pathname).toBe("/api/search");
    expect(url.searchParams.get("q")).toBe("python tutorial");
    expect(url.searchParams.get("max_results")).toBe("10");
    expect(url.searchParams.get("duration_filter")).toBe("any");
  });

  it("forwards custom maxResults and durationFilter", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await searchVideos("ml basics", 5, "under_30");

    const [calledUrl] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    const url = new URL(calledUrl);
    expect(url.searchParams.get("max_results")).toBe("5");
    expect(url.searchParams.get("duration_filter")).toBe("under_30");
  });

  it("returns the parsed response on success", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    const result = await searchVideos("python tutorial");
    expect(result).toEqual(successPayload);
  });

  it("throws with the API detail string on non-ok response", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: "YOUTUBE_API_KEY is not configured." }, 503));

    await expect(searchVideos("anything")).rejects.toThrow("YOUTUBE_API_KEY is not configured.");
  });

  it("throws generic message when error body is not a string", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: ["bad", "array"] }, 400));

    await expect(searchVideos("anything")).rejects.toThrow("Search failed");
  });

  it("throws generic message when error JSON parse fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new SyntaxError("bad json")),
    }));

    await expect(searchVideos("anything")).rejects.toThrow("Search failed");
  });
});

// ---------------------------------------------------------------------------
// ingestVideo
// ---------------------------------------------------------------------------

describe("ingestVideo", () => {
  const successPayload: IngestResponse = {
    video_id: "abc123",
    collection_name: "abc123_transcript",
    chunk_count: 42,
    embedding_model: "text-embedding-3-small",
    stored_chunk_ids: ["abc123:0:a", "abc123:1:b"],
  };

  it("sends POST to the correct URL", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await ingestVideo("abc123");

    const [calledUrl, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(`${API_BASE}/api/videos/abc123/ingest`);
    expect(options.method).toBe("POST");
  });

  it("returns parsed IngestResponse on success", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    const result = await ingestVideo("abc123");
    expect(result.chunk_count).toBe(42);
    expect(result.stored_chunk_ids).toHaveLength(2);
  });

  it("throws with status and detail on failure", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: "Transcript not found" }, 404));

    await expect(ingestVideo("missing")).rejects.toThrow("404: Transcript not found");
  });

  it("throws with stringified detail when detail is not a string", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: { code: "ERR" } }, 422));

    await expect(ingestVideo("bad")).rejects.toThrow("422:");
  });
});

// ---------------------------------------------------------------------------
// chatWithVideo
// ---------------------------------------------------------------------------

describe("chatWithVideo", () => {
  const successPayload: ChatResponse = {
    session_id: "sess-1",
    answer: "RAG is Retrieval-Augmented Generation.",
    citations: [],
  };

  it("sends POST with correct JSON body", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await chatWithVideo("What is RAG?", "abc123", "sess-1");

    const [calledUrl, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(`${API_BASE}/api/chat`);
    expect(options.method).toBe("POST");
    const body = JSON.parse(options.body as string);
    expect(body.message).toBe("What is RAG?");
    expect(body.video_id).toBe("abc123");
    expect(body.session_id).toBe("sess-1");
    expect(body.top_k).toBe(5);
  });

  it("sends null session_id when not provided", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await chatWithVideo("hello", "abc123");

    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.session_id).toBeNull();
  });

  it("returns ChatResponse on success", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    const result = await chatWithVideo("Q", "v1");
    expect(result.session_id).toBe("sess-1");
    expect(result.answer).toContain("RAG");
  });

  it("throws on non-ok response", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: "Video not ingested" }, 400));

    await expect(chatWithVideo("Q", "v1")).rejects.toThrow("Video not ingested");
  });
});

// ---------------------------------------------------------------------------
// agentChatWithVideo
// ---------------------------------------------------------------------------

describe("agentChatWithVideo", () => {
  const successPayload: AgentChatResponse = {
    session_id: "sess-2",
    answer: "Here is the answer.",
    citations: [],
    tool_steps_used: ["retrieve_context", "answer_question"],
  };

  it("sends POST to /api/agent/chat", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await agentChatWithVideo("Summarise", "abc123");

    const [calledUrl] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(calledUrl).toBe(`${API_BASE}/api/agent/chat`);
  });

  it("sends null when videoId is null", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    await agentChatWithVideo("General question", null);

    const [, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(options.body as string);
    expect(body.video_id).toBeNull();
  });

  it("returns AgentChatResponse including tool_steps_used", async () => {
    vi.stubGlobal("fetch", mockFetch(successPayload));

    const result = await agentChatWithVideo("Q", "v1");
    expect(result.tool_steps_used).toEqual(["retrieve_context", "answer_question"]);
  });

  it("throws on agent error", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: "Agent failed" }, 500));

    await expect(agentChatWithVideo("Q", "v1")).rejects.toThrow("Agent failed");
  });
});

// ---------------------------------------------------------------------------
// transcribeSpeech
// ---------------------------------------------------------------------------

describe("transcribeSpeech", () => {
  it("sends POST with FormData containing the audio blob", async () => {
    vi.stubGlobal("fetch", mockFetch({ transcript: "hello world" }));

    const blob = new Blob(["audio-data"], { type: "audio/webm" });
    await transcribeSpeech(blob);

    const [calledUrl, options] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(calledUrl).toBe(`${API_BASE}/api/speech/transcribe`);
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    const form = options.body as FormData;
    const audioFile = form.get("audio") as File;
    expect(audioFile).toBeTruthy();
    expect(audioFile.name).toBe("speech.webm");
  });

  it("returns the transcript string on success", async () => {
    vi.stubGlobal("fetch", mockFetch({ transcript: "machine learning basics" }));

    const blob = new Blob(["audio"], { type: "audio/webm" });
    const result = await transcribeSpeech(blob);
    expect(result).toBe("machine learning basics");
  });

  it("throws on transcription failure", async () => {
    vi.stubGlobal("fetch", mockFetchError({ detail: "Transcription failed" }, 500));

    const blob = new Blob(["audio"], { type: "audio/webm" });
    await expect(transcribeSpeech(blob)).rejects.toThrow("Transcription failed");
  });

  it("throws generic message when error JSON is unparseable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new SyntaxError("bad")),
    }));

    const blob = new Blob(["audio"], { type: "audio/webm" });
    await expect(transcribeSpeech(blob)).rejects.toThrow("Transcription failed");
  });
});

// ---------------------------------------------------------------------------
// decodeHtml
// ---------------------------------------------------------------------------

describe("decodeHtml", () => {
  it("decodes common HTML entities", () => {
    expect(decodeHtml("Hello &amp; World")).toBe("Hello & World");
    expect(decodeHtml("&lt;div&gt;")).toBe("<div>");
    expect(decodeHtml("It&#39;s fine")).toBe("It's fine");
    expect(decodeHtml("&quot;quoted&quot;")).toBe('"quoted"');
  });

  it("returns plain text unchanged", () => {
    expect(decodeHtml("No entities here")).toBe("No entities here");
  });

  it("handles empty string", () => {
    expect(decodeHtml("")).toBe("");
  });
});

// ---------------------------------------------------------------------------
// formatDuration
// ---------------------------------------------------------------------------

describe("formatDuration", () => {
  it("formats seconds-only as M:SS", () => {
    expect(formatDuration(45)).toBe("0:45");
  });

  it("formats minutes and seconds as M:SS", () => {
    expect(formatDuration(125)).toBe("2:05");
  });

  it("formats hours as H:MM:SS", () => {
    expect(formatDuration(3723)).toBe("1:02:03");
  });

  it("zero-pads seconds correctly", () => {
    expect(formatDuration(60)).toBe("1:00");
    expect(formatDuration(3600)).toBe("1:00:00");
  });

  it("returns '--:--' for null", () => {
    expect(formatDuration(null)).toBe("--:--");
  });

  it("returns '--:--' for undefined", () => {
    expect(formatDuration(undefined)).toBe("--:--");
  });

  it("returns '--:--' for zero", () => {
    expect(formatDuration(0)).toBe("--:--");
  });
});
