"use client";

import { ReactNode } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Loader2, RotateCcw, SearchX, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { smoothEase, staggerContainer, subtleItemReveal } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function ShimmerBlock({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.055]",
        className
      )}
    >
      <motion.div
        className="absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-transparent via-white/12 to-transparent"
        animate={{ x: ["-120%", "240%"] }}
        transition={{ duration: 1.65, repeat: Infinity, ease: "easeInOut" }}
      />
    </div>
  );
}

export function CinematicProgress({
  value,
  label,
  remaining
}: {
  value: number;
  label: string;
  remaining?: string;
}) {
  return (
    <div className="rounded-[1.35rem] border border-white/10 bg-black/30 p-4 backdrop-blur-xl">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-100">
            {label}
          </p>
          {remaining ? <p className="mt-1 text-xs text-slate-400">{remaining}</p> : null}
        </div>
        <p className="text-2xl font-black tabular-nums text-white">{Math.round(value)}%</p>
      </div>
      <div className="mt-4 h-2.5 overflow-hidden rounded-full border border-white/10 bg-black/50">
        <motion.div
          className="relative h-full overflow-hidden rounded-full bg-gradient-to-r from-pink-500 via-cyan-300 to-blue-500 shadow-[0_0_28px_rgba(34,211,238,.45)]"
          animate={{ width: `${Math.min(100, Math.max(0, value))}%` }}
          transition={{ duration: 0.55, ease: smoothEase }}
        >
          <motion.span
            aria-hidden="true"
            animate={{ x: ["-60%", "180%"] }}
            transition={{ duration: 1.35, repeat: Infinity, ease: "easeInOut" }}
            className="absolute inset-y-0 left-0 w-1/2 bg-gradient-to-r from-transparent via-white/40 to-transparent"
          />
        </motion.div>
      </div>
    </div>
  );
}

export function ProcessingSteps({
  steps,
  activeIndex
}: {
  steps: string[];
  activeIndex: number;
}) {
  return (
    <motion.div variants={staggerContainer} initial="hidden" animate="visible" className="grid gap-2">
      {steps.map((step, index) => {
        const isActive = index === activeIndex;
        const isDone = index < activeIndex;

        return (
          <motion.div
            key={step}
            variants={subtleItemReveal}
            className={cn(
              "flex min-h-11 items-center gap-3 rounded-2xl border px-3 py-2 text-sm transition duration-200",
              isActive
                ? "border-cyan-200/35 bg-cyan-200/[0.09] text-cyan-50 shadow-[0_0_28px_rgba(34,211,238,.10)]"
                : isDone
                  ? "border-emerald-300/20 bg-emerald-300/[0.07] text-emerald-100"
                  : "border-white/10 bg-white/[0.035] text-slate-400"
            )}
          >
            <span
              className={cn(
                "grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-black",
                isActive
                  ? "bg-cyan-200 text-black"
                  : isDone
                    ? "bg-emerald-300 text-black"
                    : "bg-white/10 text-slate-400"
              )}
            >
              {index + 1}
            </span>
            <span>{step}</span>
            {isActive ? <Loader2 aria-hidden="true" className="ml-auto size-4 animate-spin" /> : null}
          </motion.div>
        );
      })}
    </motion.div>
  );
}

export function VideoSkeletonGrid() {
  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      animate="visible"
      className="grid gap-4 px-5 sm:grid-cols-2 lg:grid-cols-3"
    >
      {[0, 1, 2].map((item) => (
        <motion.div
          key={item}
          variants={subtleItemReveal}
          className="rounded-[1.5rem] border border-white/10 bg-black/30 p-4"
        >
          <ShimmerBlock className="aspect-video" />
          <div className="mt-4 flex gap-2">
            <ShimmerBlock className="h-7 w-20 rounded-full" />
            <ShimmerBlock className="h-7 w-28 rounded-full" />
          </div>
          <ShimmerBlock className="mt-4 h-6 w-4/5" />
          <ShimmerBlock className="mt-3 h-4 w-full" />
          <ShimmerBlock className="mt-2 h-4 w-2/3" />
        </motion.div>
      ))}
    </motion.div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-[1.5rem] border border-white/10 bg-black/30 p-5 text-center backdrop-blur-xl">
      <div className="mx-auto grid size-12 place-items-center rounded-2xl border border-white/10 bg-white/[0.06] text-slate-200">
        {icon ?? <SearchX aria-hidden="true" className="size-5" />}
      </div>
      <h3 className="mt-4 text-lg font-black text-white">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-300">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title,
  description,
  onRetry,
  retryLabel = "Try again"
}: {
  title: string;
  description: string;
  onRetry?: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className="rounded-[1.5rem] border border-red-300/20 bg-red-500/[0.08] p-5 text-left shadow-[0_0_40px_rgba(239,68,68,.10)] backdrop-blur-xl"
    >
      <div className="flex gap-3">
        <div className="grid size-11 shrink-0 place-items-center rounded-2xl border border-red-300/20 bg-red-400/10 text-red-100">
          <AlertTriangle aria-hidden="true" className="size-5" />
        </div>
        <div>
          <h3 className="text-base font-black text-white">{title}</h3>
          <p className="mt-1 text-sm leading-6 text-red-100/85">{description}</p>
          {onRetry ? (
            <Button type="button" variant="ghost" className="mt-4" onClick={onRetry}>
              <RotateCcw aria-hidden="true" className="size-4" />
              {retryLabel}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function RouteLoadingState() {
  return (
    <main className="grid min-h-dvh place-items-center bg-[#05070d] px-5 text-white">
      <div className="w-full max-w-xl rounded-[2rem] border border-white/10 bg-white/[0.055] p-5 shadow-cinema-card backdrop-blur-2xl">
        <div className="flex items-center gap-3">
          <div className="grid size-12 place-items-center rounded-2xl border border-cyan-200/20 bg-cyan-200/10 text-cyan-100">
            <Sparkles aria-hidden="true" className="size-5" />
          </div>
          <div>
            <p className="text-sm font-black text-white">AskTube AI</p>
            <p className="text-xs text-slate-400">Preparing cinematic learning space</p>
          </div>
        </div>
        <div className="mt-6 space-y-3">
          <ShimmerBlock className="h-8 w-2/3" />
          <ShimmerBlock className="h-4 w-full" />
          <ShimmerBlock className="h-4 w-4/5" />
        </div>
        <div className="mt-6">
          <CinematicProgress value={68} label="Loading interface" remaining="about 2s left" />
        </div>
      </div>
    </main>
  );
}
