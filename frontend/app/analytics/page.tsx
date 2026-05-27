"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Clock3,
  Database,
  Gauge,
  Home,
  Info,
  MessageSquareText,
  RefreshCw,
  Search,
  UsersRound,
  Video,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { getAnalyticsDashboard, type AnalyticsDashboard, type MetricPoint } from "@/lib/api";
import { smoothEase } from "@/lib/motion";
import { cn } from "@/lib/utils";

const panel =
  "rounded-[1.25rem] border border-white/10 bg-white/[0.055] shadow-[0_24px_90px_rgba(0,0,0,.42),inset_0_1px_0_rgba(255,255,255,.06)] backdrop-blur-xl";

const metricHelp = {
  dau: "Daily Active Users counts unique anonymous users seen in the last 24 hours. It shows whether AskTube is actually being used, not only deployed.",
  questionsToday: "Questions Today counts transcript-grounded chat turns from the current day. It reflects learning engagement and the amount of AI workload the app is handling.",
  videosProcessed: "Videos Processed counts videos ingested in the last 24 hours. It shows how often the transcript, chunking, and vector indexing pipeline is used.",
  avgSessionTime: "Average Session Time comes from tracked session activity. Longer sessions usually mean users are finding enough value to keep exploring videos.",
  ragLatency: "RAG Latency is retrieval time plus answer generation time per question. It matters because slow answers hurt usability and reveal vector search or model bottlenecks.",
  citationCoverage: "Citation Coverage estimates how much of the generated answer is backed by timestamp citations. High coverage makes answers easier to verify and reduces unsupported claims.",
  tokenUsage: "Token Usage estimates prompt and completion tokens per answer. It matters for controlling OpenAI cost, latency, and context size.",
  chunkRetrieval: "Chunk Retrieval shows how many transcript chunks are returned to the RAG system. It controls how much source evidence the model can use for each answer.",
  pipelineDuration: "Pipeline Duration is total video processing time from transcript extraction through vector storage. It is the wait users feel before they can chat with a video.",
  transcriptEmbeddings: "Transcript + Embeddings separates caption extraction from vector creation. It helps identify whether YouTube access, Whisper fallback, embedding generation, or ChromaDB insertion is the slow step.",
  transcript: "Transcript measures caption extraction time. Spikes often point to YouTube transcript access, proxy, or Whisper fallback issues.",
  embeddings: "Embeddings measures vector generation and storage time. It matters for cost, indexing speed, and how quickly a processed video becomes searchable.",
  uxMetrics: "UX Metrics summarize product interactions such as carousel choices, voice use, citation clicks, and assistant engagement. They show whether users understand and use the interface.",
  carouselCtr: "Carousel CTR compares result browsing with video selection. It shows whether search results are compelling enough for users to pick a video.",
  voiceFailures: "Voice Failures counts failed speech attempts. A high number means microphone permissions, browser speech recognition, or Whisper fallback need attention.",
  chatRetention: "Chat Retention measures follow-up behavior in chat sessions. Higher retention means users continue exploring the transcript after the first answer.",
  timestampClicks: "Timestamp Clicks counts citation jumps back into the video. This is important because source verification is a core AskTube trust feature.",
  chatbotEngagement: "3D Engagement tracks interactions with the floating assistant. It helps decide whether the companion improves onboarding or is only decorative.",
  voiceUsage: "Voice Usage shows the share of searches using voice input. It measures adoption of AskTube's multimodal experience.",
  businessMetrics: "Business Metrics summarize adoption, retention, and throughput. They are the quickest way to explain product health during a demo.",
  sessions: "Sessions counts tracked user sessions. It shows overall product traffic and conversation volume.",
  returnRate: "Return Rate estimates repeat or follow-up activity. It is a simple retention signal for whether users come back or keep engaging.",
  processedVideosTotal: "Processed Videos is the total number of ingested videos in the analytics window. It measures pipeline throughput.",
  avgProcessing: "Average Processing is the mean time needed to prepare a video for chat. Lower is better because users can start asking questions sooner.",
  recentEvents: "Recent Events shows the raw latest telemetry captured by the app. It is useful for debugging whether frontend, backend, and pipeline tracking are working.",
};

