import { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "motion/react";
import {
  BrainCircuit,
  FileText,
  Github,
  ListChecks,
  Lock,
  ShieldCheck,
  Sparkles,
  Target,
  Zap,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiGet, apiPost } from "@/lib/api";
import { beginSession, useMe } from "@/lib/session";
import TerminalMock from "@/components/TerminalMock";
import { LogoMark } from "@/components/Logo";
import type { AuthUrlResponse, UserPublic } from "@/types";

const HERO_STATS = [
  { value: "100%", label: "Evidence-linked skills" },
  { value: "4x", label: "Faster STAR prep" },
  { value: "0", label: "Fluff in the bullets" },
  { value: "30d", label: "Live recruiter dossier" },
];

const FEATURES = [
  {
    testid: "feature-card-pipeline",
    icon: BrainCircuit,
    title: "AI contribution categorization",
    copy: "Every PR, issue, commit and review is classified by a domain model — Security, Backend, DevOps, Performance — with a complexity grade, impact score and a plain-language summary.",
    span: "lg:col-span-7",
  },
  {
    testid: "feature-card-skills",
    icon: Target,
    title: "Evidence-backed skill matrix",
    copy: "Technologies ranked with High / Medium / Low confidence, each backed by the count, repo diversity and recency of the proof. Click a skill, see the commits.",
    span: "lg:col-span-5",
  },
  {
    testid: "feature-card-star",
    icon: Sparkles,
    title: "STAR interview answer generator",
    copy: "Quantified resume bullets and Situation-Task-Action-Result stories, each linked to the exact pull request that proves them. One click to copy.",
    span: "lg:col-span-5",
  },
  {
    testid: "feature-card-dossier",
    icon: FileText,
    title: "Verified recruiter portfolio",
    copy: "A public, view-only dossier link — auto-expiring after 30 days, revocable any time. Recruiters get signal, not noise, with zero accounts.",
    span: "lg:col-span-7",
  },
];

const PIPELINE_STEPS = [
  { icon: Github, title: "Connect GitHub", copy: "One-click OAuth. Read-only scope; your token never leaves the server." },
  { icon: ListChecks, title: "Collect & classify", copy: "Rate-limit-aware collection, then batched AI classification of every contribution." },
  { icon: Zap, title: "Aggregate & generate", copy: "Skill graph, resume bullets, STAR answers and a recruiter summary — all cited." },
  { icon: ShieldCheck, title: "Share or purge", copy: "Publish an expiring dossier link, or delete every stored byte in one click." },
];

export default function Landing() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: me } = useMe();

  const ghUrl = useQuery({
    queryKey: ["github-url"],
    queryFn: () => apiGet<AuthUrlResponse>("/auth/github-url"),
    staleTime: 5 * 60_000,
  });

  const demo = useMutation({
    mutationFn: () => apiPost<UserPublic>("/auth/demo"),
    onSuccess: async () => {
      await beginSession();
      void queryClient.invalidateQueries();
      navigate("/dashboard");
    },
    onError: () => toast.error("Could not start the demo session — please try again"),
  });

  const continueWithGitHub = () => {
    if (ghUrl.data?.configured && ghUrl.data.url) {
      window.location.href = ghUrl.data.url;
    } else {
      toast.error("GitHub sign-in isn't configured yet — explore the demo profile instead");
    }
  };

  const signedIn = Boolean(me?.user);

  // Failed OAuth round-trips land on /?auth_error=github — say so once, then clean the URL.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("auth_error")) {
      // Defer one tick: the <Toaster> mounts after the routes, so an immediate toast is dropped.
      setTimeout(() => toast.error("GitHub sign-in didn't complete — please try again"), 0);
      window.history.replaceState(null, "", "/");
    }
  }, []);

  return (
    <div className="min-h-svh bg-background">
      {/* Header nav */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
          <div data-testid="nav-brand-logo" className="flex items-center gap-2.5">
            <LogoMark />
            <span className="font-heading text-lg font-bold tracking-tight text-slate-100">ContribIQ</span>
          </div>
          <nav className="hidden items-center gap-6 text-sm text-slate-400 md:flex">
            <a href="#pipeline" className="transition-colors hover:text-white">How it works</a>
            <a href="#features" className="transition-colors hover:text-white">Features</a>
            <Link to="/r/contribiq-demo-dossier" className="transition-colors hover:text-white">
              Sample dossier
            </Link>
          </nav>
          <div className="flex items-center gap-2">
            {signedIn ? (
              <Link
                to="/dashboard"
                data-testid="nav-github-login-btn"
                className={buttonVariants({ size: "sm" }) + " gap-2"}
              >
                Open dashboard <span aria-hidden>→</span>
              </Link>
            ) : (
              <>
                <button
                  type="button"
                  data-testid="nav-github-login-btn"
                  onClick={continueWithGitHub}
                  className={buttonVariants({ size: "sm" }) + " gap-2"}
                >
                  <Github className="h-4 w-4" />
                  Continue with GitHub
                </button>
                <button
                  type="button"
                  data-testid="nav-explore-demo-btn"
                  onClick={() => demo.mutate()}
                  disabled={demo.isPending}
                  className={buttonVariants({ variant: "outline", size: "sm" })}
                >
                  Demo
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Hero — asymmetric split */}
      <section className="relative mx-auto max-w-6xl overflow-hidden px-4 pb-20 pt-16 sm:px-6 sm:pt-24">
        <div
          aria-hidden
          className="pointer-events-none absolute -top-48 left-1/2 h-[520px] w-[820px] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -right-24 top-64 hidden h-80 w-80 rounded-full bg-cyan-400/10 blur-3xl lg:block"
        />
        <div className="relative grid items-center gap-12 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="font-mono text-xs uppercase tracking-widest text-emerald-400"
            >
              AI-powered developer portfolio
            </motion.p>
            <motion.h1
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.08, duration: 0.5 }}
              data-testid="landing-hero-heading"
              className="mt-4 font-heading text-4xl font-bold leading-[1.1] tracking-tight text-slate-100 sm:text-5xl"
            >
              Your GitHub tells what you built.
              <span className="block text-primary">ContribIQ tells what it means.</span>
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.16, duration: 0.5 }}
              className="mt-5 max-w-xl text-lg leading-relaxed text-slate-300"
            >
              Turn raw commit history into professional intelligence: AI-classified contributions, an
              evidence-backed skill profile, interview-ready STAR answers, and a recruiter dossier that
              links every claim to the PR that proves it.
            </motion.p>
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.24, duration: 0.5 }}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              {signedIn ? (
                <Link
                  to="/dashboard"
                  data-testid="landing-hero-github-cta"
                  className={buttonVariants({ size: "lg" }) + " gap-2"}
                >
                  Open dashboard <span aria-hidden>→</span>
                </Link>
              ) : (
                <button
                  type="button"
                  data-testid="landing-hero-github-cta"
                  onClick={continueWithGitHub}
                  className={buttonVariants({ size: "lg" }) + " gap-2"}
                >
                  <Github className="h-5 w-5" />
                  Continue with GitHub
                </button>
              )}
              <button
                type="button"
                data-testid="landing-hero-demo-cta"
                onClick={() => demo.mutate()}
                disabled={demo.isPending}
                className={buttonVariants({ variant: "outline", size: "lg" })}
              >
                {demo.isPending ? "Loading demo…" : "Explore the live demo profile"}
              </button>
            </motion.div>
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.4, duration: 0.5 }}
              className="mt-4 flex items-center gap-2 font-mono text-xs text-muted-foreground"
            >
              <Lock className="h-3.5 w-3.5 text-emerald-500" />
              No repo write permissions needed · 100% read-only analysis
            </motion.p>
          </div>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
            className="lg:col-span-5"
          >
            <TerminalMock />
          </motion.div>
        </div>
      </section>

      {/* Stats strip */}
      <section className="border-y border-slate-800/80 bg-muted/30">
        <div className="mx-auto grid max-w-6xl grid-cols-2 gap-6 px-4 py-10 sm:px-6 lg:grid-cols-4">
          {HERO_STATS.map((stat) => (
            <div key={stat.label}>
              <p className="font-heading text-3xl font-bold tracking-tight text-primary">{stat.value}</p>
              <p className="mt-1 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                {stat.label}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Bento feature grid */}
      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
        <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">The intelligence pipeline</p>
        <h2 className="mt-3 max-w-2xl font-heading text-3xl font-bold tracking-tight text-slate-100">
          Everything a hiring conversation needs, generated from evidence you already shipped.
        </h2>
        <div className="mt-10 grid gap-4 lg:grid-cols-12">
          {FEATURES.map((feature) => (
            <div
              key={feature.testid}
              data-testid={feature.testid}
              className={`card-hover rounded-xl border border-border bg-card p-6 ${feature.span}`}
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <feature.icon className="h-5 w-5" />
              </span>
              <h3 className="mt-4 font-heading text-lg font-semibold tracking-tight text-slate-100">
                {feature.title}
              </h3>
              <p className="mt-2 max-w-prose text-sm leading-relaxed text-slate-300">{feature.copy}</p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section id="pipeline" className="border-t border-slate-800/80 bg-muted/30">
        <div className="mx-auto max-w-6xl scroll-mt-20 px-4 py-20 sm:px-6">
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">How it works</p>
          <h2 className="mt-3 font-heading text-3xl font-bold tracking-tight text-slate-100">
            Four steps. No manual write-ups, ever again.
          </h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {PIPELINE_STEPS.map((step, idx) => (
              <div key={step.title} className="card-hover rounded-xl border border-border bg-card p-5">
                <div className="flex items-center justify-between">
                  <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <step.icon className="h-4.5 w-4.5" />
                  </span>
                  <span className="font-mono text-xs text-slate-600">0{idx + 1}</span>
                </div>
                <h3 className="mt-3 text-sm font-semibold text-slate-200">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-slate-400">{step.copy}</p>
              </div>
            ))}
          </div>
          <div className="mt-10 flex flex-wrap items-center gap-3">
            <button
              type="button"
              data-testid="landing-footer-demo-cta"
              onClick={() => demo.mutate()}
              disabled={demo.isPending}
              className={buttonVariants({ size: "lg" })}
            >
              {demo.isPending ? "Loading demo…" : "Explore the demo profile"}
            </button>
            <Link
              to="/r/contribiq-demo-dossier"
              className={buttonVariants({ variant: "outline", size: "lg" })}
            >
              See a live recruiter dossier
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-800/80">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <div className="flex items-center gap-2.5">
            <LogoMark />
            <div>
              <p className="font-heading text-sm font-bold text-slate-200">ContribIQ</p>
              <p className="font-mono text-xs text-muted-foreground">
                Private by default · read-only OAuth · delete anytime
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-[11px] text-slate-400">
              GitHub Contribution Intelligence
            </Badge>
          </div>
        </div>
      </footer>
    </div>
  );
}
