/**
 * useWidgetCatalog Hook
 *
 * Custom hook to fetch and manage the widget catalog for the dashboard builder wizard.
 * Extracts individual reports from templates as selectable widgets.
 *
 * Phase 3 - Dashboard Builder Wizard UI
 */

import { useState, useEffect, useCallback } from 'react';
import type { WidgetCatalogItem } from '../types/customDashboards';
import { fetchWidgetCatalog } from '../utils/widgetCatalog';
import { getErrorMessage } from '../services/apiUtils';

interface UseWidgetCatalogResult {
  items: WidgetCatalogItem[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook to fetch the widget catalog for the dashboard builder wizard.
 *
 * Fetches all templates and extracts their individual reports as WidgetCatalogItems.
 * These items populate the widget gallery in Step 1 of the wizard.
 *
 * Usage:
 * ```tsx
 * const { items, loading, error, refresh } = useWidgetCatalog();
 *
 * if (loading) return <Spinner />;
 * if (error) return <Banner tone="critical">{error}</Banner>;
 *
 * return <WidgetGallery items={items} />;
 * ```
 */
export function useWidgetCatalog(): UseWidgetCatalogResult {
  const [items, setItems] = useState<WidgetCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const catalog = await fetchWidgetCatalog();
      setItems(catalog);
    } catch (err) {
      console.error('Failed to fetch widget catalog:', err);
      setError(getErrorMessage(err, 'Failed to load widget catalog'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const catalog = await fetchWidgetCatalog();

        if (!cancelled) {
          setItems(catalog);
        }
      } catch (err) {
        console.error('Failed to fetch widget catalog:', err);
        if (!cancelled) {
          setError(getErrorMessage(err, 'Failed to load widget catalog'));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();

    return () => {
      cancelled = true;
    };
  }, []);

  return {
    items,
    loading,
    error,
    refresh: loadCatalog,
  };
}
