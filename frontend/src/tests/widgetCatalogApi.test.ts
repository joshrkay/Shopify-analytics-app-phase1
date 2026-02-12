import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../utils/widgetCatalog', () => ({
  fetchWidgetCatalog: vi.fn(),
}));

import * as widgetCatalogUtils from '../utils/widgetCatalog';
import {
  __resetWidgetCatalogCacheForTests,
  filterWidgetsByCategory,
  getWidgetCatalog,
  getWidgetCategories,
  getWidgetPreview,
} from '../services/widgetCatalogApi';

const mockedUtils = vi.mocked(widgetCatalogUtils);

beforeEach(() => {
  vi.clearAllMocks();
  __resetWidgetCatalogCacheForTests();

  mockedUtils.fetchWidgetCatalog.mockResolvedValue([
    {
      id: 'w-kpi',
      templateId: 'tpl-1',
      name: 'Revenue KPI',
      description: 'KPI desc',
      category: 'kpi',
      chart_type: 'kpi',
      default_config: {},
    },
    {
      id: 'w-sales',
      templateId: 'tpl-1',
      name: 'Sales Bar',
      description: 'Sales chart',
      category: 'bar',
      chart_type: 'bar',
      default_config: {},
      businessCategory: 'sales',
    },
  ] as any);
});

describe('widgetCatalogApi', () => {
  it('getWidgetCatalog returns normalized catalog', async () => {
    const catalog = await getWidgetCatalog();
    expect(catalog).toHaveLength(2);
    expect(catalog[0].businessCategory).toBe('roas');
  });

  it('caches catalog for repeated calls', async () => {
    await getWidgetCatalog();
    await getWidgetCatalog();
    expect(mockedUtils.fetchWidgetCatalog).toHaveBeenCalledTimes(1);
  });

  it('getWidgetCategories includes business categories', async () => {
    const categories = await getWidgetCategories();
    expect(categories.some((c) => c.id === 'sales')).toBe(true);
    expect(categories.some((c) => c.id === 'uncategorized')).toBe(false);
  });

  it('filters by category including all', async () => {
    const catalog = await getWidgetCatalog();
    expect(filterWidgetsByCategory(catalog, 'all')).toHaveLength(2);
    expect(filterWidgetsByCategory(catalog, 'sales')).toHaveLength(1);
  });

  it('returns KPI preview payload', async () => {
    const preview = await getWidgetPreview('w-kpi');
    expect(preview.chartType).toBe('kpi');
    expect(preview.value).toBeTypeOf('number');
    expect(preview.isFallback).toBe(true);
  });
});
