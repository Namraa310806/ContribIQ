import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { BadgeCheck, Download, ExternalLink, Fingerprint, LinkIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import type { PublicRecruiterView } from "@/types";

const CONFIDENCE_BAR: Record<string, string> = {
  High: "bg-emerald-400",
  Medium: "bg-sky-400",
  Low: "bg-slate-500",
};

function KindBadge({ kind }: { kind: string }) {
  const label = kind === "pr" ? "PR" : kind.charAt(0).toUpperCase() + kind.slice(1);
  return (
    <span className="inline-flex justify-center rounded border border-border bg-secondary px-2 py-0.5 font-mono text-[11px] uppercase tracking-wider text-slate-300">
      {label}
    </span>
  );
}

// Public, view-only recruiter dossier — no auth, no site chrome, high-signal.
export default function RecruiterView() {
  const { token } = useParams<{ token: string }>();

  const dossierQuery = useQuery({
    queryKey: ["recruiter", token],
    queryFn: () => apiGet<PublicRecruiterView>(`/share/${token}`),
    enabled: Boolean(token),
    retry: false,
  });

  const error = dossierQuery.error;
  const dossier = dossierQuery.data ?? null;

  // Browser print → "Save as PDF". The document title becomes the suggested file name.
  const downloadPdf = () => {
    const previous = document.title;
    if (dossier) document.title = `${dossier.name} — ContribIQ dossier`;
    window.addEventListener("afterprint", () => (document.title = previous), { once: true });
    window.print();
  };

  return (
    <div className="print-root min-h-svh bg-background">
      <main className="print-doc mx-auto max-w-4xl px-4 py-12 sm:px-6">
        {dossierQuery.isLoading && (
          <div className="animate-pulse space-y-6">
            <div className="h-24 rounded-xl bg-card" />
            <div className="h-48 rounded-xl bg-card" />
            <div className="h-64 rounded-xl bg-card" />
          </div>
        )}

        {!dossierQuery.isLoading && (error || !dossier) && (
          <section className="mx-auto mt-16 max-w-md rounded-xl border border-border bg-card p-8 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary text-slate-400">
              <LinkIcon className="h-5 w-5" />
            </span>
            <h1 className="mt-4 font-heading text-xl font-bold tracking-tight text-slate-100">
              This dossier link is no longer available
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-slate-400">
              The link may have expired or been revoked by its owner. Ask the candidate for a fresh
              link — they can regenerate one in seconds.
            </p>
          </section>
        )}

        {dossier && (
          <div className="space-y-8">
            {/* Candidate hero */}
            <header className="flex flex-col gap-5 sm:flex-row sm:items-center">
              {dossier.avatar_url ? (
                <img
                  src={dossier.avatar_url}
                  alt={dossier.login}
                  className="h-20 w-20 rounded-full border border-slate-700 object-cover"
                />
              ) : (
                <span className="flex h-20 w-20 items-center justify-center rounded-full bg-secondary font-heading text-2xl font-bold text-slate-300">
                  {(dossier.name || dossier.login).slice(0, 1).toUpperCase()}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h1
                    data-testid="recruiter-candidate-name"
                    className="font-heading text-2xl font-bold tracking-tight text-slate-100"
                  >
                    {dossier.name}
                  </h1>
                  <span className="inline-flex items-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-[11px] uppercase tracking-widest text-emerald-300">
                    <BadgeCheck className="h-3.5 w-3.5" /> Verified by ContribIQ
                  </span>
                  {dossier.is_demo && (
                    <Badge variant="outline" className="border-amber-500/40 font-mono text-[11px] text-amber-300">
                      Demo profile
                    </Badge>
                  )}
                </div>
                <p className="mt-1 font-mono text-sm text-muted-foreground">
                  @{dossier.login}
                  {dossier.profile_url && (
                    <>
                      {" · "}
                      <a
                        href={dossier.profile_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-sky-400 hover:text-sky-300"
                      >
                        GitHub profile
                      </a>
                    </>
                  )}
                </p>
              </div>
              <div className="flex gap-6 font-mono text-xs text-muted-foreground">
                <div>
                  <p className="text-xl font-bold text-slate-100">{dossier.stats.total_contributions ?? 0}</p>
                  contributions
                </div>
                <div>
                  <p className="text-xl font-bold text-slate-100">{dossier.stats.merged_prs ?? 0}</p>
                  merged PRs
                </div>
                <div>
                  <p className="text-xl font-bold text-slate-100">{dossier.stats.avg_impact ?? 0}</p>
                  avg impact
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                data-testid="recruiter-download-pdf-btn"
                onClick={downloadPdf}
                className="no-print gap-1.5 self-start sm:self-center"
              >
                <Download className="h-4 w-4" />
                Download PDF
              </Button>
            </header>

            {/* Executive AI summary */}
            {dossier.summary && (
              <motion.section
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="rounded-xl border border-primary/25 bg-card p-6"
              >
                <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
                  Executive summary
                </p>
                <div
                  data-testid="recruiter-executive-summary"
                  className="mt-3 space-y-3 text-sm leading-relaxed text-slate-300"
                >
                  {dossier.summary.split("\n\n").map((para, idx) => (
                    <p key={idx}>{para}</p>
                  ))}
                </div>
              </motion.section>
            )}

            {/* Verified skills */}
            <section>
              <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
                Verified skills & confidence
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {dossier.skills.map((skill) => (
                  <div
                    key={skill.name}
                    data-testid="recruiter-verified-skill-pill"
                    className="card-hover rounded-lg border border-border bg-card px-4 py-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-slate-200">{skill.name}</span>
                      <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                        {skill.confidence}
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className={"print-keep-bg h-full rounded-full " + (CONFIDENCE_BAR[skill.confidence] ?? CONFIDENCE_BAR.Low)}
                        style={{ width: `${skill.score}%` }}
                      />
                    </div>
                    <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                      {skill.evidence_count} proofs
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {/* Evidence highlights */}
            <section>
              <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
                Evidence & impact highlights
              </p>
              <div className="mt-4 space-y-3">
                {dossier.highlights.map((item) => (
                  <article
                    key={item.contribution_id}
                    data-testid="recruiter-pinned-pr-card"
                    className="card-hover rounded-lg border border-border bg-card p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <KindBadge kind={item.kind} />
                          <span className="truncate font-mono text-xs text-muted-foreground">{item.repo}</span>
                        </div>
                        <h3 className="mt-1.5 text-sm font-semibold text-slate-200">{item.title}</h3>
                        <p className="mt-1 text-sm leading-relaxed text-slate-400">{item.summary}</p>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-2">
                        <span className="font-mono text-sm font-bold text-emerald-400">{item.impact_score}</span>
                        {item.url && (
                          <a
                            data-testid="recruiter-pr-github-link"
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-xs text-sky-400 hover:text-sky-300"
                          >
                            proof <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <footer className="flex items-center justify-between border-t border-slate-800/80 pt-6 pb-4 font-mono text-xs text-muted-foreground">
              <span className="flex items-center gap-2">
                <Fingerprint className="h-3.5 w-3.5 text-emerald-500" />
                Expires {new Date(dossier.expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
              </span>
              <span>
                Powered by <Link to="/" className="text-emerald-400 hover:text-emerald-300">ContribIQ</Link>
              </span>
            </footer>
            <p className="print-only hidden font-mono text-[10px]">
              Verified dossier · {window.location.href} · printed {new Date().toLocaleDateString()}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
