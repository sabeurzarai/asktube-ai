"use client";

import { motion } from "framer-motion";
import { BrainCircuit, Database, MessageSquareText, Play, Search, Sparkles, Youtube, Zap } from "lucide-react";

import { sectionReveal, sectionViewport, smoothEase, staggerContainer, subtleItemReveal } from "@/lib/motion";

const steps = [
  {
    icon: Search,
    title: "Search",
    description: "Type a topic or speak it. AskTube queries YouTube and returns curated, embeddable videos.",
  },
  {
    icon: Play,
    title: "Pick a video",
    description: "Browse results in the carousel and select the video you want to learn from.",
  },
  {
    icon: Zap,
    title: "Prepare",
    description: "The backend extracts the full transcript, splits it into chunks, and indexes it in ChromaDB.",
  },
  {
    icon: MessageSquareText,
    title: "Ask anything",
    description: "Chat with the video. Every answer is grounded in the transcript and links back to exact timestamps.",
  },
];

const stack = [
  { label: "Next.js 14", color: "border-white/20 text-slate-200" },
  { label: "FastAPI", color: "border-cyan-300/30 text-cyan-200" },
  { label: "LangChain", color: "border-purple-300/30 text-purple-200" },
  { label: "ChromaDB", color: "border-pink-300/30 text-pink-200" },
  { label: "OpenAI", color: "border-emerald-300/30 text-emerald-200" },
  { label: "Whisper", color: "border-yellow-300/30 text-yellow-200" },
  { label: "Docker", color: "border-sky-300/30 text-sky-200" },
  { label: "Webshare Proxy", color: "border-orange-300/30 text-orange-200" },
];

export function AboutSection() {
  return (
    <motion.section
      id="about"
      aria-labelledby="about-heading"
      style={{ scrollMarginTop: "1.5rem" }}
      variants={sectionReveal}
      initial="hidden"
      whileInView="visible"
      viewport={sectionViewport}
      className="relative overflow-hidden rounded-[1.75rem] border border-white/10 bg-white/[0.04] p-6 text-left shadow-cinema-card backdrop-blur-2xl sm:p-8 lg:p-10"
    >
      {/* Ambient glows */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_80%,rgba(34,211,238,.12),transparent_35%),radial-gradient(circle_at_88%_15%,rgba(168,85,247,.14),transparent_35%)]" />
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-purple-300/50 to-transparent" />

      {/* Header */}
      <motion.div
        initial={{ opacity: 1, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={sectionViewport}
        transition={{ duration: 0.6, ease: smoothEase }}
        className="relative flex flex-col items-start gap-4 sm:flex-row sm:items-center sm:gap-5"
      >
        <div className="grid size-12 shrink-0 place-items-center rounded-2xl border border-purple-300/25 bg-purple-500/15 shadow-[0_0_24px_rgba(168,85,247,.25)] backdrop-blur-xl">
          <BrainCircuit aria-hidden="true" className="size-6 text-purple-200" />
        </div>
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-purple-300">
            About
          </p>
          <h2
            id="about-heading"
            className="mt-0.5 text-2xl font-black leading-tight text-white sm:text-3xl"
          >
            AskTube AI
          </h2>
        </div>
      </motion.div>

      {/* Pitch */}
      <motion.p
        initial={{ opacity: 1, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={sectionViewport}
        transition={{ delay: 0.1, duration: 0.6, ease: smoothEase }}
        className="relative mt-6 max-w-2xl text-base leading-8 text-slate-300 sm:text-lg"
      >
        AskTube AI turns any YouTube video into an interactive learning session.
        Instead of watching passively, you search by voice or text, let the AI
        index the transcript, and chat with the content — every answer is
        grounded in the source and links back to the exact moment in the video.
      </motion.p>

      {/* How it works */}
      <div className="relative mt-10">
        <motion.p
          initial={{ opacity: 1, y: 8 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={sectionViewport}
          transition={{ delay: 0.15, duration: 0.5, ease: smoothEase }}
          className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300"
        >
          How it works
        </motion.p>
        <motion.ol
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={sectionViewport}
          className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        >
          {steps.map((step, index) => (
            <motion.li
              key={step.title}
              variants={subtleItemReveal}
              className="flex flex-col gap-3 rounded-[1.25rem] border border-white/10 bg-black/25 p-4 shadow-[inset_0_1px_0_rgba(255,255,255,.06)]"
            >
              <div className="flex items-center gap-3">
                <span
                  aria-hidden="true"
                  className="grid size-7 shrink-0 place-items-center rounded-full bg-white text-xs font-black text-black"
                >
                  {index + 1}
                </span>
                <step.icon aria-hidden="true" className="size-4 text-cyan-300" />
                <span className="text-sm font-bold text-white">{step.title}</span>
              </div>
              <p className="text-sm leading-6 text-slate-400">{step.description}</p>
            </motion.li>
          ))}
        </motion.ol>
      </div>

      {/* Tech stack */}
      <div className="relative mt-10">
        <motion.p
          initial={{ opacity: 1, y: 8 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={sectionViewport}
          transition={{ delay: 0.2, duration: 0.5, ease: smoothEase }}
          className="mb-4 text-xs font-semibold uppercase tracking-[0.22em] text-slate-400"
        >
          Built with
        </motion.p>
        <motion.ul
          variants={staggerContainer}
          initial="hidden"
          whileInView="visible"
          viewport={sectionViewport}
          className="flex flex-wrap gap-2"
        >
          {stack.map((item) => (
            <motion.li
              key={item.label}
              variants={subtleItemReveal}
              className={`rounded-full border px-3.5 py-1.5 text-xs font-semibold backdrop-blur-sm ${item.color} bg-white/[0.04]`}
            >
              {item.label}
            </motion.li>
          ))}
        </motion.ul>
      </div>

      {/* Credits */}
      <motion.div
        initial={{ opacity: 1, y: 8 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={sectionViewport}
        transition={{ delay: 0.25, duration: 0.5, ease: smoothEase }}
        className="relative mt-10 flex flex-col gap-1 border-t border-white/[0.07] pt-6 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between"
      >
        <span>
          Built by <span className="font-semibold text-slate-300">Sabeur Zarai</span>
          {" · "}
          <span className="text-slate-400">IronHack Final Project · 2026</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Youtube aria-hidden="true" className="size-3.5 text-red-400" />
          <span>Powered by YouTube Data API v3</span>
          <Sparkles aria-hidden="true" className="size-3.5 text-cyan-400" />
          <span>OpenAI</span>
          <Database aria-hidden="true" className="size-3.5 text-purple-400" />
          <span>ChromaDB</span>
        </span>
      </motion.div>
    </motion.section>
  );
}
