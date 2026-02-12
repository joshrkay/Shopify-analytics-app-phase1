import { describe, expect, it } from 'vitest';
import {
  GRID_COLS,
  SIZE_TO_COLUMNS,
  WIDGET_CATEGORY_META,
  getWidgetCategoryLabel,
  mapChartTypeToWidgetCategory,
} from '../types/customDashboards';
import type {
  BuilderStep,
  WidgetCatalogItem,
  WidgetCategory,
  WidgetSize,
} from '../types/customDashboards';

describe('builder catalog and wizard type compatibility', () => {
  it('covers expected business categories', () => {
    const categories = WIDGET_CATEGORY_META.map((meta) => meta.id);
    const expected: WidgetCategory[] = [
      'all',
      'roas',
      'sales',
      'products',
      'customers',
      'campaigns',
      'uncategorized',
    ];

    expected.forEach((id) => {
      expect(categories).toContain(id);
    });
  });

  it('maps default sizes to 12-column spans', () => {
    const pairs: Array<[WidgetSize, number]> = [
      ['small', 3],
      ['medium', 6],
      ['large', 9],
      ['full', 12],
    ];

    pairs.forEach(([size, columns]) => {
      expect(SIZE_TO_COLUMNS[size]).toBe(columns);
      expect(columns).toBeLessThanOrEqual(GRID_COLS);
    });
  });

  it('maps chart types into business categories', () => {
    expect(mapChartTypeToWidgetCategory('kpi')).toBe('roas');
    expect(mapChartTypeToWidgetCategory('bar')).toBe('sales');
    expect(mapChartTypeToWidgetCategory('pie')).toBe('products');
    expect(mapChartTypeToWidgetCategory('table')).toBe('customers');
  });

  it('keeps widget catalog item backwards compatible while supporting new fields', () => {
    const item: WidgetCatalogItem = {
      id: 'tpl-1-report-0',
      templateId: 'tpl-1',
      name: 'Revenue',
      title: 'Revenue',
      description: 'Revenue metric',
      category: 'kpi',
      businessCategory: 'roas',
      chart_type: 'kpi',
      default_config: { metrics: ['revenue'] },
      defaultSize: 'small',
      icon: 'DollarSign',
    };

    expect(item.name).toBe(item.title);
    expect(item.category).toBe('kpi');
    expect(item.businessCategory).toBe('roas');
  });

  it('supports all wizard steps in the type union', () => {
    const steps: BuilderStep[] = ['select', 'customize', 'preview'];
    expect(steps).toHaveLength(3);
  });

  it('returns category labels', () => {
    expect(getWidgetCategoryLabel('sales')).toBe('Sales');
    expect(getWidgetCategoryLabel('uncategorized')).toBe('Uncategorized');
  });
});
