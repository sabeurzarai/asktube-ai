"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { BrainCircuit, Play } from "lucide-react";

import { searchVideos, type VideoDurationFilter, type YouTubeVideo } from "@/lib/api";

import { AboutSection } from "@/components/landing/about-section";
import { AIWorkspace } from "@/components/landing/ai-workspace";
import { ProcessingScreen } from "@/components/landing/processing-screen";
import { SearchConsole } from "@/components/landing/search-console";
import { VideoCarousel } from "@/components/landing/video-carousel";
import { FloatingCompanion } from "@/components/floating-companion";
import { pageTransition, smoothEase, staggerContainer, subtleItemReveal } from "@/lib/motion";

const journeySteps = [
  "Search by voice or text",
  "Choose a transcript-ready video",
  "Let AI prepare the evidence",
  "Ask and jump to cited moments"
];

export type JourneyStep =
  | "idle"
  | "searching"
  | "videos_ready"
  | "video_selected"
  | "processing"
  | "ready";

export function CinematicHero() {
  const [searchResults, setSearchResults] = useState<YouTubeVideo[]>([]);
  const [searchStatus, setSearchStatus] = useState<"idle" | "loading" | "ready" | "error" | "empty">("idle");
  const [selectedVideo, setSelectedVideo] = useState<YouTubeVideo | null>(null);
  const [videoReady, setVideoReady] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const journeyStep: JourneyStep = videoReady
    ? "ready"
    : isProcessing
    ? "processing"
    : selectedVideo
    ? "video_selected"
    : searchStatus === "ready"
    ? "videos_ready"
    : searchStatus === "loading"
    ? "searching"
    : "idle";

  async function handleSearch(query: string, durationFilter: VideoDurationFilter) {
    setSearchStatus("loading");
    setSearchResults([]);
    try {
      const data = await searchVideos(query, 10, durationFilter);
      setSearchResults(data.videos);
      setSearchStatus(data.videos.length === 0 ? "empty" : "ready");
      if (data.videos.length > 0) {
        setTimeout(() => {
          document.getElementById("trending")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }, 400);
      }
    } catch (err) {
      setSearchStatus("error");
      // Rethrow so SearchConsole can show its own error state
      throw err;
    }
  }

  return (
    <motion.main
      initial={{ opacity: 1, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={pageTransition}
      className="relative isolate min-h-dvh overflow-x-hidden bg-[#05070d] text-white"
    >
      <div className="absolute inset-0 -z-20 bg-cinema-radial" />
      <div className="absolute inset-0 -z-20 bg-[linear-gradient(to_bottom,rgba(5,7,13,.08),#070A12_82%,#03050a)]" />
      <div className="absolute inset-0 -z-10 bg-[linear-gradient(rgba(255,255,255,.025)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.025)_1px,transparent_1px)] bg-[size:72px_72px] opacity-35" />
      <div className="absolute left-1/2 top-0 -z-10 h-[32rem] w-[32rem] -translate-x-1/2 rounded-full bg-cyan-400/10 blur-3xl" />
      <div className="absolute bottom-[-18rem] right-[-10rem] -z-10 h-[34rem] w-[34rem] rounded-full bg-pink-600/20 blur-3xl" />

      <nav
        aria-label="Main navigation"
        className="mx-auto flex w-full max-w-7xl items-center justify-between gap-3 px-5 py-5 sm:px-8 lg:py-6"
      >
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          className="flex items-center gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:rounded-xl"
          aria-label="AskTube AI - scroll to top"
        >
          <div className="grid size-10 place-items-center rounded-2xl border border-pink-300/25 bg-pink-500/14 shadow-glow-pink backdrop-blur-xl">
            <Play aria-hidden="true" className="size-4 fill-white text-white" />
          </div>
          <span className="text-sm font-bold text-white sm:text-base">
            AskTube AI
          </span>
        </button>
        <div
          role="list"
          className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.055] p-1 text-sm text-slate-300 shadow-[inset_0_1px_0_rgba(255,255,255,.07)] backdrop-blur-xl md:flex"
        >
          {[
            { label: "Home", target: "main-content" },
            { label: "Trending", target: "trending" },
            { label: "Workspace", target: "workspace" },
            { label: "About", target: "about" },
          ].map(({ label, target }, index) => (
            <button
              key={label}
              type="button"
              role="listitem"
              aria-current={index === 0 ? "page" : undefined}
              onClick={() => {
                if (!target) return;
                const el = document.getElementById(target);
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
                else window.scrollTo({ top: 0, behavior: "smooth" });
              }}
              className="rounded-full px-4 py-2 transition duration-200 hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
            >
              {label}
            </button>
          ))}
        </div>

      </nav>

      <section
        id="main-content"
        aria-labelledby="hero-heading"
        className="mx-auto flex w-full max-w-7xl flex-col items-center overflow-x-hidden px-5 pb-16 pt-8 text-center sm:px-8 sm:pt-14 lg:pb-24"
      >
        <motion.div
          initial={{ opacity: 1, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, ease: smoothEase }}
          className="inline-flex max-w-full items-center gap-2 rounded-full border border-cyan-200/15 bg-cyan-200/[0.075] px-3 py-2 text-center text-xs font-medium text-cyan-50 shadow-glow backdrop-blur-xl sm:px-4 sm:text-sm"
        >
          <BrainCircuit aria-hidden="true" className="size-4 shrink-0" />
          <span className="truncate">Transcript-grounded YouTube intelligence</span>
        </motion.div>

        <motion.h1
          initial={{ opacity: 1, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.12, duration: 0.8, ease: smoothEase }}
          id="hero-heading"
          className="mt-7 max-w-[22rem] text-balance text-3xl font-black leading-[1.08] text-white sm:max-w-4xl sm:text-5xl md:text-6xl lg:text-[4.75rem]"
        >
          Search, understand, and chat with YouTube videos.
        </motion.h1>

        <motion.p
          initial={{ opacity: 1, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.24, duration: 0.7, ease: smoothEase }}
          className="mt-6 max-w-[22rem] text-pretty text-base leading-8 text-slate-300 sm:max-w-2xl sm:text-lg"
        >
          Turn long videos into cinematic learning sessions with voice search,
          transcript-only AI answers, summaries, and clickable timestamp citations.
        </motion.p>

        <motion.ol
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
          aria-label="AskTube learning journey"
          className="mt-7 grid w-full max-w-4xl list-none gap-2 rounded-[1.5rem] border border-white/10 bg-white/[0.045] p-2 text-left shadow-[inset_0_1px_0_rgba(255,255,255,.05)] backdrop-blur-xl sm:grid-cols-2 lg:grid-cols-4"
        >
          {journeySteps.map((step, index) => (
            <motion.li
              key={step}
              variants={subtleItemReveal}
              className="flex min-h-14 items-center gap-3 rounded-[1.1rem] border border-white/10 bg-black/20 px-3 py-2"
            >
              <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-full bg-white text-xs font-black text-black">
                {index + 1}
              </span>
              <span className="text-sm font-medium leading-5 text-slate-200">{step}</span>
            </motion.li>
          ))}
        </motion.ol>

        <SearchConsole onSearch={handleSearch} externalSearchState={searchStatus} />

        <motion.div
          initial={{ opacity: 1, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.8, ease: smoothEase }}
          className="mt-12 grid w-full max-w-full gap-5 sm:gap-6"
        >
          <VideoCarousel
            videos={searchResults}
            isLoading={searchStatus === "loading"}
            onSelectVideo={(video) => {
              setSelectedVideo(video);
              setTimeout(() => {
                document.getElementById("processing")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }, 200);
            }}
          />
          <ProcessingScreen
            selectedVideo={selectedVideo}
            onStart={() => setIsProcessing(true)}
            onComplete={() => { setIsProcessing(false); setVideoReady(true); }}
          />
          <AIWorkspace selectedVideo={selectedVideo} />
          <AboutSection />

        </motion.div>
      </section>

      <FloatingCompanion
        isReady={videoReady}
        selectedVideo={selectedVideo}
        journeyStep={journeyStep}
      />
    </motion.main>
  );
}
