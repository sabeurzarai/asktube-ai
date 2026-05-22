"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowDown, CheckCircle2, MessageSquareText } from "lucide-react";

import { decodeHtml, ingestVideo, WS_BASE, type YouTubeVideo } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ShimmerBlock } from "@/components/ui/feedback-states";
import { sectionReveal, sectionViewport, smoothEase, staggerContainer, subtleItemReveal } from "@/lib/motion";

const STEP_LABELS = [
  "Extracting transcript",
  "Cleaning timestamp segments",
  "Creating semantic chunks",
  "Generating embeddings",
  "Indexing vector store",
  "Initializing AI memory",
];

interface ProcessingScreenProps {
  selectedVideo: YouTubeVideo | null;
  onStart?: () => void;
  onComplete?: () => void;
}

export function ProcessingScreen({ selectedVideo, onStart, onComplete }: ProcessingScreenProps) {
  const prefersReducedMotion = useReducedMotion();
  const [progress, setProgress] = useState(0);
  const [stepLabel, setStepLabel] = useState("");
  const [isComplete, setIsComplete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasStarted, setHasStarted] = useState(false);
  const completedRef = useRef(false);

  // Reset state whenever a new video is selected
  useEffect(() => {
    setHasStarted(false);
    setProgress(0);
    setStepLabel("");
    setIsComplete(false);
    setError(null);
    completedRef.current = false;
  }, [selectedVideo?.video_id]);

  useEffect(() => {
    if (!selectedVideo || hasStarted) return;
    setHasStarted(true);
    setError(null);
    onStart?.();

    const videoId = selectedVideo.video_id;

    // -- REST fallback (fake progress ticker) ---------------------------------
    function startRestFallback() {
      let current = 5;
      setProgress(5);
      const ticker = window.setInterval(() => {
        current = Math.min(current + 2, 88);
        setProgress(current);
      }, 600);

      ingestVideo(videoId)
        .then(() => {
          window.clearInterval(ticker);
          if (!completedRef.current) {
            completedRef.current = true;
            setProgress(100);
            setIsComplete(true);
            onComplete?.();
          }
        })
        .catch((err: unknown) => {
          window.clearInterval(ticker);
          setError(err instanceof Error ? err.message : "Processing failed");
        });

      return () => window.clearInterval(ticker);
    }

    // -- WebSocket stream (real progress) --------------------------------------
    if (typeof WebSocket === "undefined") {
      return startRestFallback();
    }

    let ws: WebSocket;
    try {
      ws = new WebSocket(`${WS_BASE}/api/videos/${videoId}/ingest/stream`);
    } catch {
      return startRestFallback();
    }

    let wsConnected = false;

    ws.onopen = () => {
      wsConnected = true;
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data as string) as {
          type: string;
          step: string;
          label: string;
          progress: number;
          chunk_count?: number;
          error?: string;
        };

        setProgress(data.progress);
        if (data.label) setStepLabel(data.label);

        if (data.type === "ready" && !completedRef.current) {
          completedRef.current = true;
          setIsComplete(true);
          onComplete?.();
        } else if (data.type === "error") {
          setError(data.error ?? "Processing failed");
        }
      } catch {
        // ignore malformed events
      }
    };

    ws.onerror = () => {
      if (!wsConnected && !completedRef.current) {
        startRestFallback();
      }
    };

    ws.onclose = (e: CloseEvent) => {
      if (!e.wasClean && !completedRef.current && wsConnected) {
        setError("Connection lost during processing. Please retry.");
      }
    };

    return () => {
      ws.close();
    };
  }, [selectedVideo, hasStarted]);

  // Derive display label: real (from WS event) or estimated from progress
  const displayLabel =
    stepLabel ||
    STEP_LABELS[Math.min(STEP_LABELS.length - 1, Math.floor((progress / 100) * STEP_LABELS.length))];

  const remainingSeconds = Math.max(1, Math.ceil((100 - progress) * 0.55));

  return (
    <motion.section
      id="processing"
      aria-label="AI video processing status"
      style={{ scrollMarginTop: "1.5rem" }}
      variants={sectionReveal}
      initial="hidden"
      whileInView="visible"
      viewport={sectionViewport}
      className="premium-panel relative overflow-hidden p-4 text-left sm:p-6 lg:p-8"
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_18%,rgba(34,211,238,.18),transparent_28%),radial-gradient(circle_at_88%_78%,rgba(236,72,153,.18),transparent_30%)]" />
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-pink-300/50 to-transparent" />

      <motion.div variants={staggerContainer} className="relative min-w-0">
        <motion.div variants={subtleItemReveal}>
          <h2 className="max-w-2xl text-2xl font-black leading-tight text-white sm:text-4xl">
            {selectedVideo
              ? `Preparing: ${decodeHtml(selectedVideo.title)}`
              : "Select a video above to start."}
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-7 text-slate-300 sm:text-base">
            {selectedVideo
              ? "The transcript is being cleaned, chunked, embedded, and indexed so the AI can answer from the video, not guess."
              : "Click Prepare on any video card to fetch its transcript, build embeddings, and enable AI chat."}
          </p>
          <Button type="button" variant="ghost" className="mt-5" asChild>
            <a href="#assistant">
              Meet the assistant
              <ArrowDown aria-hidden="true" className="size-4" />
            </a>
          </Button>

          <AnimatePresence mode="wait">
            {isComplete ? (
              <motion.div
                key="ready"
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
                className="relative mt-7 overflow-hidden rounded-[1.5rem] border border-emerald-300/30 bg-emerald-300/[0.08] p-5 shadow-[0_0_48px_rgba(16,185,129,.12)] backdrop-blur-xl"
                role="status"
                aria-live="polite"
              >
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300/60 to-transparent" />
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="grid size-10 shrink-0 place-items-center rounded-xl border border-emerald-300/25 bg-emerald-300/10 text-emerald-100">
                      <CheckCircle2 aria-hidden="true" className="size-5" />
                    </div>
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-300">Ready</p>
                      <p className="text-base font-black text-white">Your video is prepared. Ask anything.</p>
                      <p className="mt-0.5 text-xs text-slate-400">
                        Transcript chunked * embeddings stored * citations indexed
                      </p>
                    </div>
                  </div>
                  <a
                    href="#workspace"
                    className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full bg-gradient-to-r from-emerald-400 to-cyan-400 px-5 py-2.5 text-sm font-bold text-black shadow-[0_0_40px_rgba(52,211,153,.35)] transition hover:shadow-[0_0_56px_rgba(52,211,153,.5)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
                  >
                    <MessageSquareText aria-hidden="true" className="size-4" />
                    Start chatting
                  </a>
                </div>
              </motion.div>
            ) : error ? (
              <motion.div
                key="error"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                role="alert"
                className="mt-7 rounded-[1.25rem] border border-red-300/25 bg-red-500/[0.08] p-4 backdrop-blur-xl"
              >
                <p className="text-sm font-bold text-red-100">Processing failed</p>
                <p className="mt-1 text-xs text-red-100/80">{error}</p>
                <button
                  type="button"
                  onClick={() => {
                    setHasStarted(false);
                    setError(null);
                    setProgress(0);
                    setStepLabel("");
                    completedRef.current = false;
                  }}
                  className="mt-2 text-xs font-semibold text-red-100 underline underline-offset-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300"
                >
                  Retry
                </button>
              </motion.div>
            ) : (
              <motion.div
                key="progress"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="premium-panel-soft mt-7 p-4"
              >
                <div className="flex flex-wrap items-end justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-400">Current step</p>
                    {progress < 5 ? (
                      <ShimmerBlock className="mt-2 h-6 w-64 max-w-full" />
                    ) : (
                      <p className="mt-1 text-lg font-black text-white">{displayLabel}</p>
                    )}
                  </div>
                  <div className="text-right">
                    <p className="text-3xl font-black tabular-nums text-white">{progress}%</p>
                    <p className="text-xs text-slate-400">about {remainingSeconds}s left</p>
                  </div>
                </div>
                <div
                  className="mt-5 h-3 overflow-hidden rounded-full border border-white/10 bg-black/45"
                  role="progressbar"
                  aria-valuenow={progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Video processing progress"
                >
                  <motion.div
                    className="relative h-full overflow-hidden rounded-full bg-gradient-to-r from-pink-500 via-cyan-300 to-blue-500 shadow-[0_0_28px_rgba(34,211,238,.55)]"
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.65, ease: smoothEase }}
                  >
                    <motion.span
                      aria-hidden="true"
                      animate={prefersReducedMotion ? {} : { x: ["-40%", "130%"] }}
                      transition={{ duration: 1.6, repeat: prefersReducedMotion ? 0 : Infinity, ease: "easeInOut" }}
                      className="absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-transparent via-white/45 to-transparent"
                    />
                  </motion.div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      </motion.div>

      <div className="sr-only" aria-live="polite">
        {isComplete
          ? "Processing complete. Your video is ready. You can now start chatting."
          : error
          ? `Processing failed: ${error}`
          : `Processing: ${displayLabel}. Estimated ${remainingSeconds} seconds remaining.`}
      </div>
    </motion.section>
  );
}
