import { motion } from "motion/react";
import { AlertTriangle, Check, CloudDownload, Cpu, Loader2, Sparkles, Users2 } from "lucide-react";
import type { AnalysisJob } from "@/types";

const STAGES = [
  { key: "fetch", label: "Fetching GitHub activity", testid: "pipeline-stage-fetch-repos", icon: CloudDownload },
  { key: "classify", label: "AI contribution taxonomy", testid: "pipeline-stage-classify-ai", icon: Cpu },
  { key: "skills", label: "Skill graph aggregation", testid: "pipeline-stage-aggregate-skills", icon: Users2 },
  { key: "insights", label: "STAR & insight generation", testid: "pipeline-stage-generate-insights", icon: Sparkles },
];

// Live 4-stage stepper: done = check, active = pulsing loader with emerald glow, todo = dim.
export default function AnalysisPipeline({ job }: { job: AnalysisJob }) {
  const activeIdx = STAGES.findIndex((s) => s.key === job.stage);
  const failed = job.status === "failed";
  const done = job.status === "completed";
  const active = job.status === "queued" || job.status === "running";

  const statChips = Object.entries(job.stats).filter(([, v]) => v > 0);

  return (
    <section
      data-testid="dashboard-pipeline-stepper"
      className="rounded-xl border border-border bg-card p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            Analysis pipeline
          </p>
          <h2 className="mt-1 font-heading text-xl font-semibold tracking-tight text-slate-100">
            {failed ? "Analysis failed" : done ? "Analysis complete" : job.stage_label}
          </h2>
        </div>
        <span
          className={
            "font-mono text-3xl font-bold tabular-nums " + (failed ? "text-red-400" : "text-primary")
          }
        >
          {job.progress}%
        </span>
      </div>

      <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-800">
        <motion.div
          className={
            "h-full rounded-full " + (failed ? "bg-red-500/70" : "bg-gradient-to-r from-emerald-600 to-emerald-400")
          }
          initial={{ width: 0 }}
          animate={{ width: `${job.progress}%` }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>

      <ul className="mt-6 space-y-1">
        {STAGES.map((stage, idx) => {
          const stageDone = done || (activeIdx !== -1 && idx < activeIdx);
          const stageActive = active && idx === activeIdx;
          const Icon = stage.icon;
          return (
            <li
              key={stage.key}
              data-testid={stage.testid}
              className={
                "flex items-center gap-3 rounded-lg px-3 py-2.5 " +
                (stageActive ? "bg-primary/5 stage-glow" : "")
              }
            >
              <span
                className={
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border " +
                  (stageDone
                    ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                    : stageActive
                      ? "border-emerald-500/50 bg-primary/10 text-primary"
                      : "border-slate-700 bg-secondary text-slate-500")
                }
              >
                {stageDone ? (
                  <Check className="h-4 w-4" />
                ) : stageActive ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Icon className="h-4 w-4" />
                )}
              </span>
              <span
                className={
                  "text-sm " +
                  (stageDone || stageActive ? "text-slate-200" : "text-slate-500")
                }
              >
                {stage.label}
              </span>
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {stageDone ? "done" : stageActive ? job.stage_label : "pending"}
              </span>
            </li>
          );
        })}
      </ul>

      {failed && job.error && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{job.error}</span>
        </div>
      )}

      {statChips.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {statChips.map(([key, value]) => (
            <span
              key={key}
              className="rounded-md border border-border bg-secondary px-2.5 py-1 font-mono text-xs text-slate-300"
            >
              {key.replace(/_/g, " ")}: <span className="text-primary">{value}</span>
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
