/**
 * useTemplates Hook
 *
 * Custom hook to fetch and manage the list of report templates.
 * Fetches templates on mount with optional category filter.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import type {
  ReportTemplate,
  TemplateFilters,
} from '../types/customDashboards';
import { listTemplates } from '../services/templatesApi';
import { isApiError } from '../services/apiUtils';

interface UseTemplatesResult {
  templates: ReportTemplate[];
  total: number;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

/**
 * Hook to fetch the list of available report templates.
 *
 * Usage:
 * ```tsx
 * const { templates, loading, error } = useTemplates({ category: 'sales' });
 *
 * if (loading) return <Spinner />;
 * if (error) return <ErrorBanner message={error} />;
 *
 * return <TemplateGallery templates={templates} />;
 * ```
 */
export function useTemplates(filters: TemplateFilters = {}): UseTemplatesResult {
  const [templates, setTemplates] = useState<ReportTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadTemplates = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await listTemplates(filters);
      setTemplates(data.templates);
      setTotal(data.total);
    } catch (err) {
      console.error('Failed to fetch templates:', err);
      if (isApiError(err)) {
        setError(err.detail || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load templates');
      }
    } finally {
      setLoading(false);
    }
  }, [filters.category]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  return {
    templates,
    total,
    loading,
    error,
    refetch: loadTemplates,
  };
}
