"use client";

import { useCallback, useEffect, useState } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { motion } from "framer-motion";
import {
  ArrowDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Play,
  Subtitles
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, VideoSkeletonGrid } from "@/components/ui/feedback-states";
import { type YouTubeVideo, decodeHtml, formatDuration } from "@/lib/api";
import { trackAnalyticsEvent } from "@/lib/analytics";
import { cn } from "@/lib/utils";
import { sectionReveal, sectionViewport, smoothEase, springMotion } from "@/lib/motion";

const CARD_GRADIENTS = [
  "from-red-500/80 via-fuchsia-500/45 to-cyan-400/35",
  "from-cyan-300/70 via-blue-700/55 to-violet-500/45",
  "from-emerald-300/65 via-cyan-500/35 to-red-500/55",
  "from-purple-400/70 via-indigo-500/45 to-cyan-300/35",
  "from-lime-300/60 via-emerald-500/35 to-sky-500/45",
  "from-orange-400/65 via-red-600/45 to-purple-500/45"
];

const DEMO_VIDEOS: YouTubeVideo[] = [
  {
    video_id: "demo-1",
    title: "Deep Work in the AI Era",
    description: "Focus systems, attention rituals, and how to learn without noise.",
    channel_id: "",
    channel_title: "Productivity",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 1122,
    youtube_url: "#"
  },
  {
    video_id: "demo-2",
    title: "Black Holes Explained",
    description: "A cinematic tour through gravity, event horizons, and spacetime.",
    channel_id: "",
    channel_title: "Science",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 1449,
    youtube_url: "#"
  },
  {
    video_id: "demo-3",
    title: "Muscle Growth Nutrition",
    description: "Protein ranges, meal timing, and evidence-backed training fuel.",
    channel_id: "",
    channel_title: "Health",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 808,
    youtube_url: "#"
  },
  {
    video_id: "demo-4",
    title: "Anxiety Tools That Work",
    description: "Mental models, grounding techniques, and practical coping steps.",
    channel_id: "",
    channel_title: "Psychology",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 1864,
    youtube_url: "#"
  },
  {
    video_id: "demo-5",
    title: "Football Tactics Lab",
    description: "Pressing triggers, midfield overloads, and smart build-up patterns.",
    channel_id: "",
    channel_title: "Sports",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 1277,
    youtube_url: "#"
  },
  {
    video_id: "demo-6",
    title: "AI Agents for Beginners",
    description: "Tools, memory, planning loops, and the agent architecture basics.",
    channel_id: "",
    channel_title: "Education",
    published_at: "",
    thumbnail_url: null,
    duration_seconds: 1015,
    youtube_url: "#"
  }
];

interface VideoCarouselProps {
  videos?: YouTubeVideo[];
  isLoading?: boolean;
  hasError?: boolean;
  onRetry?: () => void;
  onSelectVideo?: (video: YouTubeVideo) => void;
}

