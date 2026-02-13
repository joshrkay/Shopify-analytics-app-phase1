import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/apiUtils', () => ({
  API_BASE_URL: '',
  createHeadersAsync: vi.fn().mockResolvedValue({ 'Content-Type': 'application/json' }),
  handleResponse: vi.fn(async (response: Response) => response.json()),
}));

import { previewReportData } from '../services/reportDataApi';
import type { ChartConfig } from '../types/customDashboards';

const sampleConfig: ChartConfig = {
  metrics: [{ column: 'revenue', aggregation: 'SUM', label: 'Revenue' }],
  dimensions: ['date'],
  time_range: '30',
  time_grain: 'P1D',
  filters: [],
  display: {
    show_legend: true,
  },
};

describe('reportDataApi backend route integration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        data: [{ date: '2025-01-01', revenue: 100 }],
        columns: ['date', 'revenue'],
        row_count: 1,
        truncated: false,
        message: null,
        query_duration_ms: 10,
        viz_type: 'line',
      }),
    } as unknown as Response);
  });

  it('uses /api/datasets/preview (no /v1) and maps chart config payload', async () => {
    const result = await previewReportData('sales_daily', sampleConfig, '30');

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/datasets/preview',
      expect.objectContaining({ method: 'POST' }),
    );

    const [, options] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const body = JSON.parse(String(options.body));

    expect(body).toMatchObject({
      dataset_name: 'sales_daily',
      time_range: '30',
      time_grain: 'P1D',
      viz_type: 'line',
      dimensions: ['date'],
    });

    expect(body.metrics).toEqual([
      {
        label: 'Revenue',
        column: 'revenue',
        aggregate: 'SUM',
      },
    ]);

    expect(result.row_count).toBe(1);
    expect(result.columns).toEqual(['date', 'revenue']);
  });
});
