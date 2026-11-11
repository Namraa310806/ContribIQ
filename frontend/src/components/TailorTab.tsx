import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "motion/react";
import { Briefcase, Check, ChevronDown, Copy, ExternalLink, Loader2, Trash2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, apiDelete, apiGet, apiPost } from "@/lib/api";
import type { Insight, TailoredListResponse, TailoredSet } from "@/types";

const STAR_KEYS = ["situation", "task", "action", "result"] as const;

function errorDetail(err: unknown, fallback: string): string {
  if (err instanceof ApiError && err.body && typeof err.body === "object" && "detail" in err.body) {
    const detail = (err.body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function Evidence({ item }: { item: Insight }) {
  if (item.evidence.length === 0) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-2">
      {item.evidence.map((ev) => (
        <a
          key={ev.contribution_id}
          href={ev.url || undefined}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 font-mono text-[11px] text-sky-300 hover:border-sky-400/50"
        >
          {ev.label}
          {ev.url && <ExternalLink className="h-3 w-3" />}
        </a>
      ))}
    </div>
  );
}

function TailoredSetCard({ set, defaultOpen }: { set: TailoredSet; defaultOpen: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState<string | null>(null);

  const remove = useMutation({
    mutationFn: () => apiDelete<void>(`/tailored/${set.id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tailored"] });
      toast.success("Tailored set deleted");
    },
    onError: () => toast.error("Could not delete this set"),
  });

  const copy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopied((cur) => (cur === id ? null : cur)), 1600);
    } catch {
      toast.error("Clipboard is unavailable in this browser");
    }
  };

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      data-testid="tailored-set-card"
      className="overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="flex items-center gap-3 px-5 py-4">
        <button
          type="button"
          data-testid="tailored-set-toggle"
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Briefcase className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            <span data-testid="tailored-set-title" className="block truncate text-sm font-semibold text-slate-100">
              {set.title}
            </span>
            <span className="block font-mono text-xs text-muted-foreground">
              {set.bullets.length} bullets · {set.stars.length} STAR answers ·{" "}
              {new Date(set.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            </span>
          </span>
          <ChevronDown
            className={"ml-auto h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 " + (open ? "rotate-180" : "")}
          />
        </button>
        <Button
          variant="ghost"
          size="icon-sm"
          data-testid="tailored-set-delete-btn"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="text-slate-500 hover:text-red-300"
          title="Delete this set"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      {open && (
        <div className="space-y-5 border-t border-border px-5 py-5">
          {set.match_summary && (
            <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
              <p className="font-mono text-[11px] uppercase tracking-widest text-emerald-400">Fit for this role</p>
              <p data-testid="tailored-match-summary" className="mt-1.5 text-sm leading-relaxed text-slate-300">
                {set.match_summary}
              </p>
            </div>
          )}

          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">Tailored resume bullets</p>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {set.bullets.map((bullet) => (
                <div key={bullet.id} data-testid="tailored-bullet" className="rounded-lg border border-border bg-muted/40 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-sm font-semibold text-slate-200">{bullet.title}</h4>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      data-testid="tailored-bullet-copy-btn"
                      onClick={() => copy(bullet.content, bullet.id)}
                      className="shrink-0 text-slate-400"
                      title="Copy bullet"
                    >
                      {copied === bullet.id ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                    </Button>
                  </div>
                  <p className="mt-1 text-sm leading-relaxed text-slate-300">{bullet.content}</p>
                  <Evidence item={bullet} />
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">Tailored STAR answers</p>
            <div className="mt-3 space-y-3">
              {set.stars.map((star) => (
                <div key={star.id} data-testid="tailored-star" className="rounded-lg border border-border bg-muted/40 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="font-heading text-sm font-semibold text-slate-100">{star.title}</h4>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      data-testid="tailored-star-copy-btn"
                      onClick={() =>
                        copy(
                          `${star.title}\n\nSITUATION: ${star.situation ?? ""}\nTASK: ${star.task ?? ""}\nACTION: ${star.action ?? ""}\nRESULT: ${star.result ?? ""}`,
                          star.id,
                        )
                      }
                      className="shrink-0 text-slate-400"
                      title="Copy STAR answer"
                    >
                      {copied === star.id ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                    </Button>
                  </div>
                  <dl className="mt-2 grid gap-2 md:grid-cols-2">
                    {STAR_KEYS.map((key) => (
                      <div key={key}>
                        <dt className="font-mono text-[11px] uppercase tracking-widest text-emerald-400/90">{key}</dt>
                        <dd className="mt-0.5 text-sm leading-relaxed text-slate-300">{star[key]}</dd>
                      </div>
                    ))}
                  </dl>
                  <Evidence item={star} />
                </div>
              ))}
            </div>
          </div>

          <details className="group">
            <summary className="cursor-pointer font-mono text-xs text-muted-foreground hover:text-slate-300">
              Show the job description
            </summary>
            <p className="mt-2 whitespace-pre-wrap rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed text-slate-400">
              {set.job_description}
            </p>
          </details>
        </div>
      )}
    </motion.article>
  );
}

// Paste a job description → saved set of role-specific bullets and STAR answers.
export default function TailorTab() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [newestId, setNewestId] = useState<string | null>(null);

  const setsQuery = useQuery({
    queryKey: ["tailored"],
    queryFn: () => apiGet<TailoredListResponse>("/tailored"),
  });
  const sets = setsQuery.data?.items ?? [];

  const create = useMutation({
    mutationFn: () => apiPost<TailoredSet>("/tailored", { title: title.trim(), job_description: description.trim() }),
    onSuccess: (created) => {
      setNewestId(created.id);
      setTitle("");
      setDescription("");
      void queryClient.invalidateQueries({ queryKey: ["tailored"] });
      toast.success(`Tailored for “${created.title}”`);
    },
    onError: (err) => toast.error(errorDetail(err, "Could not tailor insights — please try again")),
  });

  const canSubmit = title.trim().length >= 2 && description.trim().length >= 40 && !create.isPending;

  return (
    <div className="grid gap-6 lg:grid-cols-12">
      <section className="h-fit rounded-xl border border-primary/25 bg-card p-6 lg:sticky lg:top-24 lg:col-span-5">
        <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">Job tailoring</p>
        <h3 className="mt-1 font-heading text-lg font-semibold tracking-tight text-slate-100">
          Rewrite your story for one role
        </h3>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-400">
          Paste a job description. You'll get bullets and STAR answers in that job's language, still
          linked to the PRs that prove them. Each job is saved as its own set.
        </p>
        <div className="mt-5 space-y-3">
          <Input
            data-testid="tailor-title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Role & company, e.g. Senior Backend Engineer · Stripe"
            maxLength={120}
          />
          <Textarea
            data-testid="tailor-description-input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Paste the full job description here…"
            rows={9}
            maxLength={8000}
            className="resize-y text-sm"
          />
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] text-muted-foreground">
              {description.trim().length < 40
                ? `${Math.max(0, 40 - description.trim().length)} more characters needed`
                : `${description.trim().length} / 8000`}
            </span>
            <Button
              data-testid="tailor-submit-btn"
              onClick={() => create.mutate()}
              disabled={!canSubmit}
              className="gap-1.5"
            >
              {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
              {create.isPending ? "Tailoring…" : "Tailor my insights"}
            </Button>
          </div>
          {create.isPending && (
            <p className="font-mono text-[11px] text-muted-foreground">
              Matching your evidence to the role — this usually takes 10–30 seconds.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3 lg:col-span-7">
        <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
          Saved sets · {sets.length}
        </p>
        {sets.map((set, idx) => (
          <TailoredSetCard key={set.id} set={set} defaultOpen={set.id === newestId || (idx === 0 && !newestId)} />
        ))}
        {!setsQuery.isLoading && sets.length === 0 && (
          <p
            data-testid="tailored-empty-state"
            className="rounded-xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground"
          >
            No tailored sets yet. Paste your first job description to get started.
          </p>
        )}
      </section>
    </div>
  );
}
