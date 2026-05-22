"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowDown, Mic, Search, Sparkles, Volume2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  CinematicProgress,
  EmptyState,
  ErrorState
} from "@/components/ui/feedback-states";
import { Input } from "@/components/ui/input";
import { transcribeSpeech } from "@/lib/api";
import { smoothEase, staggerContainer, subtleItemReveal } from "@/lib/motion";

type SpeechRecognitionResultLike = {
  isFinal: boolean;
  0: {
    transcript: string;
  };
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
};

type SpeechRecognitionErrorEventLike = {
  error: string;
};

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  start: () => void;
  stop: () => void;
};

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

const waveformBars = [18, 28, 14, 34, 22, 38, 16, 30, 20];

interface SearchConsoleProps {
  onSearch: (query: string) => Promise<void>;
  externalSearchState?: "idle" | "loading" | "ready" | "error" | "empty";
}

export function SearchConsole({ onSearch, externalSearchState }: SearchConsoleProps) {
  const prefersReducedMotion = useReducedMotion();
  const [query, setQuery] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [isSpeechSupported, setIsSpeechSupported] = useState(true);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "empty" | "error" | "ready">(
    "idle"
  );
  const [searchProgress, setSearchProgress] = useState(0);

  // Sync external state (from parent after API call resolves)
  const effectiveSearchState = externalSearchState ?? searchState;
  const [isWhisperRecording, setIsWhisperRecording] = useState(false);
  const [isWhisperProcessing, setIsWhisperProcessing] = useState(false);
  const [useWhisperFallback, setUseWhisperFallback] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const recordingTimerRef = useRef<number | null>(null);
  const recordingStartRef = useRef(0);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const committedTranscriptRef = useRef("");
  const shouldRestartRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    const SpeechRecognition =
      (window as SpeechWindow).SpeechRecognition ??
      (window as SpeechWindow).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setIsSpeechSupported(false);
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;   // one utterance at a time - more reliable
    recognition.interimResults = true;
    // Use the browser's configured language so speech is recognised regardless
    // of whether the user speaks English or another language.
    recognition.lang = navigator.language || "en-US";

    const startedAtRef = { current: 0 };

    recognition.onstart = () => {
      startedAtRef.current = Date.now();
      setIsListening(true);
      setVoiceError("");
    };

    recognition.onend = () => {
      setInterimTranscript("");
      // Auto-restart only if the user hasn't manually clicked stop AND the
      // session lasted long enough to suggest it was a real silence timeout
      // (not an immediate error restart loop).
      const lived = Date.now() - startedAtRef.current;
      if (shouldRestartRef.current && lived > 300) {
        window.setTimeout(() => {
          if (shouldRestartRef.current) {
            try {
              recognition.start();
            } catch {
              setIsListening(false);
              shouldRestartRef.current = false;
              setVoiceError("Voice search stopped. Click the mic to try again.");
            }
          }
        }, 300);
        return;
      }
      if (shouldRestartRef.current && lived <= 300) {
        // Restarted too quickly - likely a recognition error loop; stop gracefully
        setIsListening(false);
        shouldRestartRef.current = false;
        setVoiceError("Could not connect to speech service. Try again.");
        return;
      }
      setIsListening(false);
    };

    recognition.onerror = (event) => {
      setIsListening(false);
      setInterimTranscript("");
      shouldRestartRef.current = false;
      // Network error = Google speech servers unreachable.
      // getUserMedia cannot be called here (outside user gesture context) so
      // we just flip the flag and show a prompt - the next mic click will
      // call startWhisperRecording() from inside the button's onClick handler.
      if (event.error === "network") {
        setUseWhisperFallback(true);
        setVoiceError("Speech service unavailable. Tap the mic to record with Whisper instead.");
        return;
      }
      const msg: Record<string, string> = {
        "not-allowed": "Microphone permission is blocked.",
        "no-speech": "No speech detected. Try speaking louder.",
        "audio-capture": "No microphone found.",
        "service-not-allowed": "Speech service not allowed on this page.",
      };
      setVoiceError(msg[event.error] ?? "Voice search stopped. Try again.");
    };

    recognition.onresult = (event) => {
      let interim = "";
      let finalText = "";

      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        const transcript = result[0].transcript;

        if (result.isFinal) {
          finalText += transcript;
        } else {
          interim += transcript;
        }
      }

      if (finalText) {
        committedTranscriptRef.current = `${committedTranscriptRef.current} ${finalText}`
          .replace(/\s+/g, " ")
          .trim();
        setQuery(committedTranscriptRef.current);
      }

      setInterimTranscript(interim.trim());
    };

    recognitionRef.current = recognition;

    return () => {
      shouldRestartRef.current = false;
      recognition.onstart = null;
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      recognition.stop();
    };
  }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    runSearch();
  }

  // Pick the best supported MIME type for Whisper compatibility
  function getBestMimeType(): string {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/ogg",
      "audio/mp4",
    ];
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  }

  async function startWhisperRecording() {
    setVoiceError("");
    setRecordingSeconds(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getBestMimeType();
      const recorderOptions = mimeType ? { mimeType } : undefined;
      const recorder = new MediaRecorder(stream, recorderOptions);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (recordingTimerRef.current !== null) {
          window.clearInterval(recordingTimerRef.current);
          recordingTimerRef.current = null;
        }
        setIsWhisperRecording(false);
        setIsWhisperProcessing(true);
        try {
          const blob = new Blob(audioChunksRef.current, {
            type: mimeType || "audio/webm",
          });
          const transcript = await transcribeSpeech(blob);
          if (transcript) {
            committedTranscriptRef.current = `${committedTranscriptRef.current} ${transcript}`
              .replace(/\s+/g, " ")
              .trim();
            setQuery(committedTranscriptRef.current);
          } else {
            setVoiceError("Nothing detected. Speak clearly and try again.");
          }
        } catch {
          setVoiceError("Transcription failed. Try again.");
        } finally {
          setIsWhisperProcessing(false);
          setRecordingSeconds(0);
        }
      };

      // Collect data every 250ms so onstop always has chunks
      recorder.start(250);
      recordingStartRef.current = Date.now();
      mediaRecorderRef.current = recorder;
      setIsWhisperRecording(true);

      // Live recording timer
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds(Math.floor((Date.now() - recordingStartRef.current) / 1000));
      }, 500);
    } catch {
      setVoiceError("Microphone access denied.");
    }
  }

  function stopWhisperRecording() {
    const elapsed = Date.now() - recordingStartRef.current;
    if (elapsed < 1500) {
      // Too short - wait for minimum duration before stopping
      window.setTimeout(() => mediaRecorderRef.current?.stop(), 1500 - elapsed);
    } else {
      mediaRecorderRef.current?.stop();
    }
  }

  async function runSearch() {
    const normalizedQuery = liveTranscript.trim();

    if (!normalizedQuery) {
      setSearchState("empty");
      setSearchProgress(0);
      return;
    }

    setSearchState("loading");
    setSearchProgress(12);

    // Animate the progress bar while waiting for the API
    const t1 = window.setTimeout(() => setSearchProgress(44), 400);
    const t2 = window.setTimeout(() => setSearchProgress(76), 900);

    try {
      await onSearch(normalizedQuery);
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      setSearchProgress(100);
      setSearchState("ready");
    } catch {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      setSearchState("error");
    }
  }

  function toggleListening() {
    setVoiceError("");

    // Stop active Whisper recording and send to backend
    if (isWhisperRecording) {
      stopWhisperRecording();
      return;
    }

    // Start Whisper recording - either because the flag was set by a prior
    // network error, or because the browser doesn't support Web Speech at all.
    // This path is always triggered by a direct button click, so getUserMedia
    // will have the required user-gesture context.
    if (useWhisperFallback || !isSpeechSupported || !recognitionRef.current) {
      setUseWhisperFallback(false);
      startWhisperRecording();
      return;
    }

    if (isListening) {
      shouldRestartRef.current = false;
      recognitionRef.current.stop();
      return;
    }

    committedTranscriptRef.current = query;
    setInterimTranscript("");
    shouldRestartRef.current = true;

    try {
      recognitionRef.current.start();
    } catch {
      shouldRestartRef.current = false;
      setUseWhisperFallback(true);
      setVoiceError("Voice search unavailable. Tap the mic to record with Whisper instead.");
    }
  }

  const liveTranscript = [query, interimTranscript].filter(Boolean).join(" ");

  return (
    <motion.div
      initial={{ opacity: 1, y: 18, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ delay: 0.35, duration: 0.7, ease: smoothEase }}
      className="mx-auto mt-10 w-full max-w-[calc(100vw-2.5rem)] sm:max-w-3xl"
    >
      <form
        onSubmit={handleSubmit}
        className="relative overflow-hidden rounded-[1.75rem] border border-white/15 bg-white/[0.075] p-2 shadow-[0_26px_105px_rgba(0,0,0,.55),inset_0_1px_0_rgba(255,255,255,.08)] backdrop-blur-2xl"
      >
        <motion.div
          aria-hidden="true"
          animate={{
            opacity: isListening ? 1 : 0.7,
            backgroundPosition: isListening ? ["0% 50%", "100% 50%", "0% 50%"] : "0% 50%"
          }}
          transition={{ duration: 4, repeat: isListening ? Infinity : 0, ease: "easeInOut" }}
          className="pointer-events-none absolute inset-0 bg-[linear-gradient(110deg,transparent,rgba(255,255,255,.12),transparent)] bg-[length:220%_100%]"
        />
        {isListening ? (
          <motion.div
            aria-hidden="true"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_50%,rgba(236,72,153,.26),transparent_28%),radial-gradient(circle_at_82%_50%,rgba(34,211,238,.20),transparent_26%)]"
          />
        ) : null}
        <div className="relative flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center">
          <label className="sr-only" htmlFor="youtube-search">
            Search YouTube videos
          </label>
          <div className="relative flex-1">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute left-5 top-1/2 size-5 -translate-y-1/2 text-cyan-100"
            />
            <Input
              id="youtube-search"
              value={liveTranscript}
              onChange={(event) => {
                setQuery(event.target.value);
                committedTranscriptRef.current = event.target.value;
                setInterimTranscript("");
              }}
              autoComplete="off"
              spellCheck={false}
              aria-describedby="search-hint"
              className="h-14 border-transparent bg-black/35 pl-12 pr-5 text-[15px] shadow-none sm:text-base"
              placeholder="Try: explain AI agents for beginners"
            />
          </div>

          <div className="grid min-w-0 grid-cols-[3rem_1fr] gap-2 sm:flex">
            <Button
              type="button"
              variant={isListening || isWhisperRecording ? "red" : "ghost"}
              size="icon"
              aria-label={
                isWhisperRecording ? "Stop recording and transcribe"
                : isListening ? "Stop voice search"
                : isWhisperProcessing ? "Transcribing..."
                : "Start voice search"
              }
              onClick={toggleListening}
              disabled={isWhisperProcessing}
              className="relative shrink-0 overflow-visible"
            >
              {isWhisperProcessing ? (
                <span className="size-4 rounded-full border-2 border-cyan-300 border-t-transparent motion-safe:animate-spin" />
              ) : isListening || isWhisperRecording ? (
                <Volume2 aria-hidden="true" className="size-5" />
              ) : (
                <Mic aria-hidden="true" className="size-5" />
              )}
              {(isListening || isWhisperRecording) ? (
                <>
                  <span className="absolute inset-0 -z-10 rounded-full bg-red-500/30 motion-safe:animate-ping" />
                  <span className="absolute -inset-2 -z-20 rounded-full bg-cyan-300/15 blur-xl" />
                </>
              ) : null}
            </Button>
            <Button type="submit" variant="default" size="lg" className="min-w-0 flex-1 px-5 sm:flex-none sm:px-7">
              <Sparkles aria-hidden="true" className="size-4" />
              Find videos
            </Button>
          </div>
        </div>

        <AnimatePresence>
          {(isListening || isWhisperRecording || isWhisperProcessing || interimTranscript || voiceError) && (
            <motion.div
              initial={{ opacity: 0, y: -8, height: 0 }}
              animate={{ opacity: 1, y: 0, height: "auto" }}
              exit={{ opacity: 0, y: -8, height: 0 }}
              transition={{ duration: 0.25, ease: smoothEase }}
              className="relative overflow-hidden"
            >
              <div className="mt-3 rounded-[1.35rem] border border-white/10 bg-black/30 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,.06)] backdrop-blur-xl">
                {voiceError ? (
                  <p className="text-sm font-medium text-red-100">{voiceError}</p>
                ) : isWhisperProcessing ? (
                  <p className="text-sm font-medium text-cyan-100">Transcribing with Whisper...</p>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-100">
                        {isWhisperRecording
                          ? `Recording ${recordingSeconds}s - click mic to transcribe`
                          : "AI listening"}
                      </p>
                      <p className="mt-1 text-sm text-slate-300">
                        {isWhisperRecording
                          ? recordingSeconds < 2
                            ? "Speak now... hold for at least 2 seconds then click the mic."
                            : "Click the mic button to stop and transcribe."
                          : interimTranscript || "Ask for a topic, a video, or a question you want answered."}
                      </p>
                    </div>
                    <div
                      aria-hidden="true"
                      className="flex h-10 items-center gap-1.5 sm:justify-end"
                    >
                      {waveformBars.map((height, index) => (
                        <motion.span
                          key={`${height}-${index}`}
                          aria-hidden="true"
                          animate={prefersReducedMotion ? { height: 10, opacity: 0.5 } : {
                            height: isListening ? [10, height, 12] : 10,
                            opacity: isListening ? [0.45, 1, 0.55] : 0.35
                          }}
                          transition={{
                            duration: 0.85,
                            repeat: prefersReducedMotion ? 0 : Infinity,
                            ease: "easeInOut",
                            delay: index * 0.06
                          }}
                          className="w-1.5 rounded-full bg-gradient-to-t from-pink-400 to-cyan-200 shadow-[0_0_18px_rgba(34,211,238,.45)]"
                          style={{ height: 10 }}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </form>

      <p id="search-hint" className="sr-only">
        Search for any YouTube topic. Press Enter or the Find videos button to search.
        Use the microphone button for voice input.
      </p>

      {/* Live region announces search state changes */}
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {effectiveSearchState === "loading" && "Searching for videos..."}
        {effectiveSearchState === "ready" && "Results ready. Review videos below."}
        {effectiveSearchState === "empty" && "Please enter a search topic."}
        {effectiveSearchState === "error" && "Search failed. Please try again."}
      </div>

      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="visible"
        className="mx-auto mt-4 flex max-w-[22rem] flex-wrap justify-center gap-2 text-xs text-slate-400 sm:max-w-none"
      >
        {["Start broad", "pick a video", "AI prepares evidence", "ask follow-ups"].map(
          (item) => (
            <motion.span
              key={item}
              variants={subtleItemReveal}
              whileHover={{ y: -2, scale: 1.03 }}
              transition={{ type: "spring", stiffness: 320, damping: 24 }}
              className="glass-chip hover:border-cyan-200/25 hover:text-slate-100"
            >
              {item}
            </motion.span>
          )
        )}
      </motion.div>

      <AnimatePresence mode="wait">
        {effectiveSearchState === "loading" ? (
          <motion.div
            key="search-loading"
            initial={{ opacity: 0, y: 10, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.985 }}
            transition={{ duration: 0.28, ease: smoothEase }}
            className="mt-4 rounded-[1.5rem] border border-white/10 bg-white/[0.045] p-4 text-left shadow-cinema-card backdrop-blur-2xl"
          >
            <CinematicProgress
              value={searchProgress}
              label="Finding the best learning matches"
              remaining="about 4s left"
            />
          </motion.div>
        ) : null}

        {effectiveSearchState === "empty" ? (
          <motion.div
            key="search-empty"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.24, ease: smoothEase }}
            className="mt-4"
          >
            <EmptyState
              title="What do you want to learn today?"
              description="Type a topic, paste a video idea, or use the microphone. A simple question works too."
              action={
                <Button type="button" variant="ghost" onClick={() => { setSearchState("idle"); setSearchProgress(0); }}>
                  Start searching
                </Button>
              }
            />
          </motion.div>
        ) : null}

        {effectiveSearchState === "ready" ? (
          <motion.div
            key="search-ready"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.24, ease: smoothEase }}
            className="mt-4 rounded-[1.5rem] border border-emerald-300/20 bg-emerald-300/[0.075] p-4 text-left shadow-[0_0_38px_rgba(16,185,129,.10)] backdrop-blur-xl"
          >
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.22em] text-emerald-100">
                  Matches ready
                </p>
                <p className="mt-1 text-sm leading-6 text-slate-200">
                  Pick a video below. AskTube will prepare the transcript before you chat.
                </p>
              </div>
              <Button type="button" variant="ghost" asChild>
                <a href="#trending">
                  Review videos
                  <ArrowDown aria-hidden="true" className="size-4" />
                </a>
              </Button>
            </div>
          </motion.div>
        ) : null}

        {effectiveSearchState === "error" ? (
          <motion.div
            key="search-error"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.24, ease: smoothEase }}
            className="mt-4"
          >
            <ErrorState
              title="Search paused before results loaded"
              description="Your query is safe here. Retry when the connection settles, or try a shorter topic."
              onRetry={runSearch}
              retryLabel="Retry search"
            />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.div>
  );
}
