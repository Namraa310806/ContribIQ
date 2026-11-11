import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "motion/react";
import { Check, Copy, ExternalLink, Loader2, Pin, PinOff, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiPost } from "@/lib/api";
import type { Insight, StartAnalysisResponse } from "@/types";

function useCopyFlash() {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copy = async (text: string, id: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      toast.success(`${label} copied to clipboard`);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1600);
    } catch {
      toast.error("Clipboard is unavailable in this browser");
    }
  };
  return { copiedId, copy };
}

function EvidencePills({ insight }: { insight: Insight }) {
  if (insight.evidence.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {insight.evidence.map((ev) => (
        <a
          key={ev.contribution_id}
          href={ev.url || undefined}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 font-mono text-[11px] text-sky-300 hover:border-sky-400/50"
        >
          {ev.label || "evidence"}
          {ev.url && <ExternalLink className="h-3 w-3" />}
        </a>
      ))}
    </div>
  );
}

function PinButton({ insight }: { insight: Insight }) {
  const queryClient = useQueryClient();
  const pin = useMutation({
    mutationFn: () => apiPost<Insight>(`/insights/${insight.id}/pin`, { pinned: !insight.pinned }),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ["insights"] });
      toast.success(updated.pinned ? "Pinned to the recruiter dossier" : "Unpinned from the dossier");
    },
    onError: () => toast.error("Could not update the pin"),
  });
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      data-testid={insight.kind === "star" ? "star-answer-pin-btn" : "resume-bullet-pin-btn"}
      onClick={() => pin.mutate()}
      disabled={pin.isPending}
      title={insight.pinned ? "Unpin from dossier" : "Pin to recruiter dossier"}
      className={insight.pinned ? "text-amber-300" : "text-slate-400"}
    >
      {insight.pinned ? <Pin className="h-4 w-4" /> : <PinOff className="h-4 w-4" />}
    </Button>
  );
}

const STAR_BLOCKS: Array<{ key: "situation" | "task" | "action" | "result"; label: string }> = [
  { key: "situation", label: "S — Situation" },
  { key: "task", label: "T — Task" },
  { key: "action", label: "A — Action" },
  { key: "result", label: "R — Result" },
];

// Three intelligence panels: recruiter bio, resume bullets, STAR narratives.
export default function InsightsTab({ insights, jobActive }: { insights: Insight[]; jobActive: boolean }) {
  const queryClient = useQueryClient();
  const { copiedId, copy } = useCopyFlash();

  const regenerate = useMutation({
    mutationFn: () => apiPost<StartAnalysisResponse>("/insights/regenerate"),
    onSuccess: (data) => {
      queryClient.setQueryData(["job"], { job: data.job });
      toast.success("Regenerating insights — follow the pipeline above");
    },
    onError: () => toast.error("Could not start regeneration"),
  });

  const summary = insights.find((i) => i.kind === "recruiter_summary");
  const bullets = insights.filter((i) => i.kind === "bullet");
  const stars = insights.filter((i) => i.kind === "star");

  return (
    <div className="space-y-6">
      {summary && (
        <motion.section
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          className="rounded-xl border border-primary/25 bg-card p-6"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
                Executive recruiter bio
              </p>
              <h3 className="mt-1 font-heading text-lg font-semibold tracking-tight text-slate-100">
                {summary.title}
              </h3>
            </div>
            <Button
              variant="outline"
              size="sm"
              data-testid="insights-regenerate-btn"
              onClick={() => regenerate.mutate()}
              disabled={regenerate.isPending || jobActive}
              className="gap-1.5"
            >
              {regenerate.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Regenerate
            </Button>
          </div>
          <div
            data-testid="recruiter-summary-content"
            className="mt-4 space-y-3 text-sm leading-relaxed text-slate-300"
          >
            {summary.content.split("\n\n").map((para, idx) => (
              <p key={idx}>{para}</p>
            ))}
          </div>
        </motion.section>
      )}

      <section>
        <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">Resume bullets</p>
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          {bullets.map((bullet, idx) => (
            <motion.div
              key={bullet.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx * 0.05, 0.3), duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="card-hover rounded-lg border border-border bg-card p-4"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-xs text-emerald-400/80">{String(idx + 1).padStart(2, "0")}</span>
                <span className="flex items-center">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    data-testid="resume-bullet-copy-btn"
                    onClick={() => copy(bullet.content, bullet.id, "Bullet")}
                    className="text-slate-400"
                    title="Copy bullet"
                  >
                    {copiedId === bullet.id ? (
                      <Check className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <PinButton insight={bullet} />
                </span>
              </div>
              <h4 className="mt-1 text-sm font-semibold text-slate-200">{bullet.title}</h4>
              <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{bullet.content}</p>
              <EvidencePills insight={bullet} />
            </motion.div>
          ))}
          {bullets.length === 0 && (
            <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground lg:col-span-2">
              No resume bullets yet.
            </p>
          )}
        </div>
      </section>

      <section>
        <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">STAR interview answers</p>
        <div className="mt-3 space-y-4">
          {stars.map((star, idx) => (
            <motion.article
              key={star.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx * 0.05, 0.3), duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
              className="card-hover rounded-xl border border-border bg-card p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <h4 className="font-heading text-base font-semibold tracking-tight text-slate-100">
                  {star.title}
                </h4>
                <span className="flex items-center">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    data-testid="star-answer-copy-btn"
                    onClick={() =>
                      copy(
                        `${star.title}\n\nSITUATION: ${star.situation ?? ""}\nTASK: ${star.task ?? ""}\nACTION: ${star.action ?? ""}\nRESULT: ${star.result ?? ""}`,
                        star.id,
                        "STAR answer",
                      )
                    }
                    className="text-slate-400"
                    title="Copy STAR answer"
                  >
                    {copiedId === star.id ? (
                      <Check className="h-4 w-4 text-emerald-400" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                  <PinButton insight={star} />
                </span>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {STAR_BLOCKS.map((block) => (
                  <div key={block.key} className="rounded-lg border border-border bg-muted/40 p-3">
                    <p className="font-mono text-[11px] uppercase tracking-widest text-emerald-400/90">
                      {block.label}
                    </p>
                    <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{star[block.key]}</p>
                  </div>
                ))}
              </div>
              <EvidencePills insight={star} />
            </motion.article>
          ))}
          {stars.length === 0 && (
            <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
              No STAR answers yet.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
