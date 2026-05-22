"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, PerspectiveCamera } from "@react-three/drei";
import { AnimatePresence, motion, useReducedMotion, useSpring, useTransform } from "framer-motion";
import { Bot, Clock3, Send, X } from "lucide-react";
import * as THREE from "three";

import { chatWithVideo, type TimestampCitation, type YouTubeVideo } from "@/lib/api";
import type { JourneyStep } from "@/components/landing/cinematic-hero";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// -- Step messages -------------------------------------------------------------

const ROBOT_SIZE = 140; // px

const STEP_CONFIG: Record<JourneyStep, {
  bubble: string;
  spoken: string;
  position: { left: string; top: string };
  dotColor: string;
}> = {
  // All positions hug the edges - never over page text
  idle: {
    bubble: "Hi! I'm your AI tutor. Search for a YouTube topic above to get started!",
    spoken: "Hi! Search for a topic to find YouTube videos.",
    position: { left: `calc(100% - ${ROBOT_SIZE + 16}px)`, top: "80px" },  // top-right edge
    dotColor: "bg-slate-400",
  },
  searching: {
    bubble: "Searching YouTube for you...",
    spoken: "Searching YouTube.",
    position: { left: `calc(100% - ${ROBOT_SIZE + 16}px)`, top: "160px" }, // right edge, slightly lower
    dotColor: "bg-cyan-400",
  },
  videos_ready: {
    bubble: "Found some videos! Scroll down, pick one and click Prepare.",
    spoken: "I found videos. Pick one and click Prepare.",
    position: { left: "12px", top: "40%" },                                 // left edge, mid
    dotColor: "bg-cyan-400",
  },
  video_selected: {
    bubble: "Great choice! Preparing the transcript now...",
    spoken: "Preparing the video transcript.",
    position: { left: `calc(100% - ${ROBOT_SIZE + 16}px)`, top: "38%" },   // right edge, mid
    dotColor: "bg-purple-400",
  },
  processing: {
    bubble: "Hold on... reading the transcript and building knowledge. Almost there!",
    spoken: "Processing the transcript. Almost ready.",
    position: { left: "12px", top: "58%" },                                 // left edge, lower
    dotColor: "bg-purple-400",
  },
  ready: {
    bubble: "Your video is ready! Click me and ask anything - I answer with timestamps.",
    spoken: "Your video is ready. Ask me anything.",
    position: { left: `calc(100% - ${ROBOT_SIZE + 16}px)`, top: `calc(100% - ${ROBOT_SIZE + 24}px)` }, // bottom-right
    dotColor: "bg-emerald-400",
  },
};

// -- Mini 3D robot -------------------------------------------------------------

const WHITE = "#f0f4f8";
const BLACK_JOINT = "#111827";
const BLUE_GLOW = "#22d3ee";

