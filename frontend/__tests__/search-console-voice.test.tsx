import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { SearchConsole } from "@/components/landing/search-console";

// -- Static mocks -------------------------------------------------------------

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
  transcribeSpeech: vi.fn().mockResolvedValue("whisper transcript"),
}));

// -- SpeechRecognition mock ---------------------------------------------------

interface MockResultEvent {
  resultIndex: number;
  results: {
    length: number;
    [i: number]: { isFinal: boolean; 0: { transcript: string } };
  };
}

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

// -- MediaRecorder mock -------------------------------------------------------

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

// -- Suite --------------------------------------------------------------------

describe("SearchConsole – voice input", () => {
  let user: ReturnType<typeof userEvent.setup>;
  const onSearch = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) });
    onSearch.mockClear();
    mockRecognition = null;
    mockMediaRecorder = null;

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
    it("renders in the search console", () => {
      render(<SearchConsole onSearch={onSearch} />);
      expect(
        screen.getByRole("button", { name: /start voice search/i })
      ).toBeInTheDocument();
    });

    it("is not disabled by default", () => {
      render(<SearchConsole onSearch={onSearch} />);
      expect(
        screen.getByRole("button", { name: /start voice search/i })
      ).not.toBeDisabled();
    });
  });

  // --------------------------------------------------------------------------
  describe("Web Speech API", () => {
    it("calls recognition.start() when mic button is clicked", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      expect(mockRecognition!.start).toHaveBeenCalledOnce();
    });

    it('shows "AI listening" feedback strip when recognition starts', async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => mockRecognition!.fireStart());
      expect(screen.getByText(/ai listening/i)).toBeInTheDocument();
    });

    it("shows interim transcript inside the listening strip", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("machine learning basics", false);
      });
      expect(screen.getByText("machine learning basics")).toBeInTheDocument();
    });

    it("puts final transcript into the search input", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => {
        mockRecognition!.fireStart();
        mockRecognition!.fireResult("deep learning tutorial", true);
      });
      expect(
        screen.getByRole("textbox", { name: /search youtube videos/i })
      ).toHaveValue("deep learning tutorial");
    });

    it("calls recognition.stop() when mic clicked while listening", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => mockRecognition!.fireStart());
      await user.click(
        screen.getByRole("button", { name: /stop voice search/i })
      );
      expect(mockRecognition!.stop).toHaveBeenCalledOnce();
    });

    it("shows whisper fallback message on network error", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => mockRecognition!.fireError("network"));
      expect(
        screen.getByText(/speech service unavailable/i)
      ).toBeInTheDocument();
    });

    it("shows permission blocked error for not-allowed", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      act(() => mockRecognition!.fireError("not-allowed"));
      expect(
        screen.getByText(/microphone permission is blocked/i)
      ).toBeInTheDocument();
    });

    it("shows no-speech error message", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
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
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() =>
        expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
          audio: true,
        })
      );
    });

    it("shows recording timer while Whisper is active", async () => {
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() =>
        expect(screen.getByText(/recording 0s/i)).toBeInTheDocument()
      );
    });

    it("calls transcribeSpeech after stopping Whisper recording", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording and transcribe/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() => expect(transcribeSpeech).toHaveBeenCalled());
    });

    it("places Whisper transcript in the search input", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      vi.mocked(transcribeSpeech).mockResolvedValue("pytorch for beginners");

      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording and transcribe/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() =>
        expect(
          screen.getByRole("textbox", { name: /search youtube videos/i })
        ).toHaveValue("pytorch for beginners")
      );
    });

    it("shows transcription error when Whisper API fails", async () => {
      const { transcribeSpeech } = await import("@/lib/api");
      vi.mocked(transcribeSpeech).mockRejectedValue(new Error("fail"));

      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() => expect(mockMediaRecorder).not.toBeNull());

      act(() =>
        mockMediaRecorder!.ondataavailable?.({
          data: new Blob(["audio"], { type: "audio/webm" }),
        })
      );

      await user.click(
        screen.getByRole("button", { name: /stop recording and transcribe/i })
      );
      vi.advanceTimersByTime(1500);

      await waitFor(() =>
        expect(screen.getByText(/transcription failed/i)).toBeInTheDocument()
      );
    });

    it("shows microphone access denied when getUserMedia rejects", async () => {
      Object.defineProperty(navigator, "mediaDevices", {
        value: {
          getUserMedia: vi
            .fn()
            .mockRejectedValue(new Error("Permission denied")),
        },
        writable: true,
        configurable: true,
      });

      render(<SearchConsole onSearch={onSearch} />);
      await user.click(
        screen.getByRole("button", { name: /start voice search/i })
      );
      await waitFor(() =>
        expect(
          screen.getByText(/microphone access denied/i)
        ).toBeInTheDocument()
      );
    });
  });
});
