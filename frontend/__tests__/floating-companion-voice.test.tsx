import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { FloatingCompanion } from "@/components/floating-companion";
import type { JourneyStep } from "@/components/landing/cinematic-hero";

// -- Static mocks (hoisted) ---------------------------------------------------

vi.mock("@react-three/fiber", () => ({
  Canvas: ({ children: _c }: { children: React.ReactNode }) => (
    <div data-testid="r3f-canvas" />
  ),
  useFrame: vi.fn(),
}));

vi.mock("@react-three/drei", () => ({
  Environment: () => null,
  PerspectiveCamera: () => null,
}));

// Skip AnimatePresence exit-animation delay so state changes are instant
vi.mock("framer-motion", async (importOriginal) => {
  const mod = await importOriginal<typeof import("framer-motion")>();
  return {
    ...mod,
    AnimatePresence: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
  };
});

vi.mock("@/lib/api", () => ({
  chatWithVideo: vi.fn().mockResolvedValue({
    answer: "Test answer",
    citations: [],
    session_id: "session-1",
  }),
  transcribeSpeech: vi.fn().mockResolvedValue("whisper result"),
}));

// -- SpeechRecognition mock (class so `new` works) ----------------------------

interface MockResultEvent {
  resultIndex: number;
  results: {
    length: number;
    [i: number]: { isFinal: boolean; 0: { transcript: string } };
  };
}

// Module-level reference updated by each construction
let mockRecognition: InstanceType<typeof MockSpeechRecognition> | null = null;

class MockSpeechRecognition {
  continuous = false;
  interimResults = false;
  lang = "";
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onresult: ((e: MockResultEvent) => void) | null = null;
  start = vi.fn();
  stop = vi.fn();

  constructor() {
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    mockRecognition = this;
  }

  fireStart()  { this.onstart?.(); }
  fireEnd()    { this.onend?.(); }
  fireError(error: string) { this.onerror?.({ error }); }
  fireResult(transcript: string, isFinal: boolean) {
    this.onresult?.({
      resultIndex: 0,
      results: { length: 1, 0: { isFinal, 0: { transcript } } },
    });
  }
}

// -- MediaRecorder mock (class so `new` works) --------------------------------

let mockMediaRecorder: InstanceType<typeof MockMediaRecorder> | null = null;

class MockMediaRecorder {
  static isTypeSupported = (_type: string) => false;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn(() => { this.onstop?.(); });

  constructor(_stream: unknown, _opts?: unknown) {
    mockMediaRecorder = this;
  }
}

// -- Test data ----------------------------------------------------------------

const mockVideo = {
  video_id: "vid-123",
  title: "Test Video",
  description: "",
  channel_id: "ch-1",
  channel_title: "Test Channel",
  published_at: "2024-01-01",
  thumbnail_url: null,
  duration_seconds: 300,
  youtube_url: "https://youtube.com/watch?v=vid-123",
};

function renderCompanion(
  overrides: Partial<{
    isReady: boolean;
    selectedVideo: typeof mockVideo | null;
    journeyStep: JourneyStep;
  }> = {}
) {
  return render(
    <FloatingCompanion
      isReady={true}
      selectedVideo={mockVideo}
      journeyStep="ready"
      {...overrides}
    />
  );
}

async function openChat(user: ReturnType<typeof userEvent.setup>) {
  const btn = screen.getByRole("button", { name: /your video is ready/i });
  await user.click(btn);
}

// -- Suite --------------------------------------------------------------------

