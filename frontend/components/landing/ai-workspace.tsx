"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Bot,
  Captions,
  ChevronDown,
  Clock3,
  FileText,
  Mic,
  Play,
  Send,
  Sparkles,
  Square,
  UserRound,
  Volume2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  CinematicProgress,
  EmptyState,
  ErrorState,
  ProcessingSteps,
  ShimmerBlock
} from "@/components/ui/feedback-states";
import { Input } from "@/components/ui/input";
import { agentChatWithVideo, transcribeSpeech, type TimestampCitation, type YouTubeVideo } from "@/lib/api";
import { elapsedAnalyticsMs, markAnalyticsStart, trackAnalyticsEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { sectionReveal, sectionViewport, smoothEase, springMotion, staggerContainer, subtleItemReveal } from "@/lib/motion";

// -- SpeechRecognition browser types -----------------------------------------

type SpeechRecognitionResultLike = { isFinal: boolean; 0: { transcript: string } };
type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechRecognitionResultLike };
};
type SpeechRecognitionErrorEventLike = { error: string };
type SpeechRecognitionLike = {
  continuous: boolean; interimResults: boolean; lang: string;
  onstart: (() => void) | null; onend: (() => void) | null;
  onerror: ((e: SpeechRecognitionErrorEventLike) => void) | null;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  start: () => void; stop: () => void;
};
type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;
type SpeechWindow = Window & {
  SpeechRecognition?: SpeechRecognitionConstructor;
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
};

const workspaceWaveformBars = [10, 16, 8, 20, 13, 22, 9, 17, 12];

const transcriptSegments = [
  {
    time: "00:42",
    title: "Problem framing",
    text: "The speaker explains why passive video watching makes learning feel productive while retention stays low."
  },
  {
    time: "03:18",
    title: "Transcript grounding",
    text: "A searchable transcript becomes the evidence layer for summaries, answers, and timestamp citations."
  },
  {
    time: "07:06",
    title: "Retrieval step",
    text: "The system retrieves the most relevant chunks before generating a response, keeping the answer tied to source context."
  },
  {
    time: "11:52",
    title: "Learning workflow",
    text: "Users can ask follow-up questions, jump to exact moments, and turn the video into notes or quizzes."
  }
];

const responseText =
  "The video argues that YouTube becomes more useful for learning when the transcript is treated as a structured knowledge source. The key workflow is: extract timestamped transcript segments, retrieve the most relevant chunks for a question, then answer only from that evidence. That is what enables reliable citations like 03:18 and 07:06 instead of generic AI guesses.";

const suggestedPrompts = [
  "Summarize the video",
  "Show key timestamps",
  "Make study notes"
];
const chatLoadingSteps = ["Retrieving transcript chunks", "Checking citations", "Composing answer"];

// ---------------------------------------------------------------------------
// Text-to-speech hook
// ---------------------------------------------------------------------------

function pickMaleVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  // Explicit male voice names (Windows + macOS + Chrome)
  const maleNames = /microsoft david|microsoft mark|microsoft james|google uk english male|daniel|thomas|alex|fred|bruce|junior/i;
  return (
    voices.find(v => maleNames.test(v.name)) ??
    voices.find(v => /\bmale\b/i.test(v.name)) ??
    voices.find(v => !/female|zira|samantha|victoria|karen|moira|fiona|tessa|veena|siri/i.test(v.name) && v.lang.startsWith("en")) ??
    null
  );
}

function useSpeech() {
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null);
  const [supported, setSupported] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    setSupported(true);

    function loadVoices() {
      const voices = window.speechSynthesis.getVoices();
      if (voices.length > 0) voiceRef.current = pickMaleVoice(voices);
    }

    loadVoices();
    window.speechSynthesis.addEventListener("voiceschanged", loadVoices);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", loadVoices);
  }, []);

  function speak(text: string, index: number) {
    if (!supported) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    if (voiceRef.current) utterance.voice = voiceRef.current;
    utterance.pitch = 0.8;
    utterance.rate = 0.95;
    utterance.onend = () => setSpeakingIndex(null);
    utterance.onerror = () => setSpeakingIndex(null);
    setSpeakingIndex(index);
    window.speechSynthesis.speak(utterance);
  }

  function stop() {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeakingIndex(null);
  }

  return { speak, stop, speakingIndex, supported };
}