export function VideoCarousel({ videos, isLoading, hasError, onRetry, onSelectVideo }: VideoCarouselProps) {
  const displayVideos = videos && videos.length > 0 ? videos : DEMO_VIDEOS;
  const isDemo = !videos || videos.length === 0;

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isCompactViewport, setIsCompactViewport] = useState(false);
  const [emblaRef, emblaApi] = useEmblaCarousel({
    align: "center",
    containScroll: "trimSnaps",
    dragFree: false,
    loop: true,
    skipSnaps: false
  });

  const updateSelection = useCallback(() => {
    if (!emblaApi) return;
    const index = emblaApi.selectedScrollSnap();
    setSelectedIndex(index);
    trackAnalyticsEvent("carousel_scrolled", {
      selected_index: index,
      slide_count: displayVideos.length,
      selected_video_id: displayVideos[index]?.video_id,
    });
  }, [displayVideos, emblaApi]);

  const selectVideo = useCallback((video: YouTubeVideo) => {
    trackAnalyticsEvent("center_card_selection_rate", {
      video_id: video.video_id,
      selected_index: selectedIndex,
      is_center_card: displayVideos[selectedIndex]?.video_id === video.video_id,
    });
    onSelectVideo?.(video);
  }, [displayVideos, onSelectVideo, selectedIndex]);

  // Reset to first slide when videos change
  useEffect(() => {
    setSelectedIndex(0);
    emblaApi?.scrollTo(0, true);
  }, [displayVideos, emblaApi]);

  useEffect(() => {
    const updateViewport = () => setIsCompactViewport(window.innerWidth < 640);
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  useEffect(() => {
    if (!emblaApi) return;
    updateSelection();
    emblaApi.on("select", updateSelection);
    emblaApi.on("reInit", updateSelection);
    return () => {
      emblaApi.off("select", updateSelection);
      emblaApi.off("reInit", updateSelection);
    };
  }, [emblaApi, updateSelection]);

  return (
    <motion.section
      id="trending"
      aria-label="Featured learning videos"
      style={{ scrollMarginTop: "1.5rem" }}
      variants={sectionReveal}
      initial="hidden"
      whileInView="visible"
      viewport={sectionViewport}
      className="premium-panel relative overflow-hidden px-0 py-5 text-left"
    >
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-200/60 to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-[#0b0f19]/90 to-transparent sm:w-24" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-[#0b0f19]/90 to-transparent sm:w-24" />

      <div className="mb-5 flex items-center justify-between gap-4 px-5 sm:px-6 lg:px-7">
        <div>
          <h2 className="text-lg font-black text-white sm:text-2xl">
            {isDemo
              ? "Choose the video you want to understand."
              : `${displayVideos.length} video${displayVideos.length !== 1 ? "s" : ""} found - pick one to explore.`}
          </h2>
          <p className="mt-2 max-w-xl text-sm leading-6 text-slate-400">
            Swipe or use the arrows. The centered card is ready to open in the AI workspace.
          </p>
        </div>

        <div className="flex gap-2">
          <motion.div whileTap={{ scale: 0.94 }}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Previous video"
              onClick={() => emblaApi?.scrollPrev()}
              disabled={!emblaApi}
              className="relative z-20"
            >
              <ChevronLeft aria-hidden="true" className="size-5" />
            </Button>
          </motion.div>
          <motion.div whileTap={{ scale: 0.94 }}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Next video"
              onClick={() => emblaApi?.scrollNext()}
              disabled={!emblaApi}
              className="relative z-20"
            >
              <ChevronRight aria-hidden="true" className="size-5" />
            </Button>
          </motion.div>
        </div>
      </div>

      {isLoading ? (
        <div aria-busy="true" aria-live="polite">
          <VideoSkeletonGrid />
        </div>
      ) : hasError ? (
        <div className="px-5 sm:px-6 lg:px-7">
          <ErrorState
            title="Video discovery failed"
            description="AskTube could not fetch videos right now. Retry the discovery request."
            retryLabel="Reload videos"
            onRetry={onRetry}
          />
        </div>
      ) : (
        <>
          {/* Live region announces slide changes */}
          <div aria-live="polite" aria-atomic="true" className="sr-only">
            {displayVideos[selectedIndex]?.title}, slide {selectedIndex + 1} of {displayVideos.length}
          </div>

          <div
            ref={emblaRef}
            className="overflow-hidden"
            role="region"
            aria-label="Learning videos carousel"
            aria-roledescription="carousel"
          >
            <div className="flex touch-pan-y py-7">
              {displayVideos.map((video, index) => {
                const isSelected = selectedIndex === index;
                const selectedScale = isCompactViewport ? 1.01 : 1.08;
                const restingScale = isCompactViewport ? 0.92 : 0.9;
                const hoverSelectedScale = isCompactViewport ? 1.03 : 1.11;
                const hoverRestingScale = isCompactViewport ? 0.94 : 0.96;
                const gradient = CARD_GRADIENTS[index % CARD_GRADIENTS.length];

                return (
                  <div
                    key={video.video_id}
                    role="group"
                    aria-roledescription="slide"
                    aria-label={`${video.title}, ${index + 1} of ${displayVideos.length}`}
                    className="min-w-0 flex-[0_0_82%] px-2 min-[420px]:flex-[0_0_76%] sm:flex-[0_0_48%] lg:flex-[0_0_34%] xl:flex-[0_0_30%]"
                  >
                    <motion.article
                      layout
                      animate={{
                        scale: isSelected ? selectedScale : restingScale,
                        opacity: isSelected ? 1 : 0.48,
                        y: isSelected ? -8 : 8
                      }}
                      whileHover={{
                        scale: isSelected ? hoverSelectedScale : hoverRestingScale,
                        opacity: 1,
                        y: isSelected ? -12 : 0
                      }}
                      transition={springMotion}
                      className={cn(
                        "group relative min-h-[20.5rem] overflow-hidden rounded-[1.5rem] border bg-black/38 p-4 shadow-cinema-card outline-none backdrop-blur-xl transition-colors duration-300 sm:min-h-[22rem]",
                        isSelected
                          ? "border-cyan-200/40 shadow-[0_0_82px_rgba(34,211,238,.22),0_30px_110px_rgba(0,0,0,.52)]"
                          : "border-white/10 hover:border-white/25"
                      )}
                    >
                      {/* Thumbnail */}
                      <div
                        className={cn(
                          "relative aspect-video overflow-hidden rounded-[1.1rem] bg-gradient-to-br shadow-[inset_0_-30px_80px_rgba(0,0,0,.32)]",
                          gradient
                        )}
                      >
                        {video.thumbnail_url ? (
                          <img
                            src={video.thumbnail_url}
                            alt=""
                            aria-hidden="true"
                            className="absolute inset-0 h-full w-full object-cover"
                          />
                        ) : null}
                        <div className="absolute inset-0 bg-[radial-gradient(circle_at_72%_22%,rgba(255,255,255,.55),transparent_18%),linear-gradient(to_top,rgba(0,0,0,.64),transparent_62%)]" />
                        <div className="absolute left-4 top-4 rounded-full border border-white/20 bg-black/40 px-3 py-1 text-xs font-semibold text-white backdrop-blur-xl">
                          {video.channel_title}
                        </div>
                        <motion.button
                          type="button"
                          aria-label={`Select ${video.title}`}
                          onClick={() => selectVideo(video)}
                          whileHover={{ scale: 1.08 }}
                          whileTap={{ scale: 0.94 }}
                          transition={{ type: "spring", stiffness: 340, damping: 22 }}
                          className="absolute left-1/2 top-1/2 grid size-14 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-white/25 bg-white/20 text-white shadow-[0_0_50px_rgba(255,255,255,.24)] backdrop-blur-xl transition duration-200 hover:scale-105 hover:bg-white/30 active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
                        >
                          <Play aria-hidden="true" className="ml-1 size-5 fill-white" />
                        </motion.button>
                      </div>

                      <div className="mt-5">
                        <div className="flex flex-wrap gap-2 text-xs text-slate-300">
                          <span className="glass-chip px-2.5 py-1">
                            <Clock3 aria-hidden="true" className="size-3.5 text-cyan-100" />
                            {formatDuration(video.duration_seconds)}
                          </span>
                          <span className="glass-chip px-2.5 py-1">
                            <Subtitles aria-hidden="true" className="size-3.5 text-red-100" />
                            Transcript ready
                          </span>
                        </div>

                        <h3 className="mt-4 text-xl font-black leading-tight text-white">
                          {decodeHtml(video.title)}
                        </h3>
                        <p className="mt-3 line-clamp-2 text-sm leading-6 text-slate-300">
                          {video.description}
                        </p>
                      </div>

                      <div className="absolute inset-x-5 bottom-4 flex items-center justify-between border-t border-white/10 pt-4">
                        <span className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">
                          {isSelected ? "Ready to process" : "Center to select"}
                        </span>
                        <button
                          type="button"
                          onClick={() => selectVideo(video)}
                          aria-label={`Prepare ${video.title} for AI analysis`}
                          className={cn(
                            "inline-flex min-h-9 items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold shadow-[0_0_28px_rgba(255,255,255,.18)] transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black focus-visible:opacity-100",
                            isSelected
                              ? "bg-white text-black opacity-100"
                              : "bg-white/10 text-white opacity-0 group-hover:opacity-100"
                          )}
                        >
                          <span aria-hidden="true">Prepare</span>
                          <ArrowDown aria-hidden="true" className="size-3.5" />
                        </button>
                      </div>
                    </motion.article>
                  </div>
                );
              })}
            </div>
          </div>

          <div role="tablist" aria-label="Video slides" className="mt-2 flex justify-center gap-2 px-6">
            {displayVideos.map((video, index) => (
              <motion.button
                key={video.video_id}
                type="button"
                role="tab"
                aria-label={`Go to slide ${index + 1}: ${video.title}`}
                aria-selected={selectedIndex === index}
                aria-current={selectedIndex === index ? "true" : undefined}
                onClick={() => emblaApi?.scrollTo(index)}
                whileHover={{ scale: 1.15 }}
                whileTap={{ scale: 0.9 }}
                transition={{ duration: 0.2, ease: smoothEase }}
                className="grid min-h-11 min-w-11 place-items-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 focus-visible:ring-offset-2 focus-visible:ring-offset-black"
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "h-1.5 rounded-full transition-all duration-300",
                    selectedIndex === index
                      ? "w-8 bg-cyan-200"
                      : "w-2.5 bg-white/25 hover:bg-white/45"
                  )}
                />
              </motion.button>
            ))}
          </div>
        </>
      )}
    </motion.section>
  );
}
