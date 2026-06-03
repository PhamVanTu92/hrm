import { QueryClient } from "@tanstack/react-query";

/** App-wide TanStack Query client with sensible defaults for an internal tool. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}
