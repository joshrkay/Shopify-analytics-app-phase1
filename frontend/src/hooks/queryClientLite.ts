import { useCallback, useEffect, useMemo, useState } from 'react';

export type QueryKey = readonly unknown[];

function serializeKey(queryKey: QueryKey): string {
  return JSON.stringify(queryKey);
}

class QueryClientLite {
  private versions = new Map<string, number>();

  getVersion(queryKey: QueryKey): number {
    return this.versions.get(serializeKey(queryKey)) ?? 0;
  }

  invalidateQueries(queryKey: QueryKey): void {
    const serialized = serializeKey(queryKey);
    const current = this.versions.get(serialized) ?? 0;
    this.versions.set(serialized, current + 1);
  }
}

const queryClientLite = new QueryClientLite();

export function useQueryClientLite(): QueryClientLite {
  return queryClientLite;
}

interface UseQueryLiteOptions<TData> {
  queryKey: QueryKey;
  queryFn: () => Promise<TData>;
}

interface UseQueryLiteResult<TData> {
  data: TData | undefined;
  isLoading: boolean;
  error: unknown;
  refetch: () => Promise<TData>;
}

export function useQueryLite<TData>({ queryKey, queryFn }: UseQueryLiteOptions<TData>): UseQueryLiteResult<TData> {
  const client = useQueryClientLite();
  const version = client.getVersion(queryKey);
  const [data, setData] = useState<TData | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const nextData = await queryFn();
      setData(nextData);
      return nextData;
    } catch (err) {
      setError(err);
      throw err;
    } finally {
      setIsLoading(false);
    }
  }, [queryFn]);

  useEffect(() => {
    refetch().catch(() => undefined);
  }, [refetch, version]);

  return { data, isLoading, error, refetch };
}

interface UseMutationLiteOptions<TData, TVariables> {
  mutationFn: (variables: TVariables) => Promise<TData>;
  onSuccess?: (data: TData, variables: TVariables) => void | Promise<void>;
  onError?: (error: unknown, variables: TVariables) => void;
}

interface UseMutationLiteResult<TData, TVariables> {
  mutateAsync: (variables: TVariables) => Promise<TData>;
  isPending: boolean;
  error: unknown;
}

export function useMutationLite<TData, TVariables>(
  options: UseMutationLiteOptions<TData, TVariables>,
): UseMutationLiteResult<TData, TVariables> {
  const { mutationFn, onSuccess, onError } = options;
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const mutateAsync = useCallback(async (variables: TVariables) => {
    setIsPending(true);
    setError(null);
    try {
      const result = await mutationFn(variables);
      await onSuccess?.(result, variables);
      return result;
    } catch (err) {
      setError(err);
      onError?.(err, variables);
      throw err;
    } finally {
      setIsPending(false);
    }
  }, [mutationFn, onError, onSuccess]);

  return useMemo(() => ({ mutateAsync, isPending, error }), [error, isPending, mutateAsync]);
}
