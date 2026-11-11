import { useState } from "react";
import { motion } from "motion/react";
import { ChevronDown, ExternalLink } from "lucide-react";
import type { Contribution, Skill, SkillConfidence } from "@/types";

const CONFIDENCE_STYLES: Record<SkillConfidence, { cls: string; bar: string }> = {
  High: { cls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300", bar: "bg-emerald-400" },
  Medium: { cls: "border-sky-500/40 bg-sky-500/10 text-sky-300", bar: "bg-sky-400" },
  Low: { cls: "border-slate-600 bg-secondary text-slate-300", bar: "bg-slate-500" },
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// Ranked competency matrix — click a skill to reveal the exact contributions that prove it.
export default function SkillsTab({
  skills,
  contributions,
}: {
  skills: Skill[];
  contributions: Contribution[];
}) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-2">
      {skills.map((skill, idx) => {
        const style = CONFIDENCE_STYLES[skill.confidence] ?? CONFIDENCE_STYLES.Low;
        const backing = contributions
          .filter((c) => c.technologies.includes(skill.name))
          .slice(0, 6);
        const isOpen = open === skill.name;
        return (
          <motion.div
            key={skill.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: Math.min(idx * 0.04, 0.4), duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="card-hover overflow-hidden rounded-lg border border-border bg-card"
          >
            <button
              type="button"
              data-testid="skill-item-card"
              onClick={() => setOpen(isOpen ? null : skill.name)}
              className="w-full px-4 py-3.5 text-left"
            >
              <div className="flex items-center gap-3">
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-200">{skill.name}</span>
                <span
                  className={
                    "rounded border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider " + style.cls
                  }
                >
                  {skill.confidence}
                </span>
                <ChevronDown
                  className={"h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 " + (isOpen ? "rotate-180" : "")}
                />
              </div>
              <div className="mt-2.5 flex items-center gap-3">
                <div
                  data-testid="skill-confidence-progress-bar"
                  className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800"
                >
                  <motion.div
                    className={"h-full rounded-full " + style.bar}
                    initial={{ width: 0 }}
                    animate={{ width: `${skill.score}%` }}
                    transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                  />
                </div>
                <span className="font-mono text-xs tabular-nums text-slate-400">{skill.score}</span>
              </div>
              <p className="mt-2 font-mono text-xs text-muted-foreground">
                {skill.evidence_count} {skill.evidence_count === 1 ? "proof" : "proofs"} · {skill.repo_count}{" "}
                {skill.repo_count === 1 ? "repo" : "repos"} · last used {formatDate(skill.last_used_at)}
              </p>
            </button>

            {isOpen && (
              <div className="border-t border-border bg-muted/40 px-4 py-3">
                {backing.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Aggregated from repository language and topic metadata.</p>
                ) : (
                  <ul className="space-y-2">
                    {backing.map((c) => (
                      <li key={c.id} className="flex items-center gap-2 text-sm">
                        <span className="font-mono text-[11px] uppercase text-muted-foreground">{c.kind}</span>
                        <span className="min-w-0 flex-1 truncate text-slate-300">{c.title}</span>
                        {c.url && (
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noreferrer"
                            className="shrink-0 text-sky-400 hover:text-sky-300"
                            title="View on GitHub"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </motion.div>
        );
      })}
      {skills.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          No skills yet — run an analysis to build the skill graph.
        </p>
      )}
    </div>
  );
}