export default function AnalyticsPage() {
  const [dashboard, setDashboard] = useState<AnalyticsDashboard | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  async function loadDashboard() {
    setStatus("loading");
    try {
      setDashboard(await getAnalyticsDashboard());
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }

  useEffect(() => {
    loadDashboard();
  }, []);

  const hasRagData = useMemo(() => {
    const rows = dashboard?.ai_metrics.rag_latency;
    return Array.isArray(rows) && rows.length > 0;
  }, [dashboard]);

  return (
    <main className="relative min-h-dvh overflow-x-hidden bg-[#05070d] px-4 py-6 text-white sm:px-6 lg:px-8">
      <div className="absolute inset-0 -z-20 bg-cinema-radial" />
      <div className="absolute inset-0 -z-10 bg-[linear-gradient(rgba(255,255,255,.025)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.025)_1px,transparent_1px)] bg-[size:72px_72px] opacity-30" />

      <div className="mx-auto max-w-7xl">
        <header className="flex flex-col gap-5 border-b border-white/10 pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-200/20 bg-cyan-200/[0.08] px-3 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-cyan-100">
              <Activity aria-hidden="true" className="size-4" />
              Production analytics
            </div>
            <h1 className="mt-4 text-3xl font-black leading-tight sm:text-5xl">
              AskTube AI Observability
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
              Product usage, RAG quality, pipeline latency, and UX engagement from live AskTube events.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <p className="text-xs text-slate-400">
              Updated {dashboard ? new Date(dashboard.generated_at).toLocaleString() : "loading..."}
            </p>
            <Link
              href="/"
              className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.055] px-3 py-2 text-xs font-medium text-slate-300 backdrop-blur-xl transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
              aria-label="Go back to AskTube home"
            >
              <Home aria-hidden="true" className="size-3.5" />
              <span className="hidden sm:inline">Home</span>
            </Link>
            <Button type="button" variant="ghost" onClick={loadDashboard} disabled={status === "loading"}>
              <RefreshCw aria-hidden="true" className={cn("size-4", status === "loading" && "animate-spin")} />
              Refresh
            </Button>
          </div>
        </header>

        {status === "error" ? (
          <section className={cn(panel, "mt-8 p-6")}>
            <p className="text-lg font-black text-white">Analytics backend is unavailable.</p>
            <p className="mt-2 text-sm text-slate-400">Check `/api/analytics/dashboard` and PostgreSQL connectivity.</p>
            <Button type="button" className="mt-5" onClick={loadDashboard}>Retry</Button>
          </section>
        ) : null}

        {status === "loading" && !dashboard ? <AnalyticsSkeleton /> : null}

        {dashboard ? (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: smoothEase }}
            className="space-y-6 pt-6"
          >
            <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard icon={UsersRound} label="DAU" value={dashboard.overview.daily_active_users} detail={`${dashboard.overview.weekly_active_users} weekly active`} tooltip={metricHelp.dau} />
              <StatCard icon={MessageSquareText} label="Questions Today" value={dashboard.overview.questions_today} detail="Transcript-grounded chat turns" tooltip={metricHelp.questionsToday} />
              <StatCard icon={Video} label="Videos Processed" value={dashboard.overview.videos_processed_today} detail="Ingested in the last 24h" tooltip={metricHelp.videosProcessed} />
              <StatCard icon={Clock3} label="Avg Session Time" value={formatMs(dashboard.overview.avg_session_time_ms)} detail={`${dashboard.overview.search_success_rate}% search success`} tooltip={metricHelp.avgSessionTime} />
            </section>

            {!hasRagData ? (
              <section className={cn(panel, "p-6")}>
                <p className="text-base font-black text-white">No RAG runs captured yet.</p>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                  Search for a video, process it, and ask a transcript question. The charts will populate from real RAG,
                  pipeline, and UX events as soon as those actions complete.
                </p>
              </section>
            ) : null}

            <section className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
              <ChartPanel title="RAG Latency" icon={BrainCircuit} subtitle="Retrieval + generation per answer" tooltip={metricHelp.ragLatency}>
                <AnalyticsLineChart data={asSeries(dashboard.ai_metrics.rag_latency)} color="#67e8f9" />
              </ChartPanel>
              <ChartPanel title="Citation Coverage" icon={Gauge} subtitle="How much retrieved context is cited" tooltip={metricHelp.citationCoverage}>
                <div className="flex h-full min-h-[17rem] flex-col justify-center">
                  <p className="text-6xl font-black text-white">{numberValue(dashboard.ai_metrics.citation_coverage)}%</p>
                  <p className="mt-3 text-sm text-slate-400">
                    Avg retrieval {numberValue(dashboard.ai_metrics.avg_retrieval_latency)}ms · generation {numberValue(dashboard.ai_metrics.avg_generation_latency)}ms
                  </p>
                  <div className="mt-6 h-3 overflow-hidden rounded-full bg-black/40">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.min(100, numberValue(dashboard.ai_metrics.citation_coverage))}%` }}
                      transition={{ duration: 0.7, ease: smoothEase }}
                      className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300"
                    />
                  </div>
                </div>
              </ChartPanel>
            </section>

            <section className="grid gap-6 xl:grid-cols-3">
              <ChartPanel title="Token Usage" icon={BarChart3} subtitle="Prompt + completion estimates" tooltip={metricHelp.tokenUsage}>
                <AnalyticsAreaChart data={asSeries(dashboard.ai_metrics.token_usage)} color="#f0abfc" />
              </ChartPanel>
              <ChartPanel title="Chunk Retrieval" icon={Database} subtitle="Documents returned to RAG" tooltip={metricHelp.chunkRetrieval}>
                <AnalyticsBarChart data={asSeries(dashboard.ai_metrics.chunk_retrieval)} color="#5eead4" />
              </ChartPanel>
              <ChartPanel title="Pipeline Duration" icon={Zap} subtitle="Total processing time per video" tooltip={metricHelp.pipelineDuration}>
                <AnalyticsBarChart data={asSeries(dashboard.pipeline_metrics.processing_duration)} color="#fb7185" />
              </ChartPanel>
            </section>

            <section className="grid gap-6 xl:grid-cols-2">
              <ChartPanel title="Transcript + Embeddings" icon={Video} subtitle="Extraction and vector creation timing" tooltip={metricHelp.transcriptEmbeddings}>
                <div className="grid h-full gap-4 md:grid-cols-2">
                  <MiniSeries title="Transcript" data={asSeries(dashboard.pipeline_metrics.transcript_extraction)} tooltip={metricHelp.transcript} />
                  <MiniSeries title="Embeddings" data={asSeries(dashboard.pipeline_metrics.embedding_duration)} tooltip={metricHelp.embeddings} />
                </div>
              </ChartPanel>
              <section className={cn(panel, "p-5")}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                  <div className="grid size-10 place-items-center rounded-xl border border-cyan-200/20 bg-cyan-200/10">
                    <Search aria-hidden="true" className="size-5 text-cyan-100" />
                  </div>
                  <div>
                    <h2 className="text-lg font-black text-white">UX Metrics</h2>
                    <p className="text-xs text-slate-400">Engagement signals from the product surface</p>
                  </div>
                  </div>
                  <MetricTooltip title="UX Metrics" body={metricHelp.uxMetrics} />
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <MetricPill label="Carousel CTR" value={`${dashboard.ux_metrics.carousel_click_rate ?? 0}%`} tooltip={metricHelp.carouselCtr} />
                  <MetricPill label="Voice Failures" value={dashboard.ux_metrics.voice_failures ?? 0} tooltip={metricHelp.voiceFailures} />
                  <MetricPill label="Chat Retention" value={`${dashboard.ux_metrics.chat_retention ?? 0}%`} tooltip={metricHelp.chatRetention} />
                  <MetricPill label="Timestamp Clicks" value={dashboard.ux_metrics.timestamp_clicks ?? 0} tooltip={metricHelp.timestampClicks} />
                  <MetricPill label="3D Engagement" value={dashboard.ux_metrics.chatbot_interactions ?? 0} tooltip={metricHelp.chatbotEngagement} />
                  <MetricPill label="Voice Usage" value={`${dashboard.overview.voice_usage_rate}%`} tooltip={metricHelp.voiceUsage} />
                </div>
              </section>
            </section>

            <section className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
              <section className={cn(panel, "p-5")}>
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-lg font-black text-white">Business Metrics</h2>
                  <MetricTooltip title="Business Metrics" body={metricHelp.businessMetrics} />
                </div>
                <div className="mt-5 grid gap-3">
                  <MetricPill label="Sessions" value={numberValue(dashboard.business_metrics.sessions)} tooltip={metricHelp.sessions} />
                  <MetricPill label="Return Rate" value={`${numberValue(dashboard.business_metrics.return_rate)}%`} tooltip={metricHelp.returnRate} />
                  <MetricPill label="Processed Videos" value={numberValue(dashboard.business_metrics.videos_processed)} tooltip={metricHelp.processedVideosTotal} />
                  <MetricPill label="Avg Processing" value={formatMs(numberValue(dashboard.business_metrics.avg_processing_time))} tooltip={metricHelp.avgProcessing} />
                </div>
              </section>
              <section className={cn(panel, "p-5")}>
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-lg font-black text-white">Recent Events</h2>
                  <MetricTooltip title="Recent Events" body={metricHelp.recentEvents} />
                </div>
                <div className="mt-5 max-h-[23rem] space-y-3 overflow-y-auto pr-1">
                  {dashboard.recent_events.length === 0 ? (
                    <p className="text-sm text-slate-500">No events captured yet.</p>
                  ) : (
                    dashboard.recent_events.map((event, index) => (
                      <div key={`${event.event_type}-${index}`} className="rounded-xl border border-white/10 bg-black/25 p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-bold text-white">{event.event_type}</p>
                          <p className="text-xs text-slate-500">{new Date(event.timestamp).toLocaleString()}</p>
                        </div>
                        <p className="mt-1 line-clamp-1 text-xs text-slate-400">
                          {event.duration_ms ? `${Math.round(event.duration_ms)}ms · ` : ""}
                          {JSON.stringify(event.metadata_json)}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </section>
          </motion.div>
        ) : null}
      </div>
    </main>
  );
}

function StatCard({ icon: Icon, label, value, detail, tooltip }: { icon: LucideIcon; label: string; value: string | number; detail: string; tooltip: string }) {
  return (
    <motion.div whileHover={{ y: -3 }} transition={{ duration: 0.2 }} className={cn(panel, "p-5")}>
      <div className="flex items-start justify-between gap-4">
        <div className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.07]">
          <Icon aria-hidden="true" className="size-5 text-cyan-100" />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">{label}</span>
          <MetricTooltip title={label} body={tooltip} />
        </div>
      </div>
      <p className="mt-5 text-3xl font-black text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{detail}</p>
    </motion.div>
  );
}

function ChartPanel({ title, subtitle, icon: Icon, children, tooltip }: { title: string; subtitle: string; icon: LucideIcon; children: ReactNode; tooltip: string }) {
  return (
    <section className={cn(panel, "min-h-[22rem] p-5")}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.07]">
            <Icon aria-hidden="true" className="size-5 text-cyan-100" />
          </div>
          <div>
            <h2 className="text-lg font-black text-white">{title}</h2>
            <p className="text-xs text-slate-400">{subtitle}</p>
          </div>
        </div>
        <MetricTooltip title={title} body={tooltip} />
      </div>
      <div className="mt-5 h-[17rem]">{children}</div>
    </section>
  );
}

function AnalyticsLineChart({ data, color }: { data: MetricPoint[]; color: string }) {
  if (!data.length) return <NoChartData />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data}>
        <CartesianGrid stroke="rgba(255,255,255,.08)" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip content={<ChartTooltip />} />
        <Line type="monotone" dataKey="value" stroke={color} strokeWidth={3} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function AnalyticsAreaChart({ data, color }: { data: MetricPoint[]; color: string }) {
  if (!data.length) return <NoChartData />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <CartesianGrid stroke="rgba(255,255,255,.08)" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip content={<ChartTooltip />} />
        <Area type="monotone" dataKey="value" stroke={color} fill={color} fillOpacity={0.18} strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function AnalyticsBarChart({ data, color }: { data: MetricPoint[]; color: string }) {
  if (!data.length) return <NoChartData />;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid stroke="rgba(255,255,255,.08)" vertical={false} />
        <XAxis dataKey="label" tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip content={<ChartTooltip />} />
        <Bar dataKey="value" fill={color} radius={[6, 6, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function MiniSeries({ title, data, tooltip }: { title: string; data: MetricPoint[]; tooltip: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">{title}</p>
        <MetricTooltip title={title} body={tooltip} />
      </div>
      <div className="mt-3 h-44">
        <AnalyticsAreaChart data={data} color={title === "Transcript" ? "#67e8f9" : "#c084fc"} />
      </div>
    </div>
  );
}

function MetricPill({ label, value, tooltip }: { label: string; value: string | number; tooltip: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-slate-500">{label}</p>
        <MetricTooltip title={label} body={tooltip} />
      </div>
      <p className="mt-1 text-xl font-black text-white">{value}</p>
    </div>
  );
}

function MetricTooltip({ title, body }: { title: string; body: string }) {
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        className="grid size-7 shrink-0 place-items-center rounded-full border border-white/10 bg-white/[0.06] text-slate-400 transition hover:border-cyan-300/50 hover:bg-cyan-200/10 hover:text-cyan-100 focus:outline-none focus:ring-2 focus:ring-cyan-300/50"
        aria-label={`Explain ${title}`}
      >
        <Info aria-hidden="true" className="size-3.5" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute right-0 top-9 z-40 w-72 rounded-2xl border border-cyan-300/20 bg-[#080b12]/95 p-3 text-left text-xs leading-5 text-slate-300 opacity-0 shadow-2xl shadow-cyan-950/30 backdrop-blur-xl transition duration-150 group-hover:opacity-100 group-focus-within:opacity-100"
      >
        <span className="block font-black text-white">{title}</span>
        <span className="mt-1 block">{body}</span>
      </span>
    </span>
  );
}

function NoChartData() {
  return (
    <div className="grid h-full place-items-center rounded-xl border border-dashed border-white/10 bg-black/20 text-center">
      <p className="max-w-xs text-sm leading-6 text-slate-500">No matching telemetry has been recorded yet.</p>
    </div>
  );
}

function AnalyticsSkeleton() {
  return (
    <div className="grid gap-4 pt-6 sm:grid-cols-2 xl:grid-cols-4" aria-busy="true">
      {[0, 1, 2, 3].map((item) => (
        <div key={item} className={cn(panel, "h-36 animate-pulse bg-white/[0.035]")} />
      ))}
    </div>
  );
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-[#080b12]/95 px-3 py-2 shadow-2xl">
      <p className="text-xs text-slate-400">{label}</p>
      <p className="text-sm font-black text-white">{Math.round(payload[0].value * 100) / 100}</p>
    </div>
  );
}

function asSeries(value: MetricPoint[] | number | undefined): MetricPoint[] {
  return Array.isArray(value) ? value : [];
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatMs(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(1)}s`;
  return `${Math.round(value)}ms`;
}
