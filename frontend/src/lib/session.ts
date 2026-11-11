// Session boundary owner: lib/session decides when the react-query cache lives or dies.
// Sign-out must always go through endSession() — clearing only the server session would
// leak the previous account's cached data to the next login on this browser.

import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";
import type { MeResponse } from "@/types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: () => apiGet<MeResponse>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export async function beginSession(): Promise<void> {
  // Wipe any cached data from a previous identity, then let the next mount refetch /auth/me.
  queryClient.clear();
}

export async function endSession(): Promise<void> {
  try {
    await apiPost<void>("/auth/logout");
  } finally {
    queryClient.clear();
  }
}
