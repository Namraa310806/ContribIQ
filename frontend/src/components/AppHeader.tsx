import { Link, useNavigate } from "react-router-dom";
import { LayoutDashboard, LogOut, Settings as SettingsIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { endSession } from "@/lib/session";
import { LogoMark } from "@/components/Logo";
import type { UserPublic } from "@/types";

// Glass header for authenticated pages (the landing page ships its own nav).
export default function AppHeader({ user }: { user: UserPublic }) {
  const navigate = useNavigate();

  const signOut = async () => {
    await endSession();
    navigate("/", { replace: true });
  };

  const initials = (user.name || user.login || "?").slice(0, 1).toUpperCase();

  return (
    <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link to="/dashboard" data-testid="nav-brand-logo" className="flex items-center gap-2.5">
          <LogoMark />
          <span className="font-heading text-lg font-bold tracking-tight text-slate-100">ContribIQ</span>
          {user.is_demo && (
            <span className="ml-1 rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-widest text-amber-300">
              Demo
            </span>
          )}
        </Link>

        <nav className="flex items-center gap-1 sm:gap-2">
          <Link
            to="/dashboard"
            data-testid="nav-dashboard-link"
            className={buttonVariants({ variant: "ghost", size: "sm" }) + " gap-1.5"}
          >
            <LayoutDashboard className="h-4 w-4" />
            <span className="hidden sm:inline">Dashboard</span>
          </Link>
          <Link
            to="/settings"
            data-testid="nav-settings-link"
            className={buttonVariants({ variant: "ghost", size: "sm" }) + " gap-1.5"}
          >
            <SettingsIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Settings</span>
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger
              data-testid="nav-user-dropdown-menu"
              className={buttonVariants({ variant: "ghost", size: "sm" }) + " gap-2"}
            >
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user.login}
                  className="h-6 w-6 rounded-full border border-slate-700 object-cover"
                />
              ) : (
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-secondary font-mono text-xs text-slate-300">
                  {initials}
                </span>
              )}
              <span className="hidden max-w-28 truncate sm:inline">{user.name || user.login}</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuGroup>
                <DropdownMenuLabel className="font-mono text-xs text-muted-foreground">
                  @{user.login}
                </DropdownMenuLabel>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate("/dashboard")}>
                <LayoutDashboard className="mr-2 h-4 w-4" /> Dashboard
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/settings")}>
                <SettingsIcon className="mr-2 h-4 w-4" /> Settings & privacy
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" data-testid="nav-sign-out-btn" onClick={signOut}>
                <LogOut className="mr-2 h-4 w-4" /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </nav>
      </div>
    </header>
  );
}
