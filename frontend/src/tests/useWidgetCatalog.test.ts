import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/widgetCatalogApi', () => ({
  getWidgetCatalog: vi.fn(),
  getWidgetCategories: vi.fn(),
  getWidgetPreview: vi.fn(),
  filterWidgetsByCategory: vi.fn((widgets, category) =>
    category === 'all' ? widgets : widgets.filter((w: any) => w.businessCategory === category),
  ),
}));

import * as api from '../services/widgetCatalogApi';
import { useWidgetCatalog, useWidgetPreview } from '../hooks/useWidgetCatalog';

const mockedApi = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  mockedApi.getWidgetCatalog.mockResolvedValue([
    {
      id: '1',
      templateId: 't',
      name: 'Sales',
      description: 'desc',
      category: 'bar',
      chart_type: 'bar',
      businessCategory: 'sales',
      default_config: {},
    },
    {
      id: '2',
      templateId: 't',
      name: 'ROAS',
      description: 'desc',
      category: 'kpi',
      chart_type: 'kpi',
      businessCategory: 'roas',
      default_config: {},
    },
  ] as any);
  mockedApi.getWidgetCategories.mockResolvedValue([
    { id: 'all', name: 'All', icon: 'LayoutGrid' },
    { id: 'sales', name: 'Sales', icon: 'DollarSign' },
  ] as any);
  mockedApi.getWidgetPreview.mockResolvedValue({
    widgetId: '1',
    chartType: 'bar',
    isFallback: false,
    series: [{ label: 'x', value: 1 }],
  } as any);
});

describe('useWidgetCatalog', () => {
  it('returns full catalog and categories', async () => {
    const { result } = renderHook(() => useWidgetCatalog());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.items).toHaveLength(2);
    expect(result.current.categories).toHaveLength(2);
  });

  it('filters widgets by selected category', async () => {
    const { result } = renderHook(() => useWidgetCatalog('sales'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.widgets).toHaveLength(1);
  });

  it('refresh triggers refetch', async () => {
    const { result } = renderHook(() => useWidgetCatalog());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    await act(async () => {
      await result.current.refresh();
    });
    expect(mockedApi.getWidgetCatalog).toHaveBeenCalledTimes(2);
  });
});

describe('useWidgetPreview', () => {
  it('returns preview data', async () => {
    const { result } = renderHook(() => useWidgetPreview('1', 'dataset-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.previewData?.widgetId).toBe('1');
    expect(mockedApi.getWidgetPreview).toHaveBeenCalledWith('1', 'dataset-1');
  });
});
