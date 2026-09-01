"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { motion } from "framer-motion";
import { ArrowLeft, Clock3 } from "lucide-react";

import { sectionReveal, sectionViewport } from "@/lib/motion";

// WebGL has no business running during server rendering, and the three.js
// bundle should not sit in the entry chunk for people who never open this page.
const TranscriptTimelineScene = dynamic(
  () => import("@/components/tour/transcript-timeline-scene").then((m) => m.TranscriptTimelineScene),
  { ssr: false },
);

type Station = {
  step: string;
  label: string;
  heading: React.ReactNode;
  body: string;
  note: string;
  facts?: { term: string; value: string; unit: string }[];
  cite?: string;
};

const STATIONS: Station[] = [
  {
    step: "01",
    label: "Search",
    heading: (
      <>
        A question arrives before the <em className="text-accent not-italic">video</em> does.
      </>
    ),
    body:
      "The learner asks in words, not in video IDs. The YouTube Data API returns candidates; the agent binds itself to exactly one of them and is forbidden from wandering to another — a rule learned the hard way, after it once answered from a video nobody had asked for.",
    note: "Prohibition, not preference: a soft “focus on this video” lost to the workflow block above it in the same prompt.",
  },
  {
    step: "02",
    label: "Ingest",
    heading: (
      <>
        The transcript becomes a <em className="text-accent not-italic">track</em>.
      </>
    ),
    body:
      "Captions arrive as hundreds of fragments, each with a start and a duration. Whisper transcribes the video itself when no captions exist. What comes out is one continuous thing with time along its length — the ribbon under the camera.",
    note: "YouTube refuses datacenter IPs, so the fetch leaves through a rotating residential proxy. Roughly one attempt in six still draws a flagged exit IP, which is why a block is retried rather than reported.",
  },
  {
    step: "03",
    label: "Chunk & embed",
    heading: (
      <>
        Cut into spans, then turned into <em className="text-accent not-italic">coordinates</em>.
      </>
    ),
    body:
      "The track is cut at semantic boundaries into pieces of about 600 characters, each keeping the timestamps of the segments it covers. Every piece becomes a vector — the cloud drifting above the ribbon — and lands in Postgres with pgvector.",
    note: "600 was chosen for context share, not hit rate. At 1200 the top five chunks handed the model 53% of a whole video, which undercuts a prompt that promises to answer only from what it was given.",
    facts: [
      { term: "Chunk size", value: "600", unit: "characters" },
      { term: "Context share", value: "29%", unit: "of the video, at top-5" },
      { term: "Overlap", value: "1", unit: "segment per boundary" },
    ],
  },
  {
    step: "04",
    label: "Retrieve",
    heading: (
      <>
        Five spans, and the honesty to say <em className="text-accent not-italic">none</em>.
      </>
    ),
    body:
      "The question is rewritten into something standalone — “and what happens first?” means nothing to a vector search — then matched against the cloud by cosine distance. Five chunks come back. On-topic questions score 0.48–0.66; anything above 0.78 is a question this video cannot answer, and saying so is the correct result.",
    note: "The second evaluation video is a biology lecture, chosen because it shares no vocabulary with the programming one. Without an unrelated pair, a filter that silently stopped working would still look correct.",
    facts: [
      { term: "top_k", value: "5", unit: "measured, not guessed" },
      { term: "Rank 1 hits", value: "16", unit: "of 26 content cases" },
      { term: "Eval set", value: "29", unit: "cases, two videos" },
    ],
  },
  {
    step: "05",
    label: "Answer",
    heading: (
      <>
        The citation is the <em className="text-primary not-italic">product</em>.
      </>
    ),
    body:
      "The model sees only those spans and the original question — never the rewrite, which is a guess about intent. Each claim carries the timestamp of the span it came from, validated against real chunks before it is allowed to appear. An invented mark is dropped, not shown.",
    note: "A broad question — “what is this video about?” — skips retrieval entirely and summarises every chunk in one call. Top-5 answers that question badly by construction.",
    cite: "01:10 – 02:24 · fWjsdhR3z3c",
  },
];