function useStreamingText(text: string, speed = 18) {
  const [streamedText, setStreamedText] = useState("");

  useEffect(() => {
    setStreamedText("");
    let index = 0;

    const timer = window.setInterval(() => {
      index += 2;
      setStreamedText(text.slice(0, index));

      if (index >= text.length) {
        window.clearInterval(timer);
      }
    }, speed);

    return () => window.clearInterval(timer);
  }, [speed, text]);

  return streamedText;
}

interface AIWorkspaceProps {
  selectedVideo: YouTubeVideo | null;
}

interface ChatEntry {
  role: "user" | "assistant";
  content: string;
  citations?: TimestampCitation[];
  toolSteps?: string[];
}

export function AIWorkspace({ selectedVideo }: AIWorkspaceProps) {
  const prefersReducedMotion = useReducedMotion();
  const { speak, stop, speakingIndex, supported: ttsSupported } = useSpeech();
  const [message, setMessage] = useState("");
  const [chatState, setChatState] = useState<"idle" | "loading" | "empty" | "error">("idle");
  const [chatProgress, setChatProgress] = useState(0);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [history, setHistory] = useState<ChatEntry[]>([]);

  // Voice input state
  const [voiceIsListening, setVoiceIsListening] = useState(false);
  const [voiceInterim, setVoiceInterim] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const [voiceIsSpeechSupported, setVoiceIsSpeechSupported] = useState(true);
  const [voiceIsWhisperRecording, setVoiceIsWhisperRecording] = useState(false);
  const [voiceIsWhisperProcessing, setVoiceIsWhisperProcessing] = useState(false);
  const [voiceUseWhisperFallback, setVoiceUseWhisperFallback] = useState(false);
  const [voiceRecordingSeconds, setVoiceRecordingSeconds] = useState(0);

  // Voice refs
  const voiceRecognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const voiceCommittedRef = useRef("");
  const voiceShouldRestartRef = useRef(false);
  const voiceMediaRecorderRef = useRef<MediaRecorder | null>(null);
  const voiceAudioChunksRef = useRef<Blob[]>([]);
  const voiceRecordingTimerRef = useRef<number | null>(null);
  const voiceRecordingStartRef = useRef(0);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Reset chat when video changes
  useEffect(() => {
    setHistory([]);
    setSessionId(undefined);
    setChatState("idle");
    setMessage("");
  }, [selectedVideo?.video_id]);

  // Scroll chat to bottom when history grows
  useEffect(() => {
    if (!history.length) return;
    const chatScroll = chatScrollRef.current;
    if (!chatScroll) return;

    chatScroll.scrollTo({
      top: chatScroll.scrollHeight,
      behavior: prefersReducedMotion ? "auto" : "smooth",
    });
  }, [history, chatState, prefersReducedMotion]);

  // Set up Web Speech API for voice input
  useEffect(() => {
    const SpeechRecognition =
      (window as SpeechWindow).SpeechRecognition ??
      (window as SpeechWindow).webkitSpeechRecognition;

    if (!SpeechRecognition) { setVoiceIsSpeechSupported(false); return; }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";

    const startedAtRef = { current: 0 };

    recognition.onstart = () => {
      startedAtRef.current = Date.now();
      setVoiceIsListening(true);
      setVoiceError("");
    };

    recognition.onend = () => {
      setVoiceInterim("");
      const lived = Date.now() - startedAtRef.current;
      if (voiceShouldRestartRef.current && lived > 300) {
        window.setTimeout(() => {
          if (voiceShouldRestartRef.current) {
            try { recognition.start(); }
            catch { setVoiceIsListening(false); voiceShouldRestartRef.current = false; }
          }
        }, 300);
        return;
      }
      if (voiceShouldRestartRef.current && lived <= 300) {
        setVoiceIsListening(false);
        voiceShouldRestartRef.current = false;
        setVoiceError("Could not connect to speech service. Try again.");
        return;
      }
      setVoiceIsListening(false);
    };

    recognition.onerror = (event) => {
      setVoiceIsListening(false);
      setVoiceInterim("");
      voiceShouldRestartRef.current = false;
      if (event.error === "network") {
        setVoiceUseWhisperFallback(true);
        setVoiceError("Speech service unavailable. Tap mic to record with Whisper.");
        return;
      }
      const msg: Record<string, string> = {
        "not-allowed": "Microphone permission is blocked.",
        "no-speech": "No speech detected. Try speaking louder.",
        "audio-capture": "No microphone found.",
      };
      setVoiceError(msg[event.error] ?? "Voice input stopped. Try again.");
    };

    recognition.onresult = (event) => {
      let interim = "";
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      if (finalText) {
        voiceCommittedRef.current = `${voiceCommittedRef.current} ${finalText}`.replace(/\s+/g, " ").trim();
        setMessage(voiceCommittedRef.current);
      }
      setVoiceInterim(interim.trim());
    };

    voiceRecognitionRef.current = recognition;
    return () => {
      voiceShouldRestartRef.current = false;
      recognition.onstart = null; recognition.onend = null;
      recognition.onerror = null; recognition.onresult = null;
      recognition.stop();
    };
  }, []);

  function getBestMimeType(): string {
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg", "audio/mp4"];
    return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  }

  async function startWhisperRecording() {
    setVoiceError("");
    setVoiceRecordingSeconds(0);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getBestMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      voiceAudioChunksRef.current = [];

      recorder.ondataavailable = (e) => { if (e.data.size > 0) voiceAudioChunksRef.current.push(e.data); };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (voiceRecordingTimerRef.current !== null) {
          window.clearInterval(voiceRecordingTimerRef.current);
          voiceRecordingTimerRef.current = null;
        }
        setVoiceIsWhisperRecording(false);
        setVoiceIsWhisperProcessing(true);
        try {
          const blob = new Blob(voiceAudioChunksRef.current, { type: mimeType || "audio/webm" });
          const transcript = await transcribeSpeech(blob);
          if (transcript) {
            voiceCommittedRef.current = `${voiceCommittedRef.current} ${transcript}`.replace(/\s+/g, " ").trim();
            setMessage(voiceCommittedRef.current);
          } else {
            setVoiceError("Nothing detected. Speak clearly and try again.");
          }
        } catch {
          setVoiceError("Transcription failed. Try again.");
        } finally {
          setVoiceIsWhisperProcessing(false);
          setVoiceRecordingSeconds(0);
        }
      };

      recorder.start(250);
      voiceRecordingStartRef.current = Date.now();
      voiceMediaRecorderRef.current = recorder;
      setVoiceIsWhisperRecording(true);
      voiceRecordingTimerRef.current = window.setInterval(() => {
        setVoiceRecordingSeconds(Math.floor((Date.now() - voiceRecordingStartRef.current) / 1000));
      }, 500);
    } catch {
      setVoiceError("Microphone access denied.");
    }
  }

  function stopWhisperRecording() {
    const elapsed = Date.now() - voiceRecordingStartRef.current;
    if (elapsed < 1500) window.setTimeout(() => voiceMediaRecorderRef.current?.stop(), 1500 - elapsed);
    else voiceMediaRecorderRef.current?.stop();
  }

  function toggleVoiceInput() {
    setVoiceError("");
    if (voiceIsWhisperRecording) { stopWhisperRecording(); return; }
    if (voiceUseWhisperFallback || !voiceIsSpeechSupported || !voiceRecognitionRef.current) {
      setVoiceUseWhisperFallback(false);
      startWhisperRecording();
      return;
    }
    if (voiceIsListening) {
      voiceShouldRestartRef.current = false;
      voiceRecognitionRef.current.stop();
      return;
    }
    voiceCommittedRef.current = message;
    setVoiceInterim("");
    voiceShouldRestartRef.current = true;
    try { voiceRecognitionRef.current.start(); }
    catch {
      voiceShouldRestartRef.current = false;
      setVoiceUseWhisperFallback(true);
      setVoiceError("Voice unavailable. Tap mic to record with Whisper.");
    }
  }

  async function submitQuestion(question: string) {
    const trimmed = question.trim();
    if (!trimmed) { setChatState("empty"); return; }
    if (!selectedVideo) { setChatState("error"); return; }
    const startedAt = markAnalyticsStart();
    if (history.filter((entry) => entry.role === "user").length === 0) {
      trackAnalyticsEvent("chat_started", { video_id: selectedVideo.video_id });
    }
    trackAnalyticsEvent("message_sent", {
      video_id: selectedVideo.video_id,
      message_length: trimmed.length,
      is_followup: history.some((entry) => entry.role === "user"),
    });

    // Stop any active voice input before submitting
    if (voiceIsListening) {
      voiceShouldRestartRef.current = false;
      voiceRecognitionRef.current?.stop();
    }
    voiceCommittedRef.current = "";
    setVoiceInterim("");

    setHistory((prev) => [...prev, { role: "user", content: trimmed }]);
    setMessage("");
    setChatState("loading");
    setChatProgress(18);

    const t1 = window.setTimeout(() => setChatProgress(55), 400);
    const t2 = window.setTimeout(() => setChatProgress(82), 900);

    try {
      const data = await agentChatWithVideo(trimmed, selectedVideo.video_id, sessionId);
      const responseMs = elapsedAnalyticsMs(startedAt);
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      setSessionId(data.session_id);
      setHistory((prev) => [
        ...prev,
        { role: "assistant", content: data.answer, citations: data.citations, toolSteps: data.tool_steps_used },
      ]);
      if (/summarize/i.test(trimmed)) {
        trackAnalyticsEvent("summary_generated", { video_id: selectedVideo.video_id }, responseMs);
      }
      if (/study notes/i.test(trimmed)) {
        trackAnalyticsEvent("study_notes_generated", { video_id: selectedVideo.video_id }, responseMs);
      }
      setChatProgress(100);
      setChatState("idle");
    } catch (err) {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      setChatState("error");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitQuestion(message);
  }

  const latestAnswer = history.filter((e) => e.role === "assistant").at(-1);
  const latestCitations = latestAnswer?.citations ?? [];

  return (
    <motion.section
      id="workspace"
      aria-label="AI video workspace"
      style={{ scrollMarginTop: "1.5rem" }}
      variants={sectionReveal}
      initial="hidden"
      whileInView="visible"
      viewport={sectionViewport}
      className="premium-panel relative overflow-hidden p-4 text-left sm:p-5 lg:p-6"
    >
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_20%,rgba(236,72,153,.16),transparent_30%),radial-gradient(circle_at_82%_10%,rgba(34,211,238,.18),transparent_30%)]" />
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/60 to-transparent" />

      <motion.div
        variants={staggerContainer}
        className="relative mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between"
      >
        <motion.div variants={subtleItemReveal}>
          <h2 className="max-w-3xl text-2xl font-black text-white sm:text-3xl">
            Ask the video and verify every answer.
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
            The chat uses the selected transcript as evidence, keeps follow-up context,
            and surfaces timestamps you can jump back to.
          </p>
        </motion.div>
        <motion.div
          variants={subtleItemReveal}
          animate={prefersReducedMotion ? {} : { opacity: [0.82, 1, 0.82] }}
          transition={{ duration: 2.4, repeat: prefersReducedMotion ? 0 : Infinity, ease: "easeInOut" }}
          role="status"
          aria-label="AI assistant ready for follow-up questions"
          className="inline-flex w-fit items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1.5 text-xs font-semibold text-emerald-100"
        >
          <span aria-hidden="true" className="size-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,.9)]" />
          Ready for follow-ups
        </motion.div>
      </motion.div>

      <div className="relative grid min-w-0 gap-4 lg:grid-cols-[0.9fr_1.1fr] xl:grid-cols-[0.9fr_1.12fr_0.86fr]">
        <motion.aside
          initial={{ opacity: 1, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 0.45, ease: smoothEase }}
          whileHover={{ y: -3, scale: 1.006 }}
          className="premium-panel-soft min-w-0 overflow-hidden"
        >
          <div className="relative aspect-video overflow-hidden bg-gradient-to-br from-slate-900 via-slate-950 to-slate-900">
            {selectedVideo?.thumbnail_url ? (
              <img
                src={selectedVideo.thumbnail_url}
                alt=""
                aria-hidden="true"
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : null}
            <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,.78),transparent_65%)]" />
            {selectedVideo ? (
              <a
                href={selectedVideo.youtube_url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Watch ${selectedVideo.title} on YouTube`}
                className="absolute left-1/2 top-1/2 grid size-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/25 bg-white/20 text-white shadow-[0_0_54px_rgba(255,255,255,.22)] backdrop-blur-xl transition duration-200 hover:scale-105 hover:bg-white/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
              >
                <Play aria-hidden="true" className="ml-1 size-6 fill-white" />
              </a>
            ) : null}
          </div>
          <div className="p-5">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-pink-100">
              Selected video
            </p>
            {selectedVideo ? (
              <>
                <h3 className="mt-2 text-xl font-black leading-tight text-white">
                  {selectedVideo.title}
                </h3>
                <p className="mt-3 line-clamp-3 text-sm leading-6 text-slate-300">
                  {selectedVideo.description}
                </p>
                <p className="mt-3 text-xs text-slate-400">{selectedVideo.channel_title}</p>
                <div className="mt-4 grid grid-cols-2 gap-2">
                  {["Transcript ready", `${latestCitations.length} citations`].map((item) => (
                    <div
                      key={item}
                      className="rounded-2xl border border-white/10 bg-black/30 px-3 py-2 text-xs font-medium text-slate-300"
                    >
                      {item}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="mt-3 text-sm text-slate-400">
                No video selected yet. Use the carousel above to pick one.
              </p>
            )}
          </div>
        </motion.aside>

        <motion.section
          initial={{ opacity: 1, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 0.45, delay: 0.08, ease: smoothEase }}
          className="premium-panel-soft order-first flex h-[34rem] min-h-0 min-w-0 flex-col overflow-hidden p-4 sm:h-[36rem] sm:p-5 lg:order-none lg:col-span-2 lg:h-[40rem] xl:col-span-1"
        >
          <div className="flex items-center justify-between border-b border-white/10 pb-4">
            <div className="flex items-center gap-3">
              <div className="grid size-11 place-items-center rounded-2xl border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
                <Bot aria-hidden="true" className="size-5" />
              </div>
              <div>
                <h3 className="font-black text-white">AskTube Assistant</h3>
                <p className="text-xs text-slate-400">Transcript-only answers</p>
              </div>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-cyan-100">
              <span className="size-2 rounded-full bg-cyan-200 motion-safe:animate-pulse" />
              Live
            </div>
          </div>

          <div ref={chatScrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain py-5">
            {history.length === 0 && chatState === "idle" && (
              <p className="text-center text-sm text-slate-500">
                {selectedVideo
                  ? "Ask anything about this video - the AI answers from the transcript only."
                  : "Select and prepare a video first, then ask questions here."}
              </p>
            )}

            {history.map((entry, i) => (
              <div key={i} className="flex gap-3">
                {entry.role === "user" ? (
                  <>
                    <div className="grid size-8 shrink-0 place-items-center rounded-full bg-white text-black">
                      <UserRound aria-hidden="true" className="size-4" />
                    </div>
                    <div className="max-w-[calc(100%-2.75rem)] rounded-[1.25rem] border border-white/10 bg-black/30 px-4 py-3 text-sm leading-6 text-slate-200 sm:max-w-[88%]">
                      {entry.content}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="grid size-8 shrink-0 place-items-center rounded-full border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
                      <Bot aria-hidden="true" className="size-4" />
                    </div>
                    <div className="max-w-[calc(100%-2.75rem)] sm:max-w-[92%] space-y-1.5">
                      <div className="rounded-[1.25rem] border border-cyan-200/15 bg-cyan-200/[0.075] px-4 py-3 text-sm leading-7 text-slate-100 shadow-[0_0_46px_rgba(34,211,238,.10)]">
                        <p aria-live="polite">{entry.content}</p>
                        {entry.citations && entry.citations.length > 0 && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {entry.citations.map((c) => (
                              <span
                                key={c.chunk_id}
                                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-semibold text-cyan-100"
                              >
                                <Clock3 aria-hidden="true" className="size-3.5" />
                                {c.timestamp}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-3 px-1">
                        {entry.toolSteps && entry.toolSteps.length > 0 && (
                          <p className="text-[10px] text-slate-500">
                            <Sparkles aria-hidden="true" className="mr-1 inline size-3 text-cyan-400/60" />
                            {entry.toolSteps.join(" -> ")}
                          </p>
                        )}
                        {ttsSupported && (
                          <button
                            type="button"
                            aria-label={speakingIndex === i ? "Stop reading aloud" : "Read answer aloud"}
                            onClick={() => speakingIndex === i ? stop() : speak(entry.content, i)}
                            disabled={speakingIndex !== null && speakingIndex !== i}
                            className="ml-auto inline-flex items-center gap-1 rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[10px] font-medium text-slate-400 transition hover:border-cyan-300/30 hover:text-cyan-200 disabled:pointer-events-none disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                          >
                            {speakingIndex === i ? (
                              <><Square aria-hidden="true" className="size-2.5 fill-current" />Stop</>
                            ) : (
                              <><Volume2 aria-hidden="true" className="size-2.5" />Read aloud</>
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>
            ))}

            <AnimatePresence mode="wait">
              {chatState === "loading" ? (
                <motion.div
                  key="chat-loading"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.24, ease: smoothEase }}
                  className="rounded-[1.25rem] border border-white/10 bg-black/25 p-4"
                  aria-live="polite"
                >
                  <CinematicProgress
                    value={chatProgress}
                    label="Grounding answer in transcript"
                    remaining="about 5s left"
                  />
                  <div className="mt-4 grid gap-3 md:grid-cols-[0.9fr_1.1fr]">
                    <ProcessingSteps
                      steps={chatLoadingSteps}
                      activeIndex={Math.min(chatLoadingSteps.length - 1, Math.floor(chatProgress / 34))}
                    />
                    <div className="space-y-2">
                      <ShimmerBlock className="h-4 w-full" />
                      <ShimmerBlock className="h-4 w-5/6" />
                      <ShimmerBlock className="h-4 w-2/3" />
                    </div>
                  </div>
                </motion.div>
              ) : null}

              {chatState === "empty" ? (
                <motion.div
                  key="chat-empty"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.24, ease: smoothEase }}
                >
                  <EmptyState
                    title="Ask anything the video can prove"
                    description="Try a summary, a timestamp request, or a specific follow-up. Answers stay tied to transcript evidence."
                    action={
                      <Button type="button" variant="ghost" onClick={() => setChatState("idle")}>
                        Choose a prompt
                      </Button>
                    }
                  />
                </motion.div>
              ) : null}

              {chatState === "error" ? (
                <motion.div
                  key="chat-error"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.24, ease: smoothEase }}
                >
                  <ErrorState
                    title="The answer could not be generated"
                    description="Make sure the video was processed first. Retry or try a different question."
                    retryLabel="Retry"
                    onRetry={() => setChatState("idle")}
                  />
                </motion.div>
              ) : null}
            </AnimatePresence>
          </div>

          <div className="space-y-3 border-t border-white/10 pt-4">
            <div className="flex flex-wrap gap-2">
              {suggestedPrompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  aria-label={`Ask: ${prompt}`}
                  onClick={() => {
                    trackAnalyticsEvent("suggested_prompt_clicked", {
                      prompt,
                      video_id: selectedVideo?.video_id,
                    });
                    setMessage(prompt);
                    submitQuestion(prompt);
                  }}
                  className="min-h-12 rounded-full border border-white/10 bg-black/25 px-3 py-2 text-xs font-medium text-slate-300 transition duration-200 hover:border-cyan-200/35 hover:bg-cyan-200/[0.06] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                >
                  {prompt}
                </button>
              ))}
            </div>

            {/* Voice feedback strip */}
            <AnimatePresence>
              {(voiceIsListening || voiceIsWhisperRecording || voiceIsWhisperProcessing || voiceError) && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22 }}
                  className="overflow-hidden rounded-2xl border border-white/10 bg-black/30 px-4 py-2.5"
                >
                  {voiceError ? (
                    <p className="text-xs text-red-300">{voiceError}</p>
                  ) : voiceIsWhisperProcessing ? (
                    <div className="flex items-center gap-2">
                      <span className="size-3 shrink-0 rounded-full border-2 border-cyan-300 border-t-transparent motion-safe:animate-spin" />
                      <p className="text-xs text-cyan-200">Transcribing with Whisper...</p>
                    </div>
                  ) : (
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-cyan-200">
                        {voiceIsWhisperRecording
                          ? `Recording ${voiceRecordingSeconds}s — tap mic to stop`
                          : "Listening..."}
                      </span>
                      <div aria-hidden="true" className="ml-auto flex h-5 items-end gap-0.5">
                        {workspaceWaveformBars.map((h, i) => (
                          <motion.span
                            key={i}
                            animate={prefersReducedMotion ? { height: 3 } : {
                              height: [3, h, 4],
                              opacity: [0.4, 1, 0.5],
                            }}
                            transition={{ duration: 0.75, repeat: Infinity, ease: "easeInOut", delay: i * 0.07 }}
                            className="w-1 rounded-full bg-gradient-to-t from-pink-400 to-cyan-300"
                            style={{ height: 3 }}
                          />
                        ))}
                      </div>
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            <form onSubmit={handleSubmit} className="flex flex-col gap-2 sm:flex-row">
              <label className="sr-only" htmlFor="workspace-message">
                Ask a question about the video
              </label>
              <Input
                id="workspace-message"
                value={[message, voiceInterim].filter(Boolean).join(" ")}
                onChange={(event) => {
                  setMessage(event.target.value);
                  voiceCommittedRef.current = event.target.value;
                  setVoiceInterim("");
                }}
                placeholder="Ask for a summary, timestamp, or follow-up..."
                className="h-12 rounded-2xl bg-black/30"
              />
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant={voiceIsListening || voiceIsWhisperRecording ? "red" : "ghost"}
                  size="icon"
                  aria-label={
                    voiceIsWhisperRecording ? "Stop recording"
                    : voiceIsListening ? "Stop voice input"
                    : voiceIsWhisperProcessing ? "Transcribing..."
                    : "Voice input"
                  }
                  onClick={toggleVoiceInput}
                  disabled={voiceIsWhisperProcessing}
                  className="relative min-h-12 w-full shrink-0 overflow-visible sm:w-12"
                >
                  {voiceIsWhisperProcessing ? (
                    <span className="size-4 rounded-full border-2 border-cyan-300 border-t-transparent motion-safe:animate-spin" />
                  ) : voiceIsListening || voiceIsWhisperRecording ? (
                    <Volume2 aria-hidden="true" className="size-4" />
                  ) : (
                    <Mic aria-hidden="true" className="size-4" />
                  )}
                  {(voiceIsListening || voiceIsWhisperRecording) && (
                    <span className="absolute inset-0 -z-10 rounded-full bg-red-500/30 motion-safe:animate-ping" />
                  )}
                </Button>
                <Button
                  type="submit"
                  size="icon"
                  aria-label="Send message"
                  className="min-h-12 w-full shrink-0 sm:w-12"
                >
                  <Send aria-hidden="true" className="size-4" />
                  <span className="sm:sr-only">Ask</span>
                </Button>
              </div>
            </form>
          </div>
          <div ref={messagesEndRef} />
        </motion.section>

        <motion.aside
          initial={{ opacity: 1, y: 18 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 0.45, delay: 0.16, ease: smoothEase }}
          className="premium-panel-soft min-w-0 p-4 sm:p-5 lg:col-span-2 xl:col-span-1"
        >
          <input id="workspace-transcript-toggle" type="checkbox" className="peer sr-only" />
          <label
            htmlFor="workspace-transcript-toggle"
            aria-controls="workspace-transcript-panel"
            onClick={() => trackAnalyticsEvent("transcript_opened", { video_id: selectedVideo?.video_id })}
            className="mb-4 flex min-h-12 w-full cursor-pointer items-center justify-between gap-3 text-left peer-checked:[&_.transcript-chevron]:rotate-180 focus-within:outline-none focus-within:ring-2 focus-within:ring-cyan-300 md:pointer-events-none md:cursor-default"
          >
            <div>
              <p className="cinema-eyebrow tracking-[0.2em]">
                <Captions aria-hidden="true" className="size-4" />
                Evidence
              </p>
              <h3 className="mt-2 text-xl font-black text-white">Transcript moments</h3>
            </div>
            <span className="grid size-11 shrink-0 place-items-center rounded-full border border-white/10 bg-white/[0.055] text-slate-300 md:hidden">
              <ChevronDown
                aria-hidden="true"
                className="transcript-chevron size-5 transition duration-200"
              />
            </span>
            <FileText aria-hidden="true" className="hidden size-5 text-slate-400 md:block" />
          </label>

          <motion.div
            id="workspace-transcript-panel"
            className="grid grid-rows-[0fr] opacity-0 transition-all duration-300 ease-out peer-checked:grid-rows-[1fr] peer-checked:opacity-100 md:grid-rows-[1fr] md:opacity-100"
          >
            <div className="min-h-0 space-y-3 overflow-hidden">
              {latestCitations.length === 0 ? (
                <p className="text-sm text-slate-500">
                  Citations will appear here after you ask a question.
                </p>
              ) : (
                latestCitations.map((citation) => (
                  <a
                    key={citation.chunk_id}
                    href={selectedVideo ? `${selectedVideo.youtube_url}&t=${Math.floor(citation.start_seconds)}` : "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={() => trackAnalyticsEvent("timestamp_clicked", {
                      video_id: citation.video_id,
                      chunk_id: citation.chunk_id,
                      start_seconds: citation.start_seconds,
                    })}
                    aria-label={`Jump to ${citation.timestamp} in video`}
                    className="block w-full rounded-2xl border border-cyan-200/30 bg-cyan-200/[0.075] p-4 text-left shadow-[0_0_34px_rgba(34,211,238,.08)] transition duration-200 hover:-translate-y-0.5 hover:border-cyan-200/50 hover:bg-cyan-200/[0.11] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-xs font-bold text-black">
                        <Clock3 aria-hidden="true" className="size-3.5" />
                        {citation.timestamp}
                      </span>
                      <span className="text-xs font-semibold text-cyan-100">cited</span>
                    </div>
                    <p className="mt-3 line-clamp-3 text-sm leading-6 text-slate-300">
                      {citation.text}
                    </p>
                  </a>
                ))
              )}
            </div>
          </motion.div>
        </motion.aside>
      </div>
    </motion.section>
  );
}
