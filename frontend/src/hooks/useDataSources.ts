import { useQueryLite } from './queryClientLite';
import { listSources } from '../services/sourcesApi';

const DATA_SOURCES_QUERY_KEY = ['sources', 'list'] as const;

export function useDataSources() {
  const query = useQueryLite({
    queryKey: DATA_SOURCES_QUERY_KEY,
    queryFn: listSources,
  });

  return {
    sources: query.data ?? [],
    isLoading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch: query.refetch,
  };
}

export { DATA_SOURCES_QUERY_KEY };
