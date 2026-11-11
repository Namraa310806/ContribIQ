import { motion } from "motion/react";

const LINES: Array<{ text: string; cls: string }> = [
  { text: "$ contribiq analyze --user alexchen-dev", cls: "text-slate-200" },
  { text: "→ fetched 4 repos · 20 contributions", cls: "text-slate-400" },
  { text: "✓ pr#184  Performance/High  impact 92  [FastAPI, Redis]", cls: "text-emerald-400" },
  { text: "✓ pr#233  Security/High    impact 94  [Stripe, PostgreSQL]", cls: "text-emerald-400" },
  { text: "✓ pr#412  Frontend/High    impact 90  [React, TypeScript]", cls: "text-emerald-400" },
  { text: "→ skill graph: Python (High) · React (High) · Redis (High)", cls: "text-cyan-400" },
  { text: "→ 5 resume bullets · 3 STAR answers generated", cls: "text-amber-300" },
  { text: "✓ dossier ready → /r/contribiq-demo-dossier", cls: "text-emerald-400" },
];

// Animated mock of the classification pipeline streaming in real time.
export default function TerminalMock() {
  return (
    <div
      data-testid="landing-terminal-preview-container"
      className="overflow-hidden rounded-xl border border-slate-700/70 bg-[#0A0E16]/90 shadow-2xl shadow-black/40"
    >
      <div className="flex items-center gap-1.5 border-b border-slate-800 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-red-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-amber-500/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/70" />
        <span className="ml-3 font-mono text-xs text-slate-500">contribiq — analysis</span>
      </div>
      <div className="space-y-2 px-5 py-4 font-mono text-[12.5px] leading-relaxed sm:text-[13px]">
        {LINES.map((line, idx) => (
          <motion.p
            key={idx}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.5 + idx * 0.35, duration: 0.3 }}
            className={line.cls}
          >
            {line.text}
          </motion.p>
        ))}
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 1, 0] }}
          transition={{ delay: 0.5 + LINES.length * 0.35, duration: 1, repeat: Infinity }}
          className="inline-block h-4 w-2 translate-y-0.5 bg-emerald-400"
        />
      </div>
    </div>
  );
}
