import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetWidgetCatalogCacheForTests,
} from '../services/widgetCatalogApi';
import { useWidgetCatalog, useWidgetPreview } from '../hooks/useWidgetCatalog';

describe('useWidgetCatalog/useWidgetPreview backend integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    __resetWidgetCatalogCacheForTests();
    localStorage.clear();
  });

  it('loads catalog through templates backend endpoint via hook', async () => {
    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Template A',
                description: 'Desc',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Revenue KPI',
                    description: 'Revenue',
                    chart_type: 'kpi',
                    dataset_name: 'sales_daily',
                    config_json: {
                      metrics: [{ column: 'revenue', aggregation: 'SUM', label: 'Revenue' }],
                      dimensions: [],
                      time_range: '30',
                      time_grain: 'P1D',
                      filters: [],
                      display: { show_legend: true },
                    },
                  },
                ],
                required_datasets: ['sales_daily'],
                min_billing_tier: 'starter',
                sort_order: 1,
                is_active: true,
              },
            ],
            total: 1,
          }),
        } as Response;
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    }) as any;

    const { result } = renderHook(() => useWidgetCatalog());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.widgets).toHaveLength(1);
    expect(result.current.widgets[0].name).toBe('Revenue KPI');
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/templates',
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('returns hook error on backend auth failure for preview endpoint', async () => {
    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Template A',
                description: 'Desc',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Revenue Trend',
                    description: 'Revenue',
                    chart_type: 'bar',
                    dataset_name: 'sales_daily',
                    config_json: {
                      metrics: [{ column: 'revenue', aggregation: 'SUM', label: 'Revenue' }],
                      dimensions: ['date'],
                      time_range: '30',
                      time_grain: 'P1D',
                      filters: [],
                      display: { show_legend: true },
                    },
                  },
                ],
                required_datasets: ['sales_daily'],
                min_billing_tier: 'starter',
                sort_order: 1,
                is_active: true,
              },
            ],
            total: 1,
          }),
        } as Response;
      }

      if (url.endsWith('/api/datasets/preview')) {
        return {
          ok: false,
          status: 403,
          json: async () => ({ detail: 'Forbidden' }),
        } as Response;
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    }) as any;

    const { result } = renderHook(() => useWidgetPreview('tpl-1-report-0', 'sales_daily'));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.previewData).toBeNull();
    expect(result.current.error?.message).toBe('Forbidden');
    const previewCall = (global.fetch as any).mock.calls.find((call: any[]) => String(call[0]).endsWith('/api/datasets/preview'));
    expect(previewCall).toBeTruthy();
  });
});