export default function TourPage() {
  return (
    <div className="relative min-h-screen bg-background text-foreground">
      <TranscriptTimelineScene />

      <Link
        href="/"
        className="fixed left-6 top-6 z-20 inline-flex items-center gap-2 rounded-full border border-white/10 bg-background/70 px-4 py-2 text-xs font-medium text-muted-foreground backdrop-blur transition hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
        Back to AskTube
      </Link>

      <main className="relative z-10 mx-auto max-w-[88rem] px-6 sm:px-10 lg:px-20">
        <section className="grid min-h-svh max-w-2xl content-center gap-5 py-24">
          <p className="flex items-baseline gap-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-accent">
            <span className="tabular-nums text-foreground/40">00</span> AskTube AI
          </p>
          <h1 className="text-balance text-4xl font-light leading-[1.08] tracking-tight sm:text-6xl lg:text-7xl">
            Every answer points at the{" "}
            <em className="not-italic text-accent">second</em> it came from.
          </h1>
          <p className="text-lg leading-relaxed text-muted-foreground">
            A YouTube video is a timeline. So is the answer about it. This is the path a
            question takes through that timeline — search, ingest, embed, retrieve, cite —
            and why the last step is the one that matters.
          </p>
          <p className="flex items-center gap-2 border-l-2 border-white/10 pl-4 text-xs text-muted-foreground">
            <Clock3 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            The ribbon ahead of you is a transcript. Scroll to travel along it.
          </p>
        </section>

        {STATIONS.map((station) => (
          <motion.section
            key={station.step}
            variants={sectionReveal}
            initial="hidden"
            whileInView="visible"
            viewport={sectionViewport}
            className="grid min-h-svh max-w-2xl content-center gap-4 py-24"
          >
            <p
              className={`flex items-baseline gap-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em] ${
                station.cite ? "text-primary" : "text-accent"
              }`}
            >
              <span className="tabular-nums text-foreground/40">{station.step}</span>
              {station.label}
            </p>
            <h2 className="text-balance text-3xl font-light leading-[1.1] tracking-tight sm:text-4xl lg:text-5xl">
              {station.heading}
            </h2>
            <p className="leading-relaxed text-muted-foreground">{station.body}</p>

            {station.facts ? (
              <dl className="mt-3 grid gap-px overflow-hidden rounded-lg border border-white/10 bg-white/10 sm:grid-cols-3">
                {station.facts.map((fact) => (
                  <div key={fact.term} className="bg-background/85 p-4">
                    <dt className="text-[0.62rem] uppercase tracking-[0.16em] text-muted-foreground">
                      {fact.term}
                    </dt>
                    <dd className="mt-1.5 text-2xl font-medium tabular-nums text-accent">
                      {fact.value}
                      <span className="mt-1 block text-[0.62rem] font-normal tracking-wide text-muted-foreground">
                        {fact.unit}
                      </span>
                    </dd>
                  </div>
                ))}
              </dl>
            ) : null}

            {station.cite ? (
              <p className="mt-1 inline-flex w-fit items-center gap-2 rounded border border-primary/30 bg-primary/10 px-3 py-1.5 font-mono text-xs text-primary">
                <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                {station.cite}
              </p>
            ) : null}

            <p className="border-l-2 border-white/10 pl-4 text-xs leading-relaxed text-muted-foreground">
              {station.note}
            </p>
          </motion.section>
        ))}

        <section className="grid min-h-svh max-w-2xl content-center gap-4 py-24">
          <p className="flex items-baseline gap-3 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-primary">
            <span className="tabular-nums text-foreground/40">06</span> What this buys
          </p>
          <h2 className="text-balance text-3xl font-light leading-[1.1] tracking-tight sm:text-4xl lg:text-5xl">
            An answer you can <em className="not-italic text-primary">check</em> in one click.
          </h2>
          <p className="leading-relaxed text-muted-foreground">
            Grounding is a claim until someone can verify it. The timestamp is what turns
            the claim into something falsifiable: click it, land on the second, and see
            whether the video says what the answer says it does.
          </p>
          <Link
            href="/"
            className="mt-4 inline-flex w-fit items-center gap-2 rounded-full bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Try it on a video
          </Link>
        </section>
      </main>

      <footer className="relative z-10 mx-auto max-w-[88rem] border-t border-white/10 px-6 py-12 text-xs text-muted-foreground sm:px-10 lg:px-20">
        Figures shown are the project&rsquo;s measured values, not illustrations.
      </footer>
    </div>
  );
}
