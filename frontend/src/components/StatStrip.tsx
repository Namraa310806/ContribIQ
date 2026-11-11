import { motion } from "motion/react";
import type { OverviewStats } from "@/types";

// Completed-state summary strip above the workbench tabs.
export default function StatStrip({ stats }: { stats: OverviewStats }) {
  const cards = [
    {
      testid: "stat-card-authored-prs",
      label: "Authored PRs",
      value: String(stats.authored_prs),
      sub: `${stats.external_prs} external · ${stats.merged_prs} merged`,
    },
    {
      testid: "stat-card-prs-reviewed",
      label: "PRs reviewed",
      value: String(stats.prs_reviewed),
      sub: "collaboration evidence",
    },
    {
      testid: "stat-card-collaboration",
      label: "Collaboration",
      value: `${stats.collaboration_score}/100`,
      sub: "review & feedback index",
    },
    {
      testid: "stat-card-consistency",
      label: "Consistency",
      value: `${stats.consistency_score}/100`,
      sub: `${stats.repos_count} repos · sustained activity`,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card, idx) => (
        <motion.div
          key={card.testid}
          data-testid={card.testid}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: idx * 0.06, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
          className="card-hover rounded-xl border border-border bg-card p-4 sm:p-5"
        >
          <p className="font-mono text-[11px] uppercase tracking-widest text-muted-foreground">
            {card.label}
          </p>
          <p className="mt-2 truncate font-heading text-2xl font-bold tracking-tight text-slate-100">
            {card.value}
          </p>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{card.sub}</p>
        </motion.div>
      ))}
    </div>
  );
}
