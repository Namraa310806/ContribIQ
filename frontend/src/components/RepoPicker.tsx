import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FolderGit2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiGet, apiPut } from "@/lib/api";
import { ME_KEY } from "@/lib/session";
import type { ReposResponse } from "@/types";

// Choose which repositories the next analysis fetches. Exclusions only affect future runs.
export default function RepoPicker({ isDemo }: { isDemo: boolean }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Set<string> | null>(null); // excluded set being edited

  const reposQuery = useQuery({
    queryKey: ["repos"],
    queryFn: () => apiGet<ReposResponse>("/repos"),
    enabled: open,
  });
  const items = reposQuery.data?.items ?? [];
  const excluded = draft ?? new Set(items.filter((r) => !r.included).map((r) => r.full_name));

  const save = useMutation({
    mutationFn: () => apiPut<ReposResponse>("/repos/excluded", { excluded: [...excluded] }),
    onSuccess: (data) => {
      queryClient.setQueryData(["repos"], data);
      void queryClient.invalidateQueries({ queryKey: ME_KEY });
      setOpen(false);
      setDraft(null);
      const skipped = data.items.filter((r) => !r.included).length;
      toast.success(
        skipped ? `Saved — ${skipped} ${skipped === 1 ? "repo" : "repos"} will be skipped next run` : "Saved — all repos included",
      );
    },
    onError: () => toast.error("Could not save your repository choices"),
  });

  const toggle = (name: string, include: boolean) => {
    const next = new Set(excluded);
    if (include) next.delete(name);
    else next.add(name);
    setDraft(next);
  };

  const includedCount = items.length - items.filter((r) => excluded.has(r.full_name)).length;

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        data-testid="repo-picker-open-btn"
        onClick={() => {
          setDraft(null);
          setOpen(true);
        }}
        className="gap-1.5"
      >
        <FolderGit2 className="h-4 w-4" />
        Repositories
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Choose repositories to analyze</DialogTitle>
            <DialogDescription>
              Unticked repos are skipped the next time ContribIQ fetches from GitHub. Work that was
              already analyzed stays on your dashboard.
              {isDemo && " The demo profile doesn't fetch from GitHub, so choices here only take effect for real accounts."}
            </DialogDescription>
          </DialogHeader>

          {reposQuery.isLoading ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading repositories…
            </div>
          ) : reposQuery.isError ? (
            <p className="py-6 text-sm text-red-300">Couldn't load your repositories — try again in a moment.</p>
          ) : items.length === 0 ? (
            <p className="py-6 text-sm text-muted-foreground">No repositories found yet.</p>
          ) : (
            <div className="max-h-80 space-y-1 overflow-y-auto pr-1" data-testid="repo-picker-list">
              <div className="flex items-center justify-between pb-2 font-mono text-xs text-muted-foreground">
                <span>
                  {includedCount} of {items.length} included
                  {reposQuery.data?.live ? " · live from GitHub" : ""}
                </span>
                <span className="flex gap-3">
                  <button
                    type="button"
                    data-testid="repo-picker-select-all"
                    className="text-emerald-400 hover:text-emerald-300"
                    onClick={() => setDraft(new Set())}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    data-testid="repo-picker-select-none"
                    className="text-slate-400 hover:text-slate-200"
                    onClick={() => setDraft(new Set(items.map((r) => r.full_name)))}
                  >
                    None
                  </button>
                </span>
              </div>
              {items.map((repo) => {
                const checked = !excluded.has(repo.full_name);
                return (
                  <label
                    key={repo.full_name}
                    data-testid="repo-picker-item"
                    className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-muted/40 px-3 py-2.5 transition-colors duration-150 hover:border-slate-600"
                  >
                    <Checkbox
                      checked={checked}
                      onCheckedChange={(value) => toggle(repo.full_name, Boolean(value))}
                      data-testid="repo-picker-checkbox"
                    />
                    <span className="min-w-0 flex-1">
                      <span className={"block truncate font-mono text-sm " + (checked ? "text-slate-200" : "text-slate-500 line-through")}>
                        {repo.full_name}
                      </span>
                      <span className="block font-mono text-[11px] text-muted-foreground">
                        {repo.language || "—"} · {repo.contribution_count} analyzed
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              data-testid="repo-picker-save-btn"
              onClick={() => save.mutate()}
              disabled={save.isPending || reposQuery.isLoading || items.length === 0}
              className="gap-1.5"
            >
              {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              Save choices
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
