import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { ChevronDown, ExternalLink, FileSearch } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Contribution, ContributionKind } from "@/types";
import PrEvidenceSheet from "@/components/PrEvidenceSheet";

const TYPE_STYLES: Record<ContributionKind, { label: string; cls: string }> = {
  pr: { label: "PR", cls: "border-indigo-500/30 bg-indigo-500/10 text-indigo-300" },
  issue: { label: "Issue", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
  commit: { label: "Commit", cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
  review: { label: "Review", cls: "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-300" },
};

const COMPLEXITY_DOTS: Record<string, number> = { Low: 1, Medium: 2, High: 3 };

// Repository-eligibility badge: own/controlled-org work is labelled honestly and
// never presented as external open-source collaboration.
function eligibilityBadge(c: Contribution): { label: string; cls: string; title: string } {
  switch (c.eligibility_status) {
    case "ELIGIBLE_EXTERNAL":
      return { label: "external", cls: "border-sky-500/30 bg-sky-500/10 text-sky-300", title: "Independently maintained repository" };
    case "EXCLUDED_SELF_OWNED":
      return { label: "own repo", cls: "border-slate-600/60 bg-slate-700/30 text-slate-400", title: "Owned by you — excluded from open-source scoring" };
    case "EXCLUDED_CONTROLLED_ORGANIZATION":
      return { label: "own org", cls: "border-slate-600/60 bg-slate-700/30 text-slate-400", title: "Organization you belong to — excluded from open-source scoring" };
    case "REVIEW_REQUIRED":
      return { label: "review", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300", title: "Ownership uncertain — manual review advised" };
    case "UNKNOWN":
      return { label: "unverified", cls: "border-slate-500/30 bg-slate-500/10 text-slate-400", title: "Repository ownership could not be verified" };
    default:
      return c.is_own_repo
        ? { label: "own repo", cls: "border-slate-600/60 bg-slate-700/30 text-slate-400", title: "Repo owned by you" }
        : { label: "external", cls: "border-sky-500/30 bg-sky-500/10 text-sky-300", title: "Independent codebase" };
  }
}

function isExternalEligible(c: Contribution): boolean {
  if (c.eligibility_status) return c.eligibility_status === "ELIGIBLE_EXTERNAL";
  return !c.is_own_repo;
}

function isSelfOwned(c: Contribution): boolean {
  if (c.eligibility_status) {
    return (
      c.eligibility_status === "EXCLUDED_SELF_OWNED" ||
      c.eligibility_status === "EXCLUDED_CONTROLLED_ORGANIZATION"
    );
  }
  return c.is_own_repo;
}

function ImpactBar({ score }: { score: number }) {
  const bar =
    score >= 80 ? "bg-emerald-400" : score >= 60 ? "bg-sky-400" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-800">
        <div className={"h-full rounded-full " + bar} style={{ width: `${score}%` }} />
      </div>
      <span className="font-mono text-xs tabular-nums text-slate-300">{score}</span>
    </div>
  );
}

function TypeBadge({ kind }: { kind: ContributionKind }) {
  const style = TYPE_STYLES[kind] ?? TYPE_STYLES.pr;
  return (
    <span
      className={
        "inline-flex w-16 justify-center rounded border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider " +
        style.cls
      }
    >
      {style.label}
    </span>
  );
}

function ComplexityDots({ level }: { level: string }) {
  const count = COMPLEXITY_DOTS[level] ?? 2;
  return (
    <span className="flex items-center gap-1" title={`Complexity: ${level}`}>
      {[1, 2, 3].map((dot) => (
        <span
          key={dot}
          className={"h-1.5 w-1.5 rounded-full " + (dot <= count ? "bg-amber-400" : "bg-slate-700")}
        />
      ))}
    </span>
  );
}

function ContributionRow({
  contribution,
  open,
  onToggle,
  onShowEvidence,
  index,
}: {
  contribution: Contribution;
  open: boolean;
  onToggle: () => void;
  onShowEvidence: () => void;
  index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.4), duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="card-hover overflow-hidden rounded-lg border border-border bg-card"
    >
      <button
        type="button"
        data-testid="contribution-item-row"
        onClick={onToggle}
        className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 text-left sm:grid-cols-[auto_1fr_auto_auto_auto]"
      >
        <TypeBadge kind={contribution.kind} />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium text-slate-200">{contribution.title}</span>
          <span className="block truncate font-mono text-xs text-muted-foreground">
            {contribution.repo}
            {contribution.number ? ` · #${contribution.number}` : ""}
            {" · "}
            <span className="uppercase">{contribution.state}</span>
          </span>
          {(contribution.kind === "pr" || contribution.kind === "review") && (
            <span className="mt-1 flex flex-wrap items-center gap-1">
              {contribution.kind === "pr" && (() => {
                const badge = eligibilityBadge(contribution);
                return (
                  <span
                    className={"rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider " + badge.cls}
                    title={badge.title}
                  >
                    {badge.label}
                  </span>
                );
              })()}
              {contribution.kind === "pr" && contribution.merged && (
                <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-emerald-300">
                  merged
                </span>
              )}
              {contribution.kind === "pr" && contribution.draft && (
                <span className="rounded border border-slate-500/30 bg-slate-500/10 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-slate-400">
                  draft
                </span>
              )}
              {contribution.kind === "pr" && contribution.review_count > 0 && (
                <span
                  className="rounded border border-violet-500/30 bg-violet-500/10 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-violet-300"
                  title={`${contribution.approvals} approvals · ${contribution.change_requests} change requests · ${contribution.reviewers} reviewers`}
                >
                  {contribution.review_count} reviews
                  {contribution.change_requests > 0 ? ` · ${contribution.change_requests} changes` : ""}
                </span>
              )}
              {contribution.kind === "review" && contribution.pr_author && (
                <span className="rounded border border-fuchsia-500/30 bg-fuchsia-500/10 px-1.5 py-px font-mono text-[10px] text-fuchsia-300">
                  on @{contribution.pr_author}
                </span>
              )}
            </span>
          )}
        </span>
        <span className="hidden rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[11px] text-slate-300 sm:inline">
          {contribution.category}
        </span>
        <span className="hidden sm:block">
          <ComplexityDots level={contribution.complexity} />
        </span>
        <span className="flex items-center gap-3">
          <ImpactBar score={contribution.impact_score} />
          <ChevronDown
            className={"h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 " + (open ? "rotate-180" : "")}
          />
        </span>
      </button>

      {open && (
        <div className="border-t border-border bg-muted/40 px-4 py-4">
          <p className="text-sm leading-relaxed text-slate-300">{contribution.summary || "No summary available."}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {contribution.technologies.map((tech) => (
              <span
                key={tech}
                className="rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[11px] text-slate-300"
              >
                {tech}
              </span>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 font-mono text-xs text-muted-foreground">
            <span>+{contribution.additions} / -{contribution.deletions}</span>
            {contribution.changed_files > 0 && <span>{contribution.changed_files} files</span>}
            {contribution.commits_count > 0 && <span>{contribution.commits_count} commits</span>}
            <span>{contribution.comments} comments</span>
            {contribution.review_count > 0 && (
              <span>
                {contribution.review_count} reviews · {contribution.approvals} approvals ·{" "}
                {contribution.change_requests} change requests
              </span>
            )}
            <span>impact {contribution.impact_score}/100</span>
            {contribution.kind === "pr" && contribution.confidence && (
              <span title="Evidence completeness — missing data lowers confidence, never fabricates a verdict">
                confidence {contribution.confidence.toLowerCase()}
                {contribution.ci_status && contribution.ci_status !== "unknown" ? ` · ci ${contribution.ci_status}` : ""}
              </span>
            )}
            {contribution.url && (
              <a
                href={contribution.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-sky-400 hover:text-sky-300"
              >
                View on GitHub <ExternalLink className="h-3 w-3" />
              </a>
            )}
            {contribution.kind === "pr" && contribution.pr_key && contribution.number != null && (
              <button
                type="button"
                data-testid="contribution-pr-evidence-btn"
                onClick={onShowEvidence}
                className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300"
              >
                <FileSearch className="h-3 w-3" /> PR evidence
              </button>
            )}
          </div>
        </div>
      )}
    </motion.div>
  );
}

// Searchable, filterable contribution matrix — filtering happens client-side for instant feedback.
export default function ContributionsTab({
  items,
  total,
  facets,
}: {
  items: Contribution[];
  total: number;
  facets: Record<string, string[]>;
}) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("all");
  const [category, setCategory] = useState("all");
  const [repoCtx, setRepoCtx] = useState("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const [evidencePr, setEvidencePr] = useState<{ repo: string; number: number } | null>(null);

  const filtered = useMemo(
    () =>
      items.filter((c) => {
        if (kind !== "all" && c.kind !== kind) return false;
        if (category !== "all" && c.category !== category) return false;
        if (repoCtx === "own" && !isSelfOwned(c)) return false;
        if (repoCtx === "external" && !isExternalEligible(c)) return false;
        if (q && !`${c.title} ${c.summary} ${c.repo}`.toLowerCase().includes(q.toLowerCase())) return false;
        return true;
      }),
    [items, q, kind, category, repoCtx],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row">
        <Input
          data-testid="contributions-search-input"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search titles, summaries, repos…"
          className="sm:max-w-xs"
        />
        <Select value={kind} onValueChange={(value: string) => setKind(value)}>
          <SelectTrigger data-testid="contributions-type-filter" className="sm:w-44">
            <SelectValue>{(v: string) => (v === "all" ? "All types" : TYPE_STYLES[v as ContributionKind]?.label ?? v)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All types</SelectItem>
            {(facets.kinds ?? []).map((k) => (
              <SelectItem key={k} value={k}>
                {TYPE_STYLES[k as ContributionKind]?.label ?? k}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={category} onValueChange={(value: string) => setCategory(value)}>
          <SelectTrigger data-testid="contributions-category-filter" className="sm:w-44">
            <SelectValue>{(v: string) => (v === "all" ? "All categories" : v)}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All categories</SelectItem>
            {(facets.categories ?? []).map((cat) => (
              <SelectItem key={cat} value={cat}>
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={repoCtx} onValueChange={(value: string) => setRepoCtx(value)}>
          <SelectTrigger data-testid="contributions-repoctx-filter" className="sm:w-40">
            <SelectValue>{(v: string) => (v === "all" ? "All repos" : v === "own" ? "Own repos" : "External repos")}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All repos</SelectItem>
            <SelectItem value="own">Own repos</SelectItem>
            <SelectItem value="external">External repos</SelectItem>
          </SelectContent>
        </Select>
        <span className="ml-auto self-center font-mono text-xs text-muted-foreground">
          {filtered.length} / {total}
        </span>
      </div>

      <div className="space-y-2">
        {filtered.map((contribution, idx) => (
          <ContributionRow
            key={contribution.id}
            contribution={contribution}
            index={idx}
            open={openId === contribution.id}
            onToggle={() => setOpenId(openId === contribution.id ? null : contribution.id)}
            onShowEvidence={() =>
              setEvidencePr({ repo: contribution.repo, number: contribution.number as number })
            }
          />
        ))}
        {filtered.length === 0 && (
          <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
            No contributions match these filters.
          </p>
        )}
      </div>

      <PrEvidenceSheet
        repo={evidencePr?.repo ?? ""}
        number={evidencePr?.number ?? null}
        open={evidencePr != null}
        onOpenChange={(open) => {
          if (!open) setEvidencePr(null);
        }}
      />
    </div>
  );
}
