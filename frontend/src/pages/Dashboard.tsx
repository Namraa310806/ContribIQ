import { useEffect, useRef } from "react";
import { Navigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Github, RefreshCw } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import AppHeader from "@/components/AppHeader";
import AnalysisPipeline from "@/components/AnalysisPipeline";
import StatStrip from "@/components/StatStrip";
import ContributionsTab from "@/components/ContributionsTab";
import SkillsTab from "@/components/SkillsTab";
import InsightsTab from "@/components/InsightsTab";
import RepoPicker from "@/components/RepoPicker";
import TailorTab from "@/components/TailorTab";
import { apiGet, apiPost } from "@/lib/api";
import { useMe } from "@/lib/session";
import type {
  AnalysisStatusResponse,
  ContributionPage,
  InsightsResponse,
  OverviewStats,
  SkillsResponse,
  StartAnalysisResponse,
} from "@/types";

export default function Dashboard() {
  const { data: me, isLoading: meLoading } = useMe();
  const queryClient = useQueryClient();

  const jobQuery = useQuery({
    queryKey: ["job"],
    queryFn: () => apiGet<AnalysisStatusResponse>("/analysis/status"),
    refetchInterval: (query) => {
      const job = query.state.data?.job;
      return job && (job.status === "queued" || job.status === "running") ? 2000 : false;
    },
  });
  const job = jobQuery.data?.job ?? null;
  const jobActive = Boolean(job && (job.status === "queued" || job.status === "running"));

  const overviewQuery = useQuery({ queryKey: ["overview"], queryFn: () => apiGet<OverviewStats>("/overview") });
  const contributionsQuery = useQuery({
    queryKey: ["contributions"],
    queryFn: () => apiGet<ContributionPage>("/contributions?limit=500"),
  });
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: () => apiGet<SkillsResponse>("/skills") });
  const insightsQuery = useQuery({ queryKey: ["insights"], queryFn: () => apiGet<InsightsResponse>("/insights") });

  const startAnalysis = useMutation({
    mutationFn: () => apiPost<StartAnalysisResponse>("/analysis/start"),
    onSuccess: (data) => {
      queryClient.setQueryData(["job"], { job: data.job });
      toast.success("Analysis started — the pipeline is running");
    },
    onError: () => toast.error("Could not start the analysis"),
  });

  // When a job flips to completed/failed, refresh everything it produced.
  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    if (!job) return;
    if (prevStatus.current && prevStatus.current !== job.status && !jobActive) {
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["contributions"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      void queryClient.invalidateQueries({ queryKey: ["insights"] });
      if (job.status === "completed") toast.success("Analysis complete — intelligence refreshed");
      if (job.status === "failed") toast.error(job.error ?? "Analysis failed");
    }
    prevStatus.current = job.status;
  }, [job, jobActive, queryClient]);

  if (meLoading) {
    return (
      <div className="min-h-svh bg-background">
        <div className="mx-auto max-w-6xl animate-pulse px-4 py-10 sm:px-6">
          <div className="h-16" />
          <div className="mt-8 h-40 rounded-xl bg-card" />
          <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-xl bg-card" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!me?.user) return <Navigate to="/" replace />;
  const user = me.user;
  const overview = overviewQuery.data ?? null;

  return (
    <div className="min-h-svh bg-background">
      <AppHeader user={user} />
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
        {/* Analysis state area */}
        {jobActive && job ? (
          <AnalysisPipeline job={job} />
        ) : job && job.status === "failed" ? (
          <AnalysisPipeline job={job} />
        ) : overview && !overview.has_data ? (
          <section className="rounded-xl border border-primary/25 bg-card p-8 sm:p-10">
            <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
              Intelligence pipeline
            </p>
            <h2 className="mt-2 font-heading text-2xl font-bold tracking-tight text-slate-100">
              {user.has_github_token
                ? "Analyze your GitHub history"
                : user.is_demo
                  ? "Run the pipeline on this demo profile"
                  : "Your intelligence pipeline is ready"}
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
              {user.has_github_token
                ? "We'll fetch your public contributions, classify them with AI, aggregate your skill graph and generate cited insights. Incremental syncs only process new work."
                : user.is_demo
                  ? "This demo profile ships pre-analyzed. Re-running the pipeline re-aggregates the skill graph and regenerates the insights from its stored contributions."
                  : "Connect GitHub and run the pipeline to classify your contributions, build your skill graph and generate insights."}
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <Button
                size="lg"
                data-testid="dashboard-analyze-github-btn"
                onClick={() => startAnalysis.mutate()}
                disabled={startAnalysis.isPending}
                className="gap-2"
              >
                {user.has_github_token || user.is_demo ? <RefreshCw className="h-5 w-5" /> : <Github className="h-5 w-5" />}
                Analyze My GitHub
              </Button>
              <RepoPicker isDemo={user.is_demo} />
            </div>
          </section>
        ) : job && job.status === "completed" && job.stats && Object.keys(job.stats).length ? (
          <AnalysisPipeline job={job} />
        ) : null}

        {/* Workbench — only meaningful once data exists */}
        {overview?.has_data && (
          <>
            <StatStrip stats={overview} />
            <div className="flex flex-wrap items-center justify-end gap-2">
              <RepoPicker isDemo={user.is_demo} />
              <Button
                variant="outline"
                size="sm"
                data-testid="dashboard-rerun-analysis-btn"
                onClick={() => startAnalysis.mutate()}
                disabled={startAnalysis.isPending || jobActive}
                className="gap-1.5"
                title="Re-run the intelligence pipeline"
              >
                <RefreshCw className="h-4 w-4" />
                Re-run analysis
              </Button>
            </div>

            <Tabs defaultValue="contributions">
              <TabsList>
                <TabsTrigger value="contributions" data-testid="tab-trigger-contributions">
                  Contributions
                </TabsTrigger>
                <TabsTrigger value="skills" data-testid="tab-trigger-skills">
                  Skills
                </TabsTrigger>
                <TabsTrigger value="insights" data-testid="tab-trigger-insights">
                  Insights
                </TabsTrigger>
                <TabsTrigger value="tailor" data-testid="tab-trigger-tailor">
                  Job tailoring
                </TabsTrigger>
              </TabsList>
              <TabsContent value="contributions" className="mt-4">
                <ContributionsTab
                  items={contributionsQuery.data?.items ?? []}
                  total={contributionsQuery.data?.total ?? 0}
                  facets={contributionsQuery.data?.facets ?? {}}
                />
              </TabsContent>
              <TabsContent value="skills" className="mt-4">
                <SkillsTab
                  skills={skillsQuery.data?.items ?? []}
                  contributions={contributionsQuery.data?.items ?? []}
                />
              </TabsContent>
              <TabsContent value="insights" className="mt-4">
                <InsightsTab insights={insightsQuery.data?.items ?? []} jobActive={jobActive} />
              </TabsContent>
              <TabsContent value="tailor" className="mt-4">
                <TailorTab />
              </TabsContent>
            </Tabs>
          </>
        )}

        {/* Never gate the shell on a fetch: with no backend the page still renders. */}
        {overviewQuery.isError && !overview?.has_data && !jobActive && (
          <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Intelligence data is unavailable right now — the rest of the app still works.
          </p>
        )}

        <p className="pt-4 text-center">
          <a
            href="/settings"
            data-testid="dashboard-settings-link"
            className={buttonVariants({ variant: "link", size: "sm" })}
          >
            Manage share links & privacy →
          </a>
        </p>
      </main>
    </div>
  );
}
