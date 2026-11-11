import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Check, Copy, Link2, Loader2, LogOut, ShieldAlert, Trash2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import AppHeader from "@/components/AppHeader";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { ME_KEY, endSession, useMe } from "@/lib/session";
import type { DeleteDataResponse, ShareInfo, ShareStateResponse, UserPublic } from "@/types";

const EXPIRY_OPTIONS = [
  { days: "7", label: "7 days" },
  { days: "30", label: "30 days" },
  { days: "90", label: "90 days" },
];

export default function Settings() {
  const { data: me, isLoading: meLoading } = useMe();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [expiry, setExpiry] = useState("30");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const shareQuery = useQuery({
    queryKey: ["share"],
    queryFn: () => apiGet<ShareStateResponse>("/share"),
  });
  const share = shareQuery.data?.share ?? null;
  const shareUrl = share ? `${window.location.origin}${share.path}` : "";

  const createShare = useMutation({
    mutationFn: () => apiPost<ShareInfo>("/share", { days: Number(expiry) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["share"] });
      toast.success("Public dossier link created");
    },
    onError: () => toast.error("Could not create the share link"),
  });

  const revokeShare = useMutation({
    mutationFn: () => apiDelete<void>("/share"),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["share"] });
      toast.success("Dossier link revoked");
    },
    onError: () => toast.error("Could not revoke the link"),
  });

  const deleteData = useMutation({
    mutationFn: () => apiDelete<DeleteDataResponse>("/user/data"),
    onSuccess: (result) => {
      setConfirmOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["contributions"] });
      void queryClient.invalidateQueries({ queryKey: ["skills"] });
      void queryClient.invalidateQueries({ queryKey: ["insights"] });
      void queryClient.invalidateQueries({ queryKey: ["tailored"] });
      toast.success(
        `Deleted ${Object.values(result.deleted).reduce((a, b) => a + b, 0)} stored records — your account stays active`,
      );
    },
    onError: () => toast.error("Could not delete the data"),
  });

  const signOut = async () => {
    await endSession();
    navigate("/", { replace: true });
  };

  const autoSync = useMutation({
    mutationFn: (enabled: boolean) => apiPut<UserPublic>("/settings/auto-sync", { enabled }),
    onSuccess: (updated) => {
      queryClient.setQueryData(ME_KEY, { user: updated });
      toast.success(updated.auto_sync ? "Weekly auto-sync is on" : "Weekly auto-sync is off");
    },
    onError: () => toast.error("Could not update auto-sync"),
  });

  const copyShare = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Dossier link copied");
      setTimeout(() => setCopied(false), 1600);
    } catch {
      toast.error("Clipboard is unavailable in this browser");
    }
  };

  if (meLoading) {
    return (
      <div className="min-h-svh bg-background">
        <div className="mx-auto h-16 max-w-6xl animate-pulse px-4 sm:px-6" />
      </div>
    );
  }
  if (!me?.user) return <Navigate to="/" replace />;
  const user = me.user;

  return (
    <div className="min-h-svh bg-background">
      <AppHeader user={user} />
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
          Account & privacy management
        </p>
        <h1 className="mt-2 font-heading text-2xl font-bold tracking-tight text-slate-100">
          Settings
        </h1>

        <div className="mt-8 grid gap-6 lg:grid-cols-12">
          {/* Share link manager */}
          <section className="rounded-xl border border-border bg-card p-6 lg:col-span-7">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Link2 className="h-5 w-5" />
              </span>
              <div>
                <h2 className="font-heading text-lg font-semibold tracking-tight text-slate-100">
                  Recruiter dossier link
                </h2>
                <p className="text-sm text-slate-400">
                  A public, view-only page with your verified skills and evidence.
                </p>
              </div>
            </div>

            {share ? (
              <div className="mt-6 space-y-4">
                <div>
                  <p className="font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    {`Active link · expires ${new Date(share.expires_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}`}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <Input
                      readOnly
                      data-testid="settings-share-link-input"
                      value={shareUrl}
                      className="font-mono text-xs"
                    />
                    <Button
                      size="icon"
                      data-testid="settings-share-link-copy-btn"
                      onClick={copyShare}
                      title="Copy link"
                    >
                      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    </Button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={share.path}
                    target="_blank"
                    rel="noreferrer"
                    className={buttonVariants({ variant: "outline", size: "sm" })}
                  >
                    Preview dossier
                  </a>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid="settings-share-link-revoke-btn"
                    onClick={() => revokeShare.mutate()}
                    disabled={revokeShare.isPending}
                    className="text-red-300 hover:text-red-200"
                  >
                    Revoke access
                  </Button>
                </div>
              </div>
            ) : (
              <div className="mt-6 space-y-4">
                <div className="max-w-48">
                  <p className="mb-1.5 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                    Link expiry
                  </p>
                  <Select value={expiry} onValueChange={(value: string) => setExpiry(value)}>
                    <SelectTrigger data-testid="share-expiry-select">
                      <SelectValue>{(v: string) => EXPIRY_OPTIONS.find((o) => o.days === v)?.label ?? v}</SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                      {EXPIRY_OPTIONS.map((option) => (
                        <SelectItem key={option.days} value={option.days}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  data-testid="settings-generate-share-link-btn"
                  onClick={() => createShare.mutate()}
                  disabled={createShare.isPending}
                  className="gap-2"
                >
                  {createShare.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Link2 className="h-4 w-4" />
                  )}
                  Generate public dossier link
                </Button>
              </div>
            )}
          </section>

          {/* Account card */}
          <section className="rounded-xl border border-border bg-card p-6 lg:col-span-5">
            <h2 className="font-heading text-lg font-semibold tracking-tight text-slate-100">Account</h2>
            <div className="mt-4 flex items-center gap-3">
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user.login}
                  className="h-12 w-12 rounded-full border border-slate-700 object-cover"
                />
              ) : (
                <span className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary font-mono text-lg text-slate-300">
                  {(user.name || user.login).slice(0, 1).toUpperCase()}
                </span>
              )}
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-200">{user.name || user.login}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">@{user.login}</p>
              </div>
            </div>
            <p className="mt-4 font-mono text-xs text-muted-foreground">
              {user.has_github_token
                ? "GitHub connected · read-only token stored server-side"
                : "Demo profile · no GitHub token stored"}
            </p>
            <Button
              variant="outline"
              size="sm"
              data-testid="settings-sign-out-btn"
              onClick={signOut}
              className="mt-6 gap-1.5"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </section>

          {/* Weekly auto-sync */}
          <section className="rounded-xl border border-border bg-card p-6 lg:col-span-12">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-500/10 text-cyan-400">
                <CalendarClock className="h-5 w-5" />
              </span>
              <div className="flex-1">
                <h2 className="font-heading text-lg font-semibold tracking-tight text-slate-100">
                  Weekly auto-sync
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-slate-400">
                  {user.has_github_token
                    ? "Re-analyze your GitHub once a week so new work shows up without clicking. Only new contributions are processed; excluded repos stay skipped."
                    : "Weekly re-analysis fetches from GitHub, so it only runs for accounts signed in with GitHub — the demo profile is never synced."}
                </p>
                <p className="mt-1.5 font-mono text-xs text-muted-foreground" data-testid="auto-sync-last-synced">
                  Last synced:{" "}
                  {user.last_synced_at
                    ? new Date(user.last_synced_at).toLocaleString(undefined, {
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })
                    : "never"}
                </p>
              </div>
              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3">
                <Checkbox
                  data-testid="settings-auto-sync-toggle"
                  checked={user.auto_sync}
                  disabled={autoSync.isPending}
                  onCheckedChange={(value) => autoSync.mutate(Boolean(value))}
                />
                <span className="text-sm text-slate-200">{user.auto_sync ? "On — weekly" : "Off"}</span>
              </label>
            </div>
          </section>

          {/* Danger zone */}
          <section className="rounded-xl border border-red-500/30 bg-red-500/[0.03] p-6 lg:col-span-12">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-red-500/10 text-red-400">
                <ShieldAlert className="h-5 w-5" />
              </span>
              <div className="flex-1">
                <h2 className="font-heading text-lg font-semibold tracking-tight text-slate-100">
                  Danger zone
                </h2>
                <p className="mt-1 max-w-2xl text-sm text-slate-400">
                  Permanently delete all stored GitHub-derived intelligence — contributions, skill
                  graph, insights and share links. Your account and sign-in stay intact.
                </p>
                <Button
                  variant="destructive"
                  size="sm"
                  data-testid="settings-danger-delete-data-btn"
                  onClick={() => setConfirmOpen(true)}
                  className="mt-4 gap-1.5"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete all analyzed intelligence
                </Button>
              </div>
            </div>
          </section>
        </div>
      </main>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete all analyzed intelligence?</DialogTitle>
            <DialogDescription>
              This permanently removes every contribution, skill, insight and share link derived from
              GitHub for your account. This cannot be undone — you would need to re-run the analysis
              to rebuild it.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              data-testid="settings-confirm-delete-dialog-btn"
              onClick={() => deleteData.mutate()}
              disabled={deleteData.isPending}
              className="gap-1.5"
            >
              {deleteData.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete everything
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

