import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileCode2, MessageSquare, GitPullRequest, CheckCircle2 } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiGet } from "@/lib/api";
import type { PrCheck, PrComment, PrDetailResponse, PrFile, PrReview } from "@/types";

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Chip({ children, cls = "border-border bg-secondary text-slate-300" }: { children: React.ReactNode; cls?: string }) {
  return (
    <span className={"inline-flex items-center rounded border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider " + cls}>
      {children}
    </span>
  );
}

function stateChip(state: string, merged?: boolean): string {
  if (merged || state === "merged") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (state === "open") return "border-sky-500/30 bg-sky-500/10 text-sky-300";
  return "border-slate-500/30 bg-slate-500/10 text-slate-400";
}

function conclusionChip(check: PrCheck): { label: string; cls: string } {
  const c = (check.conclusion || check.status || "").toLowerCase();
  if (["success", "neutral", "skipped"].includes(c))
    return { label: c, cls: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  if (["failure", "error", "cancelled", "timed_out", "action_required"].includes(c))
    return { label: c, cls: "border-rose-500/30 bg-rose-500/10 text-rose-300" };
  return { label: c || "unknown", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
}

function FileRow({ file }: { file: PrFile }) {
  return (
    <details className="group rounded-md border border-border bg-card/60">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs">
        <span className="min-w-0 flex-1 truncate font-mono text-slate-300" title={file.path}>
          {file.path}
        </span>
        <Chip>{file.status}</Chip>
        <Chip>{file.category}</Chip>
        <span className="font-mono text-[11px] text-emerald-400">+{file.additions}</span>
        <span className="font-mono text-[11px] text-rose-400">−{file.deletions}</span>
      </summary>
      {file.patch_available ? (
        <pre className="max-h-80 overflow-auto border-t border-border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed text-slate-300">
          {file.patch}
          {file.patch_truncated && (
            <span className="mt-2 block text-amber-400/80">… patch truncated at ingest (PATCH_MAX_CHARS)</span>
          )}
        </pre>
      ) : (
        <p className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">
          No patch captured (binary or too large) — diff stats only.
        </p>
      )}
    </details>
  );
}

function ReviewRow({ review }: { review: PrReview }) {
  const st = (review.state || "").toLowerCase();
  const cls =
    st === "approved"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : st === "changes_requested"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
        : "border-slate-500/30 bg-slate-500/10 text-slate-400";
  return (
    <div className="rounded-md border border-border bg-card/60 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-200">@{review.reviewer_login}</span>
        <Chip cls={cls}>{review.state.toLowerCase().replace(/_/g, " ")}</Chip>
        <span className="font-mono text-[10px] text-muted-foreground">{fmtDate(review.submitted_at)}</span>
        {review.html_url && (
          <a href={review.html_url} target="_blank" rel="noreferrer" className="ml-auto text-sky-400 hover:text-sky-300">
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {review.body && <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{review.body}</p>}
    </div>
  );
}

function CommentRow({ comment }: { comment: PrComment }) {
  return (
    <div className="rounded-md border border-border bg-card/60 p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-200">@{comment.user_login}</span>
        <Chip>{comment.kind === "review" ? "review comment" : "conversation"}</Chip>
        {comment.kind === "review" && comment.path && (
          <span className="font-mono text-[10px] text-muted-foreground">
            {comment.path}
            {comment.line ? `:${comment.line}` : ""}
          </span>
        )}
        <span className="font-mono text-[10px] text-muted-foreground">{fmtDate(comment.created_at)}</span>
        {comment.html_url && (
          <a href={comment.html_url} target="_blank" rel="noreferrer" className="ml-auto text-sky-400 hover:text-sky-300">
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {comment.body && <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">{comment.body}</p>}
    </div>
  );
}

function CheckRow({ check }: { check: PrCheck }) {
  const { label, cls } = conclusionChip(check);
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-card/60 px-3 py-2 text-xs">
      <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-slate-500" />
      <span className="min-w-0 flex-1 truncate font-mono text-slate-300" title={check.name}>
        {check.name}
      </span>
      <Chip>{check.source.replace(/_/g, " ")}</Chip>
      <Chip cls={cls}>{label}</Chip>
      {check.url && (
        <a href={check.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300">
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  );
}

// Slide-over evidence panel for one authored PR — the recruiter promise:
// open a PR, see the implementation, inspect maintainer feedback.
export default function PrEvidenceSheet({
  repo,
  number,
  open,
  onOpenChange,
}: {
  repo: string;
  number: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [fileFilter, setFileFilter] = useState("");
  const query = useQuery({
    queryKey: ["pr-evidence", repo, number],
    queryFn: () => apiGet<PrDetailResponse>(`/prs?repo=${encodeURIComponent(repo)}&number=${number}`),
    enabled: open && Boolean(repo) && number != null,
    staleTime: 60_000,
  });

  const data = query.data;
  const pr = data?.pr;
  const files = (data?.files ?? []).filter((f) => !fileFilter || f.path.toLowerCase().includes(fileFilter.toLowerCase()));
  const reviews = data?.reviews ?? [];
  const comments = data?.comments ?? [];
  const checks = data?.checks ?? [];
  const outcome = pr?.outcome ?? {};

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 sm:max-w-2xl">
        <SheetHeader className="border-b border-border pb-3">
          <SheetTitle className="flex flex-wrap items-center gap-2 pr-8 text-base">
            <GitPullRequest className="h-4 w-4 text-indigo-400" />
            <span className="font-mono text-xs text-muted-foreground">
              {repo}
              {pr?.number != null ? `#${pr.number}` : number != null ? `#${number}` : ""}
            </span>
            {pr && <Chip cls={stateChip(pr.state, pr.merged)}>{pr.merged ? "merged" : pr.state || "unknown"}</Chip>}
            {pr?.draft && <Chip>draft</Chip>}
            {outcome.reverted && (
              <Chip cls="border-rose-500/30 bg-rose-500/10 text-rose-300" >
                reverted{outcome.revert_detected_via === "search" ? " (search)" : ""}
              </Chip>
            )}
            {(outcome.superseded_by?.length ?? 0) > 0 && <Chip cls="border-amber-500/30 bg-amber-500/10 text-amber-300">superseded</Chip>}
          </SheetTitle>
          <SheetDescription className="text-left text-sm text-slate-200">
            {pr?.title ?? "Loading PR evidence…"}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-4 py-3">
          {query.isLoading && <p className="py-8 text-center text-sm text-muted-foreground">Fetching evidence…</p>}
          {query.isError && (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              Evidence unavailable — run an analysis first, or this PR predates evidence ingestion.
            </p>
          )}

          {data && pr && (
            <div className="space-y-4">
              {/* stats strip */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted-foreground">
                <span className="text-emerald-400">+{pr.additions}</span>
                <span className="text-rose-400">−{pr.deletions}</span>
                <span>{pr.changed_files} files</span>
                <span>{pr.commits_count} commits</span>
                <span>{pr.comment_count} comments</span>
                <span>
                  {pr.review_summary && typeof pr.review_summary === "object"
                    ? `${(pr.review_summary as Record<string, number>).review_count ?? 0} reviews`
                    : "0 reviews"}
                </span>
                <span>ci {pr.ci_status}</span>
                <span>evidence {pr.evidence_status}</span>
                {pr.html_url && (
                  <a href={pr.html_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 text-sky-400 hover:text-sky-300">
                    GitHub <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>

              {pr.body && (
                <p className="whitespace-pre-wrap rounded-md border border-border bg-card/60 p-3 text-xs leading-relaxed text-slate-300">
                  {pr.body}
                </p>
              )}

              {pr.linked_issues.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">linked issues</span>
                  {pr.linked_issues.map((i) => (
                    <a key={i.number} href={i.url} target="_blank" rel="noreferrer" className="text-sky-400 hover:text-sky-300">
                      #{i.number} {i.title}
                    </a>
                  ))}
                </div>
              )}

              {pr.evidence_errors.length > 0 && (
                <p className="rounded-md border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300/90">
                  Partial evidence: {pr.evidence_errors.join(" · ")}
                </p>
              )}

              <Tabs defaultValue="files">
                <TabsList>
                  <TabsTrigger value="files" className="gap-1.5">
                    <FileCode2 className="h-3.5 w-3.5" /> Files ({files.length})
                  </TabsTrigger>
                  <TabsTrigger value="reviews" className="gap-1.5">
                    <GitPullRequest className="h-3.5 w-3.5" /> Reviews ({reviews.length})
                  </TabsTrigger>
                  <TabsTrigger value="comments" className="gap-1.5">
                    <MessageSquare className="h-3.5 w-3.5" /> Comments ({comments.length})
                  </TabsTrigger>
                  <TabsTrigger value="checks">Checks ({checks.length})</TabsTrigger>
                </TabsList>

                <TabsContent value="files" className="mt-3 space-y-2">
                  <input
                    value={fileFilter}
                    onChange={(e) => setFileFilter(e.target.value)}
                    placeholder="Filter files…"
                    className="w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-muted-foreground"
                  />
                  {files.map((f) => (
                    <FileRow key={f.path} file={f} />
                  ))}
                  {files.length === 0 && (
                    <p className="py-6 text-center text-xs text-muted-foreground">No changed files recorded.</p>
                  )}
                </TabsContent>

                <TabsContent value="reviews" className="mt-3 space-y-2">
                  {reviews.map((r, i) => (
                    <ReviewRow key={r.review_id ?? i} review={r} />
                  ))}
                  {reviews.length === 0 && (
                    <p className="py-6 text-center text-xs text-muted-foreground">No reviews recorded.</p>
                  )}
                </TabsContent>

                <TabsContent value="comments" className="mt-3 space-y-2">
                  {comments.map((c, i) => (
                    <CommentRow key={c.html_url || i} comment={c} />
                  ))}
                  {comments.length === 0 && (
                    <p className="py-6 text-center text-xs text-muted-foreground">No comments recorded.</p>
                  )}
                </TabsContent>

                <TabsContent value="checks" className="mt-3 space-y-2">
                  {checks.map((c, i) => (
                    <CheckRow key={`${c.name}-${i}`} check={c} />
                  ))}
                  {checks.length === 0 && (
                    <p className="py-6 text-center text-xs text-muted-foreground">
                      No CI checks on the head commit — unknown, not failed.
                    </p>
                  )}
                </TabsContent>
              </Tabs>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
