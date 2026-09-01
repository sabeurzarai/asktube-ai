"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useReducedMotion } from "framer-motion";
import * as THREE from "three";

// The scene is built around the one thing that is distinctive about this
// product: time. A transcript is a track, chunks are spans on it, and a
// citation is a single moment. So the camera travels ALONG a ribbon rather than
// between floating cards, and the citation is drawn as a beam that goes back
// down to a specific second of it.
//
// Colours come from the app's own tokens (accent = blue, primary = magenta),
// not from the architecture diagram's amber/teal — this has to look like part
// of AskTube, not like a visitor from another design system.
const ACCENT = new THREE.Color("hsl(217, 91%, 60%)");
const PRIMARY = new THREE.Color("hsl(329, 84%, 60%)");
const GROUND = new THREE.Color("hsl(224, 45%, 5%)");
const RAIL = new THREE.Color("hsl(222, 47%, 14%)");

const TRACK_LENGTH = 320;
const CHUNK_COUNT = 42;
const CHUNK_SPACING = 7.2;
const CLOUD_POINTS = 900;
const CITATION_Z = -261;

/** Scroll position 0..1, read once per frame instead of on every scroll event. */
function useScrollProgress() {
  const progress = useRef(0);

  if (typeof window !== "undefined" && progress.current === 0) {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    progress.current = max > 0 ? window.scrollY / max : 0;
  }

  return progress;
}

