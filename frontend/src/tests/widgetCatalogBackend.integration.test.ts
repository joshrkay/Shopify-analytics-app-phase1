import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  __resetWidgetCatalogCacheForTests,
  getWidgetCatalog,
  getWidgetPreview,
} from '../services/widgetCatalogApi';

describe('widget catalog backend wiring integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    __resetWidgetCatalogCacheForTests();
    localStorage.clear();
  });

  it('loads catalog from backend templates endpoint', async () => {
    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Sales template',
                description: 'Template description',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Revenue Trend',
                    description: 'Revenue over time',
                    chart_type: 'line',
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

      throw new Error(`Unexpected fetch URL: ${url}`);
    }) as any;

    const catalog = await getWidgetCatalog();

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/templates',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(catalog).toHaveLength(1);
    expect(catalog[0].name).toBe('Revenue Trend');
    expect(catalog[0].required_dataset).toBe('sales_daily');
    expect(catalog[0].businessCategory).toBe('campaigns');
  });

  it('fetches preview from backend dataset preview endpoint when dataset is available', async () => {
    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Template',
                description: 'desc',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Sales by day',
                    description: 'desc',
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
          ok: true,
          json: async () => ({
            data: [
              { date: '2025-01-01', revenue: 100 },
              { date: '2025-01-02', revenue: 120 },
            ],
            columns: ['date', 'revenue'],
            row_count: 2,
            truncated: false,
            message: null,
            query_duration_ms: 20,
            viz_type: 'bar',
          }),
        } as Response;
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    }) as any;

    const catalog = await getWidgetCatalog();
    const preview = await getWidgetPreview(catalog[0].id);

    const previewCall = (global.fetch as any).mock.calls.find((call: any[]) => String(call[0]).endsWith('/api/datasets/preview'));
    expect(previewCall).toBeTruthy();
    expect(previewCall[1]).toMatchObject({ method: 'POST' });
    expect(preview.isFallback).toBe(false);
    expect(preview.chartType).toBe('bar');
    expect(preview.series?.length).toBe(2);
    expect(preview.series?.[0]).toEqual({ label: '2025-01-01', value: 100 });
  });


  it('falls back with api_error and logs diagnostic context on non-auth preview failures', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Template',
                description: 'desc',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Sales by day',
                    description: 'desc',
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
          status: 500,
          json: async () => ({ detail: 'Server exploded' }),
        } as Response;
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    }) as any;

    const catalog = await getWidgetCatalog();
    const preview = await getWidgetPreview(catalog[0].id);

    expect(preview.isFallback).toBe(true);
    expect(preview.fallbackReason).toBe('api_error');
    expect(errorSpy).toHaveBeenCalledWith(
      'Failed to fetch widget preview from backend API',
      expect.objectContaining({
        widgetId: catalog[0].id,
        datasetName: 'sales_daily',
        chartType: 'bar',
      }),
    );
  });

  it('propagates auth errors from preview endpoint instead of silently falling back', async () => {
    global.fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);

      if (url.endsWith('/api/v1/templates')) {
        return {
          ok: true,
          json: async () => ({
            templates: [
              {
                id: 'tpl-1',
                name: 'Template',
                description: 'desc',
                category: 'sales',
                thumbnail_url: null,
                layout_json: {},
                reports_json: [
                  {
                    name: 'Sales by day',
                    description: 'desc',
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

    const catalog = await getWidgetCatalog();

    await expect(getWidgetPreview(catalog[0].id)).rejects.toMatchObject({
      status: 403,
    });
  });

});
