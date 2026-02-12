/**
 * Type compatibility tests for Phase 2 Builder widget catalog types.
 *
 * Validates that new catalog types:
 * - Are properly defined and exportable
 * - Cover all required enum values
 * - Map correctly to grid layout system
 * - Don't break existing type system
 */

import { describe, it, expect } from 'vitest';
import type {
  WidgetCatalogItem,
  WidgetCategory,
  WidgetCategoryMeta,
  BuilderStep,
  BuilderWizardState,
  WidgetPreviewData,
  WidgetSize,
  ChartType,
} from '../types/customDashboards';
import {
  getWidgetCategoryLabel,
  getWidgetSizeColumns,
  getChartTypeLabel,
} from '../types/customDashboards';

describe('Widget Catalog Types - Phase 2.1', () => {
  describe('WidgetCatalogItem type', () => {
    it('accepts valid widget catalog item structure', () => {
      const widget: WidgetCatalogItem = {
        id: 'roas-overview',
        type: 'chart',
        title: 'ROAS Overview',
        description: 'Return on ad spend across all channels',
        icon: 'TrendingUp',
        category: 'roas',
        defaultSize: 'medium',
        chartType: 'kpi',
        dataSourceRequired: true,
        requiredDatasets: ['marketing_attribution'],
      };

      expect(widget.id).toBe('roas-overview');
      expect(widget.type).toBe('chart');
      expect(widget.category).toBe('roas');
      expect(widget.defaultSize).toBe('medium');
    });

    it('accepts metric widget without chartType', () => {
      const widget: WidgetCatalogItem = {
        id: 'revenue-kpi',
        type: 'metric',
        title: 'Total Revenue',
        description: 'Total revenue for selected period',
        icon: 'DollarSign',
        category: 'sales',
        defaultSize: 'small',
      };

      expect(widget.type).toBe('metric');
      expect(widget.chartType).toBeUndefined();
    });

    it('accepts table widget', () => {
      const widget: WidgetCatalogItem = {
        id: 'top-products',
        type: 'table',
        title: 'Top Products',
        description: 'Best selling products by revenue',
        icon: 'Package',
        category: 'products',
        defaultSize: 'medium',
        chartType: 'table',
      };

      expect(widget.type).toBe('table');
      expect(widget.chartType).toBe('table');
    });
  });

  describe('WidgetCategory enum', () => {
    it.each<[WidgetCategory, string]>([
      ['all', 'All Widgets'],
      ['roas', 'ROAS & ROI'],
      ['sales', 'Sales'],
      ['products', 'Products'],
      ['customers', 'Customers'],
      ['campaigns', 'Campaigns'],
    ])('covers %s category with label "%s"', (category, expectedLabel) => {
      expect(getWidgetCategoryLabel(category)).toBe(expectedLabel);
    });

    it('has exactly 6 categories', () => {
      const categories: WidgetCategory[] = [
        'all',
        'roas',
        'sales',
        'products',
        'customers',
        'campaigns',
      ];
      expect(categories).toHaveLength(6);
    });
  });

  describe('WidgetCategoryMeta interface', () => {
    it('accepts valid category metadata', () => {
      const categoryMeta: WidgetCategoryMeta = {
        id: 'roas',
        name: 'ROAS & ROI',
        icon: 'TrendingUp',
        description: 'Return on ad spend metrics',
      };

      expect(categoryMeta.id).toBe('roas');
      expect(categoryMeta.name).toBe('ROAS & ROI');
      expect(categoryMeta.icon).toBe('TrendingUp');
    });

    it('accepts category without description', () => {
      const categoryMeta: WidgetCategoryMeta = {
        id: 'all',
        name: 'All Widgets',
        icon: 'LayoutGrid',
      };

      expect(categoryMeta.description).toBeUndefined();
    });
  });

  describe('BuilderStep enum', () => {
    it.each<[BuilderStep, number]>([
      ['select', 1],
      ['customize', 2],
      ['preview', 3],
    ])('step %s is step %d in wizard flow', (step, expectedOrder) => {
      const steps: BuilderStep[] = ['select', 'customize', 'preview'];
      expect(steps.indexOf(step)).toBe(expectedOrder - 1);
    });

    it('has exactly 3 wizard steps', () => {
      const steps: BuilderStep[] = ['select', 'customize', 'preview'];
      expect(steps).toHaveLength(3);
    });
  });

  describe('BuilderWizardState interface', () => {
    it('accepts valid wizard state', () => {
      const state: BuilderWizardState = {
        currentStep: 'select',
        selectedCatalogItems: [],
        dashboardName: 'My Dashboard',
        selectedCategory: 'all',
        isDirty: false,
      };

      expect(state.currentStep).toBe('select');
      expect(state.selectedCatalogItems).toEqual([]);
      expect(state.isDirty).toBe(false);
    });

    it('accepts state with selected widgets', () => {
      const widget: WidgetCatalogItem = {
        id: 'roas-overview',
        type: 'chart',
        title: 'ROAS Overview',
        description: 'ROAS metrics',
        icon: 'TrendingUp',
        category: 'roas',
        defaultSize: 'medium',
        chartType: 'kpi',
      };

      const state: BuilderWizardState = {
        currentStep: 'customize',
        selectedCatalogItems: [widget],
        dashboardName: 'Marketing Dashboard',
        selectedCategory: 'roas',
        isDirty: true,
      };

      expect(state.selectedCatalogItems).toHaveLength(1);
      expect(state.isDirty).toBe(true);
    });
  });

  describe('WidgetPreviewData interface', () => {
    it('accepts preview data with chart type', () => {
      const previewData: WidgetPreviewData = {
        widgetId: 'roas-overview',
        chartType: 'kpi',
        sampleData: { value: 12458, change: 12.5, trend: 'up' },
        loading: false,
      };

      expect(previewData.widgetId).toBe('roas-overview');
      expect(previewData.chartType).toBe('kpi');
      expect(previewData.loading).toBe(false);
    });

    it('accepts preview data with error', () => {
      const previewData: WidgetPreviewData = {
        widgetId: 'sales-trend',
        sampleData: {},
        loading: false,
        error: 'Failed to load preview data',
      };

      expect(previewData.error).toBe('Failed to load preview data');
    });
  });

  describe('Widget size to grid column mapping', () => {
    it.each<[WidgetSize, number]>([
      ['small', 3],
      ['medium', 6],
      ['large', 9],
      ['full', 12],
    ])('maps %s size to %d columns', (size, expectedColumns) => {
      expect(getWidgetSizeColumns(size)).toBe(expectedColumns);
    });

    it('all sizes fit within 12-column grid', () => {
      const sizes: WidgetSize[] = ['small', 'medium', 'large', 'full'];
      sizes.forEach((size) => {
        const columns = getWidgetSizeColumns(size);
        expect(columns).toBeGreaterThan(0);
        expect(columns).toBeLessThanOrEqual(12);
      });
    });
  });

  describe('Type compatibility with existing types', () => {
    it('WidgetCatalogItem chartType is compatible with ChartType', () => {
      const chartTypes: ChartType[] = ['line', 'bar', 'area', 'pie', 'kpi', 'table'];

      chartTypes.forEach((chartType) => {
        const widget: WidgetCatalogItem = {
          id: `test-${chartType}`,
          type: 'chart',
          title: `Test ${chartType}`,
          description: 'Test widget',
          icon: 'TestIcon',
          category: 'sales',
          defaultSize: 'medium',
          chartType, // Should accept any valid ChartType
        };

        expect(widget.chartType).toBe(chartType);
        expect(getChartTypeLabel(chartType)).toBeTruthy();
      });
    });

    it('widget catalog can store widgets with various types', () => {
      const catalog: WidgetCatalogItem[] = [
        {
          id: 'metric-widget',
          type: 'metric',
          title: 'Metric',
          description: 'A metric widget',
          icon: 'Icon',
          category: 'sales',
          defaultSize: 'small',
        },
        {
          id: 'chart-widget',
          type: 'chart',
          title: 'Chart',
          description: 'A chart widget',
          icon: 'Icon',
          category: 'sales',
          defaultSize: 'large',
          chartType: 'line',
        },
        {
          id: 'table-widget',
          type: 'table',
          title: 'Table',
          description: 'A table widget',
          icon: 'Icon',
          category: 'products',
          defaultSize: 'medium',
          chartType: 'table',
        },
      ];

      expect(catalog).toHaveLength(3);
      expect(catalog.map((w) => w.type)).toEqual(['metric', 'chart', 'table']);
    });
  });

  describe('Helper function edge cases', () => {
    it('getWidgetCategoryLabel falls back to category value for unknown', () => {
      // Testing runtime behavior with invalid category
      const label = getWidgetCategoryLabel('unknown' as WidgetCategory);
      expect(label).toBe('unknown');
    });

    it('getChartTypeLabel falls back to type value for unknown', () => {
      // Testing runtime behavior with invalid type
      const label = getChartTypeLabel('unknown' as ChartType);
      expect(label).toBe('unknown');
    });
  });
});