function Timeline({ target }: { target: React.MutableRefObject<number> }) {
  const reduced = useReducedMotion();
  const eased = useRef(0);
  const chunksRef = useRef<THREE.InstancedMesh>(null);
  const cloudRef = useRef<THREE.Points>(null);
  const beamRef = useRef<THREE.Mesh>(null);
  const anchorRef = useRef<THREE.Mesh>(null);

  // Second marks along the ribbon. Time is the subject, so it is drawn.
  const tickGeometry = useMemo(() => {
    const points: number[] = [];
    for (let z = 0; z < TRACK_LENGTH; z += 1.25) {
      const half = Math.abs(z % 10) < 0.01 ? 3.2 : 1.5;
      points.push(-half, 0.01, -z, half, 0.01, -z);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    return geometry;
  }, []);

  const cloudGeometry = useMemo(() => {
    const positions = new Float32Array(CLOUD_POINTS * 3);
    for (let i = 0; i < CLOUD_POINTS; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 26;
      positions[i * 3 + 1] = 3 + Math.random() * 11;
      positions[i * 3 + 2] = -Math.random() * TRACK_LENGTH;
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    return geometry;
  }, []);

  // One InstancedMesh instead of 42 meshes: same picture, one draw call.
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const chunkColor = useMemo(() => new THREE.Color(), []);

  useFrame((state, delta) => {
    const max =
      document.documentElement.scrollHeight - window.innerHeight;
    target.current = max > 0 ? window.scrollY / max : 0;

    eased.current = reduced
      ? target.current
      : eased.current + (target.current - eased.current) * Math.min(delta * 3.2, 1);

    const p = eased.current;
    const z = 8 - p * 268;
    const sway = Math.sin(p * 2.1) * 2.6;

    state.camera.position.set(sway, 4.6 + Math.sin(p * 3.4) * 0.7, z);
    state.camera.lookAt(sway * 0.45, 1.4, z - 26);

    // A chunk brightens as the camera reaches it: retrieval, made visible.
    const chunks = chunksRef.current;
    if (chunks) {
      for (let i = 0; i < CHUNK_COUNT; i++) {
        const chunkZ = -4 - i * CHUNK_SPACING;
        dummy.position.set(0, 0.18, chunkZ);
        dummy.updateMatrix();
        chunks.setMatrixAt(i, dummy.matrix);

        const distance = Math.abs(chunkZ - (z - 30));
        const lit = Math.max(0, 1 - distance / 26) ** 2;
        chunkColor.copy(RAIL).lerp(ACCENT, lit * 0.9);
        chunks.setColorAt(i, chunkColor);
      }
      chunks.instanceMatrix.needsUpdate = true;
      if (chunks.instanceColor) chunks.instanceColor.needsUpdate = true;
    }

    if (cloudRef.current && !reduced) cloudRef.current.rotation.y = p * 0.35;

    // The beam only exists once there is an answer to attach it to.
    const cited = Math.min(1, Math.max(0, (p - 0.68) / 0.16));
    const beamMaterial = beamRef.current?.material as THREE.MeshBasicMaterial | undefined;
    if (beamMaterial) beamMaterial.opacity = cited * 0.55;
    const anchorMaterial = anchorRef.current?.material as THREE.MeshBasicMaterial | undefined;
    if (anchorMaterial) anchorMaterial.opacity = cited * 0.75;
    if (anchorRef.current) anchorRef.current.scale.setScalar(1 + (1 - cited) * 0.6);
  });

  return (
    <>
      <color attach="background" args={[GROUND]} />
      <fog attach="fog" args={[GROUND.getHex(), 26, 92]} />

      <ambientLight intensity={1.1} color="hsl(222, 40%, 40%)" />
      <directionalLight position={[6, 12, 4]} intensity={1.6} color="#ffffff" />
      <directionalLight position={[-8, 4, -20]} intensity={0.9} color={PRIMARY} />

      {/* the transcript itself */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -TRACK_LENGTH / 2]}>
        <planeGeometry args={[7, TRACK_LENGTH, 1, 220]} />
        <meshBasicMaterial color={RAIL} transparent opacity={0.85} />
      </mesh>

      <lineSegments geometry={tickGeometry}>
        <lineBasicMaterial color="hsl(222, 40%, 26%)" transparent opacity={0.55} />
      </lineSegments>

      {/* chunks: spans on the track */}
      <instancedMesh ref={chunksRef} args={[undefined, undefined, CHUNK_COUNT]}>
        <boxGeometry args={[6.2, 0.32, 3.1]} />
        <meshStandardMaterial roughness={0.55} metalness={0.1} />
      </instancedMesh>

      {/* embeddings, lifted off the timeline */}
      <points ref={cloudRef} geometry={cloudGeometry}>
        <pointsMaterial color={ACCENT} size={0.09} transparent opacity={0.5} sizeAttenuation />
      </points>

      {/* the citation: a cylinder, not a Line — WebGL ignores linewidth, so a
          Line renders one pixel wide and reads as an artefact. */}
      <mesh ref={beamRef} position={[0, 4.7, CITATION_Z]}>
        <cylinderGeometry args={[0.055, 0.16, 8.8, 12, 1, true]} />
        <meshBasicMaterial color={PRIMARY} transparent opacity={0} />
      </mesh>
      <mesh ref={anchorRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.35, CITATION_Z]}>
        <ringGeometry args={[1.7, 2.15, 56]} />
        <meshBasicMaterial color={PRIMARY} transparent opacity={0} side={THREE.DoubleSide} />
      </mesh>
    </>
  );
}

export function TranscriptTimelineScene() {
  const progress = useScrollProgress();

  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
      <Canvas
        camera={{ fov: 46, near: 0.1, far: 400, position: [0, 4.6, 8] }}
        dpr={[1, 2]}
        gl={{ antialias: true }}
      >
        <Timeline target={progress} />
      </Canvas>
      {/* Keeps the copy legible wherever the scene is bright. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "linear-gradient(90deg, hsl(224 45% 5% / 0.96) 0%, hsl(224 45% 5% / 0.9) 30%, hsl(224 45% 5% / 0.55) 50%, hsl(224 45% 5% / 0) 74%), radial-gradient(120% 80% at 70% 50%, hsl(224 45% 5% / 0) 40%, hsl(224 45% 5% / 0.75) 100%)",
        }}
      />
    </div>
  );
}