describe("FloatingCompanion – voice input", () => {
  let user: ReturnType<typeof userEvent.setup>;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });

    mockRecognition = null;
    mockMediaRecorder = null;

    // Assign the class itself (not a vi.fn wrapper) so `new` works
    Object.defineProperty(window, "SpeechRecognition", {
      value: MockSpeechRecognition,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(window, "webkitSpeechRecognition", {
      value: undefined,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(window, "MediaRecorder", {
      value: MockMediaRecorder,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // --------------------------------------------------------------------------
  describe("mic button", () => {
    it("appears in the chat panel when isReady is true", async () => {
      renderCompanion();
      await openChat(user);
      expect(
        screen.getByRole("button", { name: /voice input/i })
      ).toBeInTheDocument();
    });

    it("is disabled when isReady is false", async () => {
      renderCompanion({ isReady: false });
      await openChat(user);
      expect(
        screen.getByRole("button", { name: /voice input/i })
      ).toBeDisabled();
    });
  });

  // --------------------------------------------------------------------------
  describe("Web Speech API", () => {
    it("calls recognition.start() when mic button is clicked", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      expect(mockRecognition!.start).toHaveBeenCalledOnce();
    });

    it('shows "Listening..." feedback strip after recognition starts', async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireStart());
      expect(screen.getByText(/listening/i)).toBeInTheDocument();
    });

    it("shows interim transcript in the message input", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("explain machine learning", false);
      });
      expect(screen.getByPlaceholderText(/ask anything/i)).toHaveValue(
        "explain machine learning"
      );
    });

    it("commits final transcript to message input", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("what is gradient descent", true);
      });
      expect(screen.getByPlaceholderText(/ask anything/i)).toHaveValue(
        "what is gradient descent"
      );
    });

    it("calls recognition.stop() when mic clicked while listening", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireStart());
      await user.click(
        screen.getByRole("button", { name: /stop voice input/i })
      );
      expect(mockRecognition!.stop).toHaveBeenCalledOnce();
    });

    it("shows network error and switches to Whisper fallback message", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireError("network"));
      expect(
        screen.getByText(/speech service unavailable/i)
      ).toBeInTheDocument();
    });

    it("shows microphone permission error", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireError("not-allowed"));
      expect(
        screen.getByText(/microphone permission is blocked/i)
      ).toBeInTheDocument();
    });

    it("shows no-speech error message", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireError("no-speech"));
      expect(screen.getByText(/no speech detected/i)).toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  describe("Whisper fallback", () => {
    beforeEach(() => {
      Object.defineProperty(window, "SpeechRecognition", {
        value: undefined,
        writable: true,
        configurable: true,
      });
    });

    it("requests microphone when SpeechRecognition is unavailable", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() =>
        expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
          audio: true,
        })
      );
    });

    it("shows recording timer while Whisper is recording", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() =>
        expect(screen.getByText(/recording 0s/i)).toBeInTheDocument()
      );
    });

    it("calls transcribeSpeech after stopping recording", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() => expect(transcribeSpeech).toHaveBeenCalled());
    });

    it("places Whisper transcript in the message input", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      vi.mocked(transcribeSpeech).mockResolvedValue(
        "how do neural networks work"
      );

      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() =>
        expect(screen.getByPlaceholderText(/ask anything/i)).toHaveValue(
          "how do neural networks work"
        )
      );
    });

    it("shows error message when transcription fails", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      vi.mocked(transcribeSpeech).mockRejectedValue(new Error("API error"));

      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() =>
        expect(screen.getByText(/transcription failed/i)).toBeInTheDocument()
      );
    });

    it("shows microphone access denied when getUserMedia is rejected", async () => {
      Object.defineProperty(navigator, "mediaDevices", {
        value: {
          getUserMedia: vi
            .fn()
            .mockRejectedValue(new Error("Permission denied")),
        },
        writable: true,
        configurable: true,
      });

      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      await waitFor(() =>
        expect(
          screen.getByText(/microphone access denied/i)
        ).toBeInTheDocument()
      );
    });
  });

  // --------------------------------------------------------------------------
  describe("voice active visual feedback", () => {
    it("shows pulsing red ring around robot when chat is open and listening", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireStart());
      expect(
        document.querySelector(".border-red-400\\/70")
      ).toBeInTheDocument();
    });

    it("removes pulsing ring after voice stops", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => mockRecognition!.fireStart());
      act(() => mockRecognition!.fireEnd());
      expect(
        document.querySelector(".border-red-400\\/70")
      ).not.toBeInTheDocument();
    });
  });

  // --------------------------------------------------------------------------
  describe("send integration", () => {
    it("stops voice recognition before submitting a message", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("summarize the video", true);
      });
      await user.click(screen.getByRole("button", { name: /^send$/i }));
      expect(mockRecognition!.stop).toHaveBeenCalled();
    });

    it("clears interim text after message is sent", async () => {
      renderCompanion();
      await openChat(user);
      await user.click(screen.getByRole("button", { name: /voice input/i }));
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("key insights", true);
      });
      await user.click(screen.getByRole("button", { name: /^send$/i }));
      await waitFor(() =>
        expect(
          screen.getByPlaceholderText(/ask anything/i)
        ).toHaveValue("")
      );
    });
  });
});
