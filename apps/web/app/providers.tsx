"use client";

import * as React from "react";
import {
  QueryClient,
  QueryClientProvider,
  isServer,
} from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";

import { Toaster } from "@/components/ui/toast";
import { useStrategyStore } from "@/lib/strategy-store";

/**
 * TanStack Query provider.
 *
 * Following the recommended pattern from
 * https://tanstack.com/query/latest/docs/framework/react/guides/ssr —
 * we make a fresh client on the server for every request, and a single
 * stable client on the browser. Otherwise multiple users would share
 * one cache during SSR.
 */

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Most analysis endpoints are point-in-time so 30 s of staleness
        // is plenty; live ticker / status data sets its own staleTime.
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient(): QueryClient {
  if (isServer) {
    // Server: always make a fresh one — never share across requests.
    return makeQueryClient();
  }
  // Browser: lazily create exactly one for the lifetime of the page.
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

function StrategyBucketSync(): null {
  const syncFromServer = useStrategyStore((s) => s.syncFromServer);
  React.useEffect(() => {
    void syncFromServer();
  }, [syncFromServer]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  return (
    <QueryClientProvider client={queryClient}>
      <StrategyBucketSync />
      {children}
      <Toaster />
      {process.env.NODE_ENV === "development" && (
        <ReactQueryDevtools initialIsOpen={false} buttonPosition="bottom-right" />
      )}
    </QueryClientProvider>
  );
}