function MiniRobot({ isReady, isMoving, paused }: { isReady: boolean; isMoving: boolean; paused: boolean }) {
  const groupRef    = useRef<THREE.Group>(null);
  const leftEyeRef  = useRef<THREE.Mesh>(null);
  const rightEyeRef = useRef<THREE.Mesh>(null);
  const antennaRef  = useRef<THREE.Mesh>(null);
  const waveArmRef  = useRef<THREE.Group>(null);
  const leftLegRef  = useRef<THREE.Group>(null);
  const rightLegRef = useRef<THREE.Group>(null);

  useFrame(({ clock }) => {
    if (paused) return;
    const t = clock.elapsedTime;

    if (groupRef.current) {
      groupRef.current.position.y = isMoving ? Math.sin(t * 12) * 0.04 : Math.sin(t * 1.3) * 0.06;
      groupRef.current.rotation.z = isMoving ? Math.sin(t * 9) * 0.07 : Math.sin(t * 0.8) * 0.03;
      groupRef.current.rotation.y = isMoving ? 0.15 : Math.sin(t * 0.6) * 0.14;
    }

    const swing = isMoving ? Math.sin(t * 10) * 0.42 : 0;
    if (leftLegRef.current)  leftLegRef.current.rotation.x  =  swing;
    if (rightLegRef.current) rightLegRef.current.rotation.x = -swing;

    const b = Math.sin(t * 3.4) > 0.94 ? 0.08 : 1;
    if (leftEyeRef.current)  leftEyeRef.current.scale.y  = b;
    if (rightEyeRef.current) rightEyeRef.current.scale.y = b;

    if (antennaRef.current)
      (antennaRef.current.material as THREE.MeshStandardMaterial).emissiveIntensity = 0.8 + Math.sin(t * 2.4) * 0.55;

    if (waveArmRef.current)
      waveArmRef.current.rotation.z = isReady ? 0.35 + Math.sin(t * 4.2) * 0.6 : 0.3 + Math.sin(t * 1.2) * 0.08;
  });

  return (
    <group ref={groupRef} position={[0, 0.15, 0]}>
      {/* Head */}
      <group position={[0, 0.7, 0]}>
        <mesh scale={[1.08, 1.0, 1.0]}>
          <sphereGeometry args={[0.62, 48, 48]} />
          <meshStandardMaterial color={WHITE} metalness={0.15} roughness={0.28} />
        </mesh>
        <mesh position={[0, 0.02, 0.48]} scale={[0.86, 0.72, 0.5]}>
          <sphereGeometry args={[0.58, 36, 36]} />
          <meshStandardMaterial color="#060a14" roughness={0.1} metalness={0.55} />
        </mesh>
        <mesh ref={leftEyeRef} position={[-0.21, 0.1, 0.74]} scale={[0.9, 1, 0.5]}>
          <sphereGeometry args={[0.155, 28, 28]} />
          <meshStandardMaterial color="#0a0e1c" roughness={0.05} />
        </mesh>
        <mesh position={[-0.155, 0.19, 0.83]}><sphereGeometry args={[0.04, 12, 12]} /><meshStandardMaterial color="#fff" /></mesh>
        <mesh ref={rightEyeRef} position={[0.21, 0.1, 0.74]} scale={[0.9, 1, 0.5]}>
          <sphereGeometry args={[0.155, 28, 28]} />
          <meshStandardMaterial color="#0a0e1c" roughness={0.05} />
        </mesh>
        <mesh position={[0.27, 0.19, 0.83]}><sphereGeometry args={[0.04, 12, 12]} /><meshStandardMaterial color="#fff" /></mesh>
        <mesh position={[0, -0.2, 0.76]} rotation={[0.1, 0, 0]}>
          <torusGeometry args={[0.18, 0.022, 14, 28, Math.PI * 0.75]} />
          <meshStandardMaterial color="#060a14" roughness={0.2} />
        </mesh>
        <mesh position={[0, 0.52, 0.5]}><circleGeometry args={[0.1, 32]} /><meshStandardMaterial color={BLUE_GLOW} emissive={BLUE_GLOW} emissiveIntensity={1.4} /></mesh>
        <mesh position={[0, 0.52, 0.49]}><torusGeometry args={[0.12, 0.018, 12, 32]} /><meshStandardMaterial color={WHITE} metalness={0.3} roughness={0.3} /></mesh>
        <mesh position={[0.18, 0.74, 0.1]} rotation={[0, 0, 0.18]}><cylinderGeometry args={[0.018, 0.018, 0.35, 10]} /><meshStandardMaterial color="#c8d8e4" metalness={0.5} /></mesh>
        <mesh ref={antennaRef} position={[0.26, 0.95, 0.12]}><sphereGeometry args={[0.07, 20, 20]} /><meshStandardMaterial color={BLUE_GLOW} emissive={BLUE_GLOW} emissiveIntensity={1.2} roughness={0.1} /></mesh>
        <mesh position={[0.65, 0.08, 0.12]} rotation={[0, Math.PI/2, 0]}><cylinderGeometry args={[0.18, 0.18, 0.07, 24]} /><meshStandardMaterial color="#1a2535" metalness={0.65} /></mesh>
        <mesh position={[0.7, 0.08, 0.12]} rotation={[0, Math.PI/2, 0]}><circleGeometry args={[0.1, 24]} /><meshStandardMaterial color={BLUE_GLOW} emissive={BLUE_GLOW} emissiveIntensity={0.9} /></mesh>
        <mesh position={[-0.66, 0.08, 0.08]} rotation={[0, Math.PI/2, 0]}><cylinderGeometry args={[0.14, 0.14, 0.06, 20]} /><meshStandardMaterial color="#1a2535" metalness={0.6} /></mesh>
      </group>
      {/* Neck */}
      <mesh position={[0, 0.08, 0]}><cylinderGeometry args={[0.13, 0.18, 0.2, 16]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} roughness={0.22} /></mesh>
      {/* Body */}
      <mesh position={[0, -0.38, 0]}><capsuleGeometry args={[0.38, 0.44, 16, 28]} /><meshStandardMaterial color={WHITE} metalness={0.12} roughness={0.3} /></mesh>
      <mesh position={[0, -0.28, 0.37]}><boxGeometry args={[0.3, 0.055, 0.02]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.6} /></mesh>
      {[-0.08, 0, 0.08].map((x, i) => (
        <mesh key={i} position={[x, -0.36, 0.38]}><sphereGeometry args={[0.022, 10, 10]} /><meshStandardMaterial color={i===1?BLUE_GLOW:"#e0f0f8"} emissive={i===1?BLUE_GLOW:"#fff"} emissiveIntensity={i===1?0.9:0.1} /></mesh>
      ))}
      {/* Shoulders */}
      <mesh position={[0.46, -0.06, 0]}><sphereGeometry args={[0.14, 20, 20]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
      <mesh position={[-0.46, -0.06, 0]}><sphereGeometry args={[0.14, 20, 20]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
      {/* Wave arm */}
      <group ref={waveArmRef} position={[0.5, -0.06, 0]} rotation={[0, 0, 0.3]}>
        <mesh position={[0.24, 0, 0]} rotation={[0, 0, Math.PI/2]}><capsuleGeometry args={[0.09, 0.34, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0.48, 0, 0]}><sphereGeometry args={[0.11, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
        <mesh position={[0.72, 0.06, 0]} rotation={[0, 0, Math.PI/2-0.3]}><capsuleGeometry args={[0.08, 0.28, 10, 16]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0.96, 0.14, 0]}><sphereGeometry args={[0.13, 20, 20]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.65} /></mesh>
      </group>
      {/* Other arm */}
      <group position={[-0.5, -0.06, 0]} rotation={[0, 0, -0.2]}>
        <mesh position={[-0.22, 0, 0]} rotation={[0, 0, Math.PI/2]}><capsuleGeometry args={[0.09, 0.3, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[-0.42, 0, 0]}><sphereGeometry args={[0.11, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
        <mesh position={[-0.62, -0.08, 0]} rotation={[0, 0, Math.PI/2+0.2]}><capsuleGeometry args={[0.08, 0.24, 10, 16]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[-0.82, -0.14, 0]}><sphereGeometry args={[0.12, 20, 20]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.65} /></mesh>
      </group>
      {/* Hip joints */}
      <mesh position={[-0.22, -0.72, 0]}><sphereGeometry args={[0.13, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
      <mesh position={[0.22, -0.72, 0]}><sphereGeometry args={[0.13, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
      {/* Left leg */}
      <group ref={leftLegRef} position={[-0.22, -0.72, 0]}>
        <mesh position={[0, -0.22, 0]}><capsuleGeometry args={[0.12, 0.24, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0, -0.42, 0]}><sphereGeometry args={[0.12, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
        <mesh position={[0, -0.62, 0]}><capsuleGeometry args={[0.11, 0.22, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0.04, -0.86, 0.07]} scale={[1, 0.65, 1.3]}><sphereGeometry args={[0.16, 24, 24]} /><meshStandardMaterial color={WHITE} /></mesh>
      </group>
      {/* Right leg */}
      <group ref={rightLegRef} position={[0.22, -0.72, 0]}>
        <mesh position={[0, -0.22, 0]}><capsuleGeometry args={[0.12, 0.24, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0, -0.42, 0]}><sphereGeometry args={[0.12, 18, 18]} /><meshStandardMaterial color={BLACK_JOINT} metalness={0.7} /></mesh>
        <mesh position={[0, -0.62, 0]}><capsuleGeometry args={[0.11, 0.22, 12, 18]} /><meshStandardMaterial color={WHITE} /></mesh>
        <mesh position={[0.04, -0.86, 0.07]} scale={[1, 0.65, 1.3]}><sphereGeometry args={[0.16, 24, 24]} /><meshStandardMaterial color={WHITE} /></mesh>
      </group>
    </group>
  );
}

// -- Chat entry ----------------------------------------------------------------

interface ChatEntry {
  role: "user" | "assistant";
  content: string;
  citations?: TimestampCitation[];
}

// -- Main component ------------------------------------------------------------

interface FloatingCompanionProps {
  isReady: boolean;
  selectedVideo: YouTubeVideo | null;
  journeyStep: JourneyStep;
}

export function FloatingCompanion({ isReady, selectedVideo, journeyStep }: FloatingCompanionProps) {
  const prefersReducedMotion = useReducedMotion();
  const [isOpen, setIsOpen] = useState(false);
  const [showBubble, setShowBubble] = useState(false);
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const [isSending, setIsSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [spokenStep, setSpokenStep] = useState<JourneyStep | null>(null);
  const [isMoving, setIsMoving] = useState(false);
  const bubbleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const cfg = STEP_CONFIG[journeyStep];

  // Reset chat when video changes
  useEffect(() => {
    setHistory([]);
    setSessionId(undefined);
    setChatError(null);
  }, [selectedVideo?.video_id]);

  // Move robot + show bubble on step change
  useEffect(() => {
    if (journeyStep === spokenStep) return;

    if (bubbleTimer.current) clearTimeout(bubbleTimer.current);
    setShowBubble(false);

    // No walking animation on first load (idle); walk for all subsequent steps
    const isFirstLoad = journeyStep === "idle";
    if (!isFirstLoad) setIsMoving(true);

    const arriveDelay = isFirstLoad ? 400 : prefersReducedMotion ? 0 : 700;

    const t = setTimeout(() => {
      setIsMoving(false);
      setSpokenStep(journeyStep);
      setShowBubble(true);

      const speak = () => {
        if (!prefersReducedMotion && "speechSynthesis" in window) {
          window.speechSynthesis.cancel();
          const utter = new SpeechSynthesisUtterance(cfg.spoken);
          utter.rate = 0.95;
          utter.pitch = 0.8;
          const voices = window.speechSynthesis.getVoices();
          const maleVoice = voices.find((v) =>
            /microsoft david|microsoft mark|microsoft james|google uk english male|daniel|thomas|alex|fred/i.test(v.name)
          ) ?? voices.find((v) =>
            !/female|zira|samantha|victoria|karen|moira|fiona|tessa|siri/i.test(v.name) && v.lang.startsWith("en")
          );
          if (maleVoice) utter.voice = maleVoice;
          window.speechSynthesis.speak(utter);
        }
      };

      // Voices may not be loaded yet on first render - wait for them
      if (isFirstLoad && window.speechSynthesis && window.speechSynthesis.getVoices().length === 0) {
        window.speechSynthesis.addEventListener("voiceschanged", speak, { once: true });
      } else {
        speak();
      }

      bubbleTimer.current = setTimeout(
        () => setShowBubble(false),
        journeyStep === "idle" ? 10000 : 6000
      );
    }, arriveDelay);

    return () => clearTimeout(t);
  }, [journeyStep]);

  // Scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history, isSending]);

  async function sendMessage(q: string) {
    const trimmed = q.trim();
    if (!trimmed || !selectedVideo || isSending) return;
    setHistory((prev) => [...prev, { role: "user", content: trimmed }]);
    setMessage("");
    setIsSending(true);
    setChatError(null);
    try {
      const data = await chatWithVideo(trimmed, selectedVideo.video_id, sessionId);
      setSessionId(data.session_id);
      setHistory((prev) => [...prev, { role: "assistant", content: data.answer, citations: data.citations }]);
    } catch {
      setChatError("Could not get an answer. Make sure the video was processed.");
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    sendMessage(message);
  }

  const suggestedPrompts = ["Summarize this video", "Show key timestamps", "Give me study notes"];

  // Determine chat panel position (open left if robot is on the right)
  const robotOnRight = cfg.position.left.includes("100%") || cfg.position.left.includes("calc(100%");
  const robotOnBottom = cfg.position.top.includes("100%") || cfg.position.top.includes("calc(100%");

  return (
    <>
      {/* The roaming robot */}
      <motion.div
        animate={cfg.position}
        transition={prefersReducedMotion
          ? { duration: 0 }
          : { type: "spring", stiffness: 60, damping: 18, mass: 1.2 }
        }
        style={{ position: "fixed", zIndex: 50, width: ROBOT_SIZE, height: ROBOT_SIZE }}
      >
        {/* Speech bubble */}
        <AnimatePresence>
          {showBubble && !isOpen && (
            <motion.div
              key={journeyStep}
              initial={{ opacity: 0, scale: 0.88, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.88, y: 8 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "absolute w-64 rounded-2xl border px-4 py-3 text-sm text-white shadow-[0_8px_32px_rgba(0,0,0,.45)] backdrop-blur-xl",
                // Position bubble above robot, or to the side
                robotOnBottom ? "bottom-full mb-3" : "top-full mt-3",
                robotOnRight ? "right-0" : "left-0",
                journeyStep === "ready"
                  ? "border-emerald-300/30 bg-[#05070d]/92"
                  : journeyStep === "processing" || journeyStep === "video_selected"
                  ? "border-purple-300/30 bg-[#05070d]/92"
                  : "border-cyan-200/25 bg-[#05070d]/92"
              )}
            >
              <div className="mb-1.5 flex items-center gap-1.5">
                <Bot className="size-3 shrink-0 text-cyan-300" />
                <span className="text-[10px] font-bold uppercase tracking-widest text-cyan-300">AskTube AI</span>
              </div>
              <p className="leading-5">{cfg.bubble}</p>
              {/* Tail */}
              <div className={cn(
                "absolute h-2.5 w-2.5 rotate-45 border",
                robotOnBottom
                  ? "bottom-[-6px] border-l-0 border-t-0"
                  : "top-[-6px] border-b-0 border-r-0",
                robotOnRight ? "right-8" : "left-8",
                journeyStep === "ready"
                  ? "border-emerald-300/30 bg-[#05070d]/92"
                  : journeyStep === "processing" || journeyStep === "video_selected"
                  ? "border-purple-300/30 bg-[#05070d]/92"
                  : "border-cyan-200/25 bg-[#05070d]/92"
              )} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Robot canvas button */}
        <div className="relative">

          <motion.button
            type="button"
            onClick={() => { setIsOpen((v) => !v); setShowBubble(false); }}
            aria-label={isOpen ? "Close AI tutor chat" : cfg.bubble.slice(0, 50)}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.92 }}
            className="relative flex items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:rounded-full"
            style={{ width: ROBOT_SIZE, height: ROBOT_SIZE }}
          >
            <Canvas
              dpr={[1, 1.5]}
              gl={{ antialias: true, alpha: true }}
              aria-hidden="true"
              className="absolute inset-0"
              style={{ background: "transparent" }}
            >
              <PerspectiveCamera makeDefault position={[0, 0.1, 4.2]} fov={42} />
              <ambientLight intensity={0.6} />
              <pointLight position={[2, 3, 2]} intensity={32} color="#67e8f9" />
              <pointLight position={[-2, 1, 2]} intensity={20} color="#818cf8" />
              <pointLight position={[0, -1, 3]} intensity={14} color="#ffffff" />
              <MiniRobot isReady={isReady} isMoving={isMoving} paused={!!prefersReducedMotion} />
              <Environment preset="night" />
            </Canvas>

            {/* Step dot */}
            <span className={cn(
              "absolute right-1 top-1 size-3 rounded-full border-2 border-transparent shadow-lg",
              cfg.dotColor,
              (journeyStep === "processing" || journeyStep === "video_selected") && "animate-pulse"
            )} />
          </motion.button>
        </div>

        {/* Chat panel - opens relative to robot position */}
        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, scale: 0.92, y: robotOnBottom ? -12 : 12 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.92 }}
              transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className={cn(
                "absolute flex flex-col overflow-hidden rounded-[1.75rem] border border-white/12 bg-[#07090f]/96 shadow-[0_32px_80px_rgba(0,0,0,.7)] backdrop-blur-2xl",
                robotOnBottom ? "bottom-full mb-3" : "top-full mt-3",
                robotOnRight ? "right-0" : "left-0"
              )}
              style={{ width: "min(90vw, 380px)", height: "min(70vh, 520px)" }}
            >
              {/* Header */}
              <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3.5">
                <div className="grid size-8 shrink-0 place-items-center rounded-xl border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
                  <Bot className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-black text-white">AskTube AI</p>
                  <p className="truncate text-xs text-slate-400">
                    {selectedVideo ? selectedVideo.title : "Select a video first"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {isReady && (
                    <span className="flex items-center gap-1.5 text-xs text-emerald-300">
                      <span className="size-1.5 animate-pulse rounded-full bg-emerald-300" />
                      Live
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => setIsOpen(false)}
                    aria-label="Close chat"
                    className="grid size-7 place-items-center rounded-full border border-white/10 bg-white/[0.06] text-slate-400 transition hover:bg-white/[0.14] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              </div>

              {/* Messages */}
              <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
                {history.length === 0 && (
                  <div className="pt-1">
                    <p className="text-center text-xs text-slate-500">
                      {isReady
                        ? "Ask anything - answers come from the video transcript."
                        : "Prepare a video first to start chatting."}
                    </p>
                    {isReady && (
                      <div className="mt-3 flex flex-wrap justify-center gap-2">
                        {suggestedPrompts.map((p) => (
                          <button
                            key={p}
                            type="button"
                            onClick={() => sendMessage(p)}
                            className="rounded-full border border-white/10 bg-white/[0.055] px-3 py-1.5 text-xs text-slate-300 transition hover:border-cyan-200/30 hover:bg-cyan-200/[0.07] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                          >
                            {p}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {history.map((entry, i) => (
                  <div key={i} className={cn("flex gap-2", entry.role === "user" && "justify-end")}>
                    {entry.role === "assistant" && (
                      <div className="grid size-6 shrink-0 place-items-center rounded-full border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
                        <Bot className="size-3" />
                      </div>
                    )}
                    <div className={cn(
                      "max-w-[85%] rounded-[1rem] px-3 py-2 text-sm leading-6",
                      entry.role === "user"
                        ? "bg-white text-black"
                        : "border border-cyan-200/15 bg-cyan-200/[0.07] text-slate-100"
                    )}>
                      <p>{entry.content}</p>
                      {entry.citations && entry.citations.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {entry.citations.map((c) => (
                            <span key={c.chunk_id} className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-black/30 px-2 py-0.5 text-[11px] font-semibold text-cyan-200">
                              <Clock3 className="size-3" />
                              {c.timestamp}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}

                {isSending && (
                  <div className="flex gap-2">
                    <div className="grid size-6 shrink-0 place-items-center rounded-full border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
                      <Bot className="size-3" />
                    </div>
                    <div className="flex items-center gap-1.5 rounded-[1rem] border border-cyan-200/15 bg-cyan-200/[0.07] px-3 py-2.5">
                      {[0, 1, 2].map((i) => (
                        <motion.span key={i} animate={{ scale: [1, 1.5, 1], opacity: [0.4, 1, 0.4] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.18 }} className="size-1.5 rounded-full bg-cyan-300" />
                      ))}
                    </div>
                  </div>
                )}

                {chatError && <p className="text-center text-xs text-red-300">{chatError}</p>}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <form onSubmit={handleSubmit} className="flex gap-2 border-t border-white/10 p-3">
                <label className="sr-only" htmlFor="companion-input">Ask a question</label>
                <Input
                  id="companion-input"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder={isReady ? "Ask anything..." : "Prepare a video first"}
                  disabled={!isReady || isSending}
                  autoComplete="off"
                  className="h-9 flex-1 rounded-xl bg-black/30 text-sm"
                />
                <Button type="submit" size="icon" disabled={!isReady || isSending || !message.trim()} aria-label="Send" className="size-9 shrink-0 rounded-xl">
                  <Send className="size-4" />
                </Button>
              </form>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </>
  );
}
