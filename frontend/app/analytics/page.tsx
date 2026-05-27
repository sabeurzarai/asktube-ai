"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  BarChart3,
  BrainCircuit,
  Clock3,
  Database,
  Gauge,
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
              <StatCard icon={UsersRound} label="DAU" value={dashboard.overview.daily_active_users} detail={`${dashboard.overview.weekly_active_users} weekly active`} />
              <StatCard icon={MessageSquareText} label="Questions Today" value={dashboard.overview.questions_today} detail="Transcript-grounded chat turns" />
              <StatCard icon={Video} label="Videos Processed" value={dashboard.overview.videos_processed_today} detail="Ingested in the last 24h" />
              <StatCard icon={Clock3} label="Avg Session Time" value={formatMs(dashboard.overview.avg_session_time_ms)} detail={`${dashboard.overview.search_success_rate}% search success`} />
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
              <ChartPanel title="RAG Latency" icon={BrainCircuit} subtitle="Retrieval + generation per answer">
                <AnalyticsLineChart data={asSeries(dashboard.ai_metrics.rag_latency)} color="#67e8f9" />
              </ChartPanel>
              <ChartPanel title="Citation Coverage" icon={Gauge} subtitle="How much retrieved context is cited">
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
              <ChartPanel title="Token Usage" icon={BarChart3} subtitle="Prompt + completion estimates">
                <AnalyticsAreaChart data={asSeries(dashboard.ai_metrics.token_usage)} color="#f0abfc" />
              </ChartPanel>
              <ChartPanel title="Chunk Retrieval" icon={Database} subtitle="Documents returned to RAG">
                <AnalyticsBarChart data={asSeries(dashboard.ai_metrics.chunk_retrieval)} color="#5eead4" />
              </ChartPanel>
              <ChartPanel title="Pipeline Duration" icon={Zap} subtitle="Total processing time per video">
                <AnalyticsBarChart data={asSeries(dashboard.pipeline_metrics.processing_duration)} color="#fb7185" />
              </ChartPanel>
            </section>

            <section className="grid gap-6 xl:grid-cols-2">
              <ChartPanel title="Transcript + Embeddings" icon={Video} subtitle="Extraction and vector creation timing">
                <div className="grid h-full gap-4 md:grid-cols-2">
                  <MiniSeries title="Transcript" data={asSeries(dashboard.pipeline_metrics.transcript_extraction)} />
                  <MiniSeries title="Embeddings" data={asSeries(dashboard.pipeline_metrics.embedding_duration)} />
                </div>
              </ChartPanel>
              <section className={cn(panel, "p-5")}>
                <div className="flex items-center gap-3">
                  <div className="grid size-10 place-items-center rounded-xl border border-cyan-200/20 bg-cyan-200/10">
                    <Search aria-hidden="true" className="size-5 text-cyan-100" />
                  </div>
                  <div>
                    <h2 className="text-lg font-black text-white">UX Metrics</h2>
                    <p className="text-xs text-slate-400">Engagement signals from the product surface</p>
                  </div>
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <MetricPill label="Carousel CTR" value={`${dashboard.ux_metrics.carousel_click_rate ?? 0}%`} />
                  <MetricPill label="Voice Failures" value={dashboard.ux_metrics.voice_failures ?? 0} />
                  <MetricPill label="Chat Retention" value={`${dashboard.ux_metrics.chat_retention ?? 0}%`} />
                  <MetricPill label="Timestamp Clicks" value={dashboard.ux_metrics.timestamp_clicks ?? 0} />
                  <MetricPill label="3D Engagement" value={dashboard.ux_metrics.chatbot_interactions ?? 0} />
                  <MetricPill label="Voice Usage" value={`${dashboard.overview.voice_usage_rate}%`} />
                </div>
              </section>
            </section>

            <section className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
              <section className={cn(panel, "p-5")}>
                <h2 className="text-lg font-black text-white">Business Metrics</h2>
                <div className="mt-5 grid gap-3">
                  <MetricPill label="Sessions" value={numberValue(dashboard.business_metrics.sessions)} />
                  <MetricPill label="Return Rate" value={`${numberValue(dashboard.business_metrics.return_rate)}%`} />
                  <MetricPill label="Processed Videos" value={numberValue(dashboard.business_metrics.videos_processed)} />
                  <MetricPill label="Avg Processing" value={formatMs(numberValue(dashboard.business_metrics.avg_processing_time))} />
                </div>
              </section>
              <section className={cn(panel, "p-5")}>
                <h2 className="text-lg font-black text-white">Recent Events</h2>
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

function StatCard({ icon: Icon, label, value, detail }: { icon: LucideIcon; label: string; value: string | number; detail: string }) {
  return (
    <motion.div whileHover={{ y: -3 }} transition={{ duration: 0.2 }} className={cn(panel, "p-5")}>
      <div className="flex items-center justify-between gap-4">
        <div className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.07]">
          <Icon aria-hidden="true" className="size-5 text-cyan-100" />
        </div>
        <span className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">{label}</span>
      </div>
      <p className="mt-5 text-3xl font-black text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{detail}</p>
    </motion.div>
  );
}

function ChartPanel({ title, subtitle, icon: Icon, children }: { title: string; subtitle: string; icon: LucideIcon; children: ReactNode }) {
  return (
    <section className={cn(panel, "min-h-[22rem] p-5")}>
      <div className="flex items-center gap-3">
        <div className="grid size-10 place-items-center rounded-xl border border-white/10 bg-white/[0.07]">
          <Icon aria-hidden="true" className="size-5 text-cyan-100" />
        </div>
        <div>
          <h2 className="text-lg font-black text-white">{title}</h2>
          <p className="text-xs text-slate-400">{subtitle}</p>
        </div>
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

function MiniSeries({ title, data }: { title: string; data: MetricPoint[] }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-400">{title}</p>
      <div className="mt-3 h-44">
        <AnalyticsAreaChart data={data} color={title === "Transcript" ? "#67e8f9" : "#c084fc"} />
      </div>
    </div>
  );
}

function MetricPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/25 p-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-black text-white">{value}</p>
    </div>
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
