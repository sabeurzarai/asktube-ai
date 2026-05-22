"use client";

import { useEffect, useRef, useState } from "react";
import { Environment, Float, PerspectiveCamera } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { motion, useReducedMotion, AnimatePresence } from "framer-motion";
import { ArrowDown, Bot, Mic } from "lucide-react";
import * as THREE from "three";

import { Button } from "@/components/ui/button";
import { sectionReveal, sectionViewport, smoothEase } from "@/lib/motion";

// -- Cute robot built from Three.js primitives ---------------------------------

function CuteRobot({ isReady, paused }: { isReady: boolean; paused: boolean }) {
  const groupRef = useRef<THREE.Group>(null);
  const headRef = useRef<THREE.Group>(null);
  const leftEyeRef = useRef<THREE.Mesh>(null);
  const rightEyeRef = useRef<THREE.Mesh>(null);
  const waveArmRef = useRef<THREE.Group>(null);
  const antennaGlowRef = useRef<THREE.Mesh>(null);

  // Fly-in state: robot starts far back, flies to origin when isReady
  const flyProgress = useRef(isReady ? 1 : 0);
  const arrived = useRef(isReady);

  useFrame(({ clock }) => {
    if (paused) return;
    const t = clock.elapsedTime;

    // Fly-in animation
    if (isReady && flyProgress.current < 1) {
      flyProgress.current = Math.min(flyProgress.current + 0.012, 1);
      arrived.current = flyProgress.current >= 1;
    }

    const ease = easeOutCubic(flyProgress.current);

    if (groupRef.current) {
      // Fly in from far above-back
      groupRef.current.position.z = THREE.MathUtils.lerp(-18, 0, ease);
      groupRef.current.position.y = THREE.MathUtils.lerp(6, 0, ease);
      groupRef.current.rotation.y = THREE.MathUtils.lerp(Math.PI, 0, ease);
      groupRef.current.scale.setScalar(THREE.MathUtils.lerp(0.1, 1, ease));

      // Idle float after arrival
      if (arrived.current) {
        groupRef.current.position.y = Math.sin(t * 1.2) * 0.12;
        groupRef.current.rotation.y = Math.sin(t * 0.6) * 0.18;
      }
    }

    // Head tilt
    if (headRef.current) {
      headRef.current.rotation.z = Math.sin(t * 0.9) * 0.06;
    }

    // Blink
    const blink = Math.sin(t * 3.5) > 0.94 ? 0.08 : 1;
    if (leftEyeRef.current) leftEyeRef.current.scale.y = blink;
    if (rightEyeRef.current) rightEyeRef.current.scale.y = blink;

    // Wave arm
    if (waveArmRef.current && arrived.current) {
      waveArmRef.current.rotation.z = 0.4 + Math.sin(t * 4) * 0.55;
    }

    // Antenna glow pulse
    if (antennaGlowRef.current) {
      const mat = antennaGlowRef.current.material as THREE.MeshStandardMaterial;
      mat.emissiveIntensity = 0.8 + Math.sin(t * 2.4) * 0.5;
    }
  });

  return (
    <group ref={groupRef} position={[0, 0, isReady ? 0 : -18]} scale={isReady ? 1 : 0.1}>
      {/* -- Head ------------------------------------------------ */}
      <group ref={headRef} position={[0, 0.55, 0]}>
        {/* Head sphere - oval, white */}
        <mesh>
          <sphereGeometry args={[0.72, 48, 48]} />
          <meshStandardMaterial
            color="#e8f4f8"
            emissive="#b8dce8"
            emissiveIntensity={0.08}
            metalness={0.2}
            roughness={0.35}
          />
        </mesh>

        {/* Black face visor panel */}
        <mesh position={[0, 0.04, 0.58]} scale={[0.82, 0.62, 1]}>
          <sphereGeometry args={[0.55, 32, 32]} />
          <meshStandardMaterial color="#0a0e1a" roughness={0.15} metalness={0.6} />
        </mesh>

        {/* Left eye (large, cute) */}
        <mesh ref={leftEyeRef} position={[-0.2, 0.08, 0.88]}>
          <sphereGeometry args={[0.12, 24, 24]} />
          <meshStandardMaterial color="#050a14" roughness={0.1} />
        </mesh>
        {/* Left eye highlight */}
        <mesh position={[-0.15, 0.14, 0.94]}>
          <sphereGeometry args={[0.035, 12, 12]} />
          <meshStandardMaterial color="#ffffff" roughness={0} />
        </mesh>

        {/* Right eye */}
        <mesh ref={rightEyeRef} position={[0.2, 0.08, 0.88]}>
          <sphereGeometry args={[0.12, 24, 24]} />
          <meshStandardMaterial color="#050a14" roughness={0.1} />
        </mesh>
        {/* Right eye highlight */}
        <mesh position={[0.25, 0.14, 0.94]}>
          <sphereGeometry args={[0.035, 12, 12]} />
          <meshStandardMaterial color="#ffffff" roughness={0} />
        </mesh>

        {/* Smile - torus arc */}
        <mesh position={[0, -0.14, 0.9]} rotation={[0, 0, 0]}>
          <torusGeometry args={[0.14, 0.022, 12, 24, Math.PI]} />
          <meshStandardMaterial color="#050a14" roughness={0.2} />
        </mesh>

        {/* Blue forehead glow circle */}
        <mesh position={[0, 0.54, 0.62]}>
          <circleGeometry args={[0.1, 32]} />
          <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={1.2} />
        </mesh>

        {/* Ear disc left */}
        <mesh position={[-0.73, 0.08, 0.05]} rotation={[0, Math.PI / 2, 0]}>
          <cylinderGeometry args={[0.18, 0.18, 0.09, 24]} />
          <meshStandardMaterial color="#c8dde8" metalness={0.4} roughness={0.3} />
        </mesh>
        {/* Ear blue accent left */}
        <mesh position={[-0.78, 0.08, 0.05]} rotation={[0, Math.PI / 2, 0]}>
          <circleGeometry args={[0.1, 24]} />
          <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={0.9} />
        </mesh>

        {/* Ear disc right */}
        <mesh position={[0.73, 0.08, 0.05]} rotation={[0, Math.PI / 2, 0]}>
          <cylinderGeometry args={[0.18, 0.18, 0.09, 24]} />
          <meshStandardMaterial color="#c8dde8" metalness={0.4} roughness={0.3} />
        </mesh>

        {/* Antenna stick */}
        <mesh position={[0, 0.88, 0]}>
          <cylinderGeometry args={[0.025, 0.025, 0.38, 12]} />
          <meshStandardMaterial color="#c8dde8" metalness={0.5} roughness={0.3} />
        </mesh>
        {/* Antenna glow ball */}
        <mesh ref={antennaGlowRef} position={[0, 1.1, 0]}>
          <sphereGeometry args={[0.08, 24, 24]} />
          <meshStandardMaterial
            color="#22d3ee"
            emissive="#22d3ee"
            emissiveIntensity={1.2}
            metalness={0}
            roughness={0.1}
          />
        </mesh>
      </group>

      {/* -- Neck ------------------------------------------------ */}
      <mesh position={[0, 0, 0]}>
        <cylinderGeometry args={[0.15, 0.2, 0.22, 16]} />
        <meshStandardMaterial color="#1a2535" metalness={0.7} roughness={0.25} />
      </mesh>

      {/* -- Body ------------------------------------------------ */}
      <mesh position={[0, -0.54, 0]}>
        <capsuleGeometry args={[0.42, 0.55, 16, 24]} />
        <meshStandardMaterial
          color="#ddeef5"
          emissive="#b8d8e8"
          emissiveIntensity={0.04}
          metalness={0.2}
          roughness={0.38}
        />
      </mesh>

      {/* Body blue accent strip */}
      <mesh position={[0, -0.44, 0.42]}>
        <boxGeometry args={[0.28, 0.06, 0.02]} />
        <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={0.8} />
      </mesh>

      {/* Body button dots */}
      {[-0.08, 0, 0.08].map((x, i) => (
        <mesh key={i} position={[x, -0.56, 0.43]}>
          <sphereGeometry args={[0.025, 12, 12]} />
          <meshStandardMaterial
            color={i === 1 ? "#22d3ee" : "#e8f4f8"}
            emissive={i === 1 ? "#22d3ee" : "#ffffff"}
            emissiveIntensity={i === 1 ? 0.8 : 0.1}
          />
        </mesh>
      ))}

      {/* -- Left arm (waving) ----------------------------------- */}
      <group ref={waveArmRef} position={[0.58, -0.22, 0]} rotation={[0, 0, 0.4]}>
        <mesh position={[0.28, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
          <capsuleGeometry args={[0.09, 0.44, 12, 16]} />
          <meshStandardMaterial color="#ddeef5" metalness={0.2} roughness={0.35} />
        </mesh>
        {/* Hand */}
        <mesh position={[0.58, 0, 0]}>
          <sphereGeometry args={[0.12, 20, 20]} />
          <meshStandardMaterial color="#1a2535" metalness={0.65} roughness={0.2} />
        </mesh>
        {/* Finger nubs */}
        {[0, 60, 120, 180, 240].map((deg, i) => {
          const angle = (deg * Math.PI) / 180;
          return (
            <mesh
              key={i}
              position={[0.64 + Math.cos(angle) * 0.05, Math.sin(angle) * 0.06, 0]}
            >
              <sphereGeometry args={[0.035, 8, 8]} />
              <meshStandardMaterial color="#0f1822" metalness={0.7} roughness={0.15} />
            </mesh>
          );
        })}
      </group>

      {/* -- Right arm (resting) --------------------------------- */}
      <group position={[-0.58, -0.22, 0]} rotation={[0, 0, -0.3]}>
        <mesh position={[-0.26, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
          <capsuleGeometry args={[0.09, 0.4, 12, 16]} />
          <meshStandardMaterial color="#ddeef5" metalness={0.2} roughness={0.35} />
        </mesh>
        <mesh position={[-0.52, 0, 0]}>
          <sphereGeometry args={[0.12, 20, 20]} />
          <meshStandardMaterial color="#1a2535" metalness={0.65} roughness={0.2} />
        </mesh>
      </group>

      {/* -- Legs ------------------------------------------------ */}
      {/* Left leg */}
      <mesh position={[-0.22, -1.1, 0]}>
        <capsuleGeometry args={[0.14, 0.28, 12, 16]} />
        <meshStandardMaterial color="#1a2535" metalness={0.6} roughness={0.25} />
      </mesh>
      {/* Left foot */}
      <mesh position={[-0.22, -1.38, 0.06]}>
        <capsuleGeometry args={[0.13, 0.18, 12, 16]} />
        <meshStandardMaterial color="#ddeef5" metalness={0.2} roughness={0.35} />
      </mesh>

      {/* Right leg */}
      <mesh position={[0.22, -1.1, 0]}>
        <capsuleGeometry args={[0.14, 0.28, 12, 16]} />
        <meshStandardMaterial color="#1a2535" metalness={0.6} roughness={0.25} />
      </mesh>
      {/* Right foot */}
      <mesh position={[0.22, -1.38, 0.06]}>
        <capsuleGeometry args={[0.13, 0.18, 12, 16]} />
        <meshStandardMaterial color="#ddeef5" metalness={0.2} roughness={0.35} />
      </mesh>

      {/* Soft glow under robot */}
      <mesh position={[0, -1.6, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[0.9, 48]} />
        <meshBasicMaterial color="#22d3ee" transparent opacity={0.06} />
      </mesh>
    </group>
  );
}

function easeOutCubic(x: number): number {
  return 1 - Math.pow(1 - x, 3);
}

// -- Stars background ----------------------------------------------------------
function Stars({ paused }: { paused: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const count = 180;
  const positions = new Float32Array(count * 3).map(() => (Math.random() - 0.5) * 28);

  useFrame(({ clock }) => {
    if (!ref.current || paused) return;
    ref.current.rotation.y = clock.elapsedTime * 0.015;
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} count={count} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial color="#a5f3fc" size={0.04} transparent opacity={0.7} sizeAttenuation />
    </points>
  );
}

// -- Grid floor ----------------------------------------------------------------
function GridFloor({ paused }: { paused: boolean }) {
  const ref = useRef<THREE.GridHelper>(null);

  useFrame(({ clock }) => {
    if (!ref.current || paused) return;
    ref.current.position.z = (clock.elapsedTime * 0.18) % 1;
  });

  return (
    <gridHelper
      ref={ref}
      args={[12, 40, "#22d3ee", "#1f2937"]}
      position={[0, -1.75, 0]}
    />
  );
}

// -- Full 3D scene -------------------------------------------------------------
function SceneContent({ isReady, paused }: { isReady: boolean; paused: boolean }) {
  return (
    <>
      <PerspectiveCamera makeDefault position={[0, 0.5, 5.5]} fov={38} />
      <color attach="background" args={["#04060f"]} />
      <ambientLight intensity={0.5} />
      <pointLight position={[3, 4, 3]} intensity={35} color="#67e8f9" />
      <pointLight position={[-3, 2, 2]} intensity={22} color="#818cf8" />
      <spotLight position={[0, 6, 4]} angle={0.5} penumbra={0.8} intensity={20} color="#ffffff" />
      <Stars paused={paused} />
      <GridFloor paused={paused} />
      <Float speed={paused ? 0 : 1.2} rotationIntensity={0.12} floatIntensity={0.3}>
        <CuteRobot isReady={isReady} paused={paused} />
      </Float>
      <Environment preset="night" />
    </>
  );
}

// -- Main exported component ---------------------------------------------------
interface AIAssistantSceneProps {
  isReady?: boolean;
}

export function AIAssistantScene({ isReady = false }: AIAssistantSceneProps) {
  const prefersReducedMotion = useReducedMotion();
  const [hasSpoken, setHasSpoken] = useState(false);
  const [showBubble, setShowBubble] = useState(false);

  const message = "Your video is ready. Ask me anything - by typing or speaking.";

  // Speak and show bubble when isReady becomes true
  useEffect(() => {
    if (!isReady || hasSpoken) return;

    const delay = setTimeout(() => {
      setShowBubble(true);
      setHasSpoken(true);

      if (!prefersReducedMotion && "speechSynthesis" in window) {
        const utter = new SpeechSynthesisUtterance(message);
        utter.rate = 0.95;
        utter.pitch = 0.8;
        utter.volume = 0.9;
        const voices = window.speechSynthesis.getVoices();
        const maleVoice = voices.find((v) =>
          /microsoft david|microsoft mark|microsoft james|google uk english male|daniel|thomas|alex|fred/i.test(v.name)
        ) ?? voices.find((v) =>
          !/female|zira|samantha|victoria|karen|moira|fiona|tessa|siri/i.test(v.name) && v.lang.startsWith("en")
        );
        if (maleVoice) utter.voice = maleVoice;
        window.speechSynthesis.speak(utter);
      }

      // Hide bubble after 8s
      setTimeout(() => setShowBubble(false), 8000);
    }, 1800); // Wait for fly-in to mostly complete

    return () => clearTimeout(delay);
  }, [isReady, hasSpoken, prefersReducedMotion]);

  return (
    <motion.section
      id="assistant"
      aria-label="3D AI assistant - your transcript-aware tutor"
      style={{ scrollMarginTop: "1.5rem" }}
      aria-describedby="assistant-desc"
      variants={sectionReveal}
      initial="hidden"
      whileInView="visible"
      viewport={sectionViewport}
      className="premium-panel relative overflow-hidden text-left"
    >
      <div className="absolute inset-x-0 top-0 z-10 h-px bg-gradient-to-r from-transparent via-cyan-200/60 to-transparent" />

      <p id="assistant-desc" className="sr-only">
        An animated 3D AI assistant. When your video is processed, the robot flies in and announces it is ready.
      </p>

      {/* Status badge */}
      <div className="absolute right-5 top-5 z-10">
        {isReady ? (
          <span className="inline-flex items-center gap-2 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-3 py-1.5 text-xs font-semibold text-emerald-100">
            <span className="size-2 rounded-full bg-emerald-300 shadow-[0_0_12px_rgba(110,231,183,.9)] animate-pulse" />
            Ready
          </span>
        ) : (
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/30 px-3 py-1.5 text-xs font-semibold text-slate-400">
            <span className="size-2 rounded-full bg-slate-500" />
            Waiting for video
          </span>
        )}
      </div>

      {/* 3D Canvas */}
      <motion.div
        className="h-[28rem] w-full sm:h-[38rem]"
      >
        <Canvas
          dpr={[1, 1.75]}
          gl={{ antialias: true, alpha: false }}
          aria-hidden="true"
        >
          <SceneContent isReady={isReady} paused={!!prefersReducedMotion} />
        </Canvas>
      </motion.div>

      {/* Speech bubble overlay */}
      <AnimatePresence>
        {showBubble && (
          <motion.div
            initial={{ opacity: 0, y: 12, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            role="status"
            aria-live="polite"
            className="absolute left-1/2 top-[44%] z-20 w-[min(90%,26rem)] -translate-x-1/2 -translate-y-1/2"
          >
            <div className="rounded-[1.5rem] border border-cyan-200/30 bg-black/70 px-5 py-4 text-center shadow-[0_0_48px_rgba(34,211,238,.18)] backdrop-blur-xl">
              <p className="text-sm font-semibold text-white">
                {message}
              </p>
              <div className="mt-2 flex justify-center gap-1">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    animate={{ scale: [1, 1.4, 1], opacity: [0.5, 1, 0.5] }}
                    transition={{ duration: 1, repeat: Infinity, delay: i * 0.2 }}
                    className="size-1.5 rounded-full bg-cyan-300"
                  />
                ))}
              </div>
            </div>
            {/* Bubble tail */}
            <div className="mx-auto mt-1 h-3 w-3 rotate-45 rounded-sm border-b border-r border-cyan-200/30 bg-black/70" />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom CTA bar */}
      <div className="absolute bottom-4 left-4 right-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-[1.35rem] border border-white/10 bg-black/55 px-4 py-3 backdrop-blur-xl sm:bottom-5 sm:left-5 sm:right-5">
        <div>
          <h2 className="text-base font-black text-white sm:text-lg">
            {isReady ? "Your transcript-aware tutor is ready." : "Prepare a video to meet your AI tutor."}
          </h2>
          <p className="mt-0.5 text-xs text-slate-400 sm:text-sm">
            {isReady
              ? "Ask by typing or speaking. Answers come from the video transcript only."
              : "Prepare a video above - the robot will fly in when processing is done."}
          </p>
        </div>
        <div className="flex gap-2">
          {isReady && (
            <Button type="button" size="default" variant="ghost" asChild>
              <a href="#workspace">
                <Mic aria-hidden="true" className="size-4" />
                Ask now
              </a>
            </Button>
          )}
          <Button type="button" size="default" asChild>
            <a href="#workspace">
              {isReady ? "Open chat" : "Start chatting"}
              <ArrowDown aria-hidden="true" className="size-4" />
            </a>
          </Button>
        </div>
      </div>
    </motion.section>
  );
}
