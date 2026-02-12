import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../services/customDashboardsApi', () => ({
  getDashboard: vi.fn(),
  updateDashboard: vi.fn(),
  publishDashboard: vi.fn(),
  createDashboard: vi.fn(),
}));

vi.mock('../services/customReportsApi', () => ({
  createReport: vi.fn(),
  updateReport: vi.fn(),
  deleteReport: vi.fn(),
  reorderReports: vi.fn(),
}));

import { DashboardBuilderProvider, useDashboardBuilder } from '../contexts/DashboardBuilderContext';
import type { Dashboard, WidgetCatalogItem } from '../types/customDashboards';

function wrapper({ children }: { children: React.ReactNode }) {
  return <DashboardBuilderProvider>{children}</DashboardBuilderProvider>;
}

const sampleCatalogItem: WidgetCatalogItem = {
  id: 'widget-sales-1',
  templateId: 'tpl-1',
  name: 'Sales KPI',
  description: 'desc',
  category: 'kpi',
  businessCategory: 'sales',
  chart_type: 'kpi',
  default_config: { metrics: ['revenue'] },
};

const sampleDashboard: Dashboard = {
  id: 'dash-1',
  name: 'Existing Dashboard',
  description: 'existing description',
  status: 'draft',
  layout_json: {},
  filters_json: null,
  template_id: null,
  is_template_derived: false,
  version_number: 1,
  reports: [
    {
      id: 'report-1',
      dashboard_id: 'dash-1',
      name: 'Legacy KPI',
      description: null,
      chart_type: 'kpi',
      dataset_name: 'sales_dataset',
      config_json: {},
      position_json: { x: 0, y: 0, w: 3, h: 2 },
      sort_order: 0,
      created_by: 'u1',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      warnings: [],
    },
  ],
  access_level: 'owner',
  created_by: 'u1',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
};

describe('DashboardBuilderContext wizard behavior (Phase 3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('starts at select step in wizard mode', () => {
    const { result } = renderHook(() => useDashboardBuilder(), { wrapper });

    act(() => {
      result.current.enterWizardMode();
    });

    expect(result.current.wizardState.currentStep).toBe('select');
    expect(result.current.wizardState.selectedWidgets).toHaveLength(0);
    expect(result.current.wizardState.selectedCatalogItems ?? []).toHaveLength(0);
  });

  it('blocks step transitions when guards are not satisfied', () => {
    const { result } = renderHook(() => useDashboardBuilder(), { wrapper });

    act(() => {
      result.current.enterWizardMode();
      result.current.setBuilderStep('customize');
    });
    expect(result.current.wizardState.currentStep).toBe('select');

    act(() => {
      result.current.addCatalogWidget(sampleCatalogItem);
      result.current.setBuilderStep('preview');
    });
    expect(result.current.wizardState.currentStep).toBe('select');

    act(() => {
      result.current.setBuilderStep('customize');
      result.current.setWizardDashboardName('Q1 Dashboard');
      result.current.setBuilderStep('preview');
    });
    expect(result.current.wizardState.currentStep).toBe('preview');
  });

  it('allows duplicate catalog widgets with unique generated report IDs', () => {
    const { result } = renderHook(() => useDashboardBuilder(), { wrapper });

    act(() => {
      result.current.enterWizardMode();
      result.current.addCatalogWidget(sampleCatalogItem);
      result.current.addCatalogWidget(sampleCatalogItem);
    });

    const widgets = result.current.wizardState.selectedWidgets;
    expect(widgets).toHaveLength(2);
    expect(widgets[0].id).not.toBe(widgets[1].id);
    expect(result.current.wizardState.selectedCatalogItems ?? []).toHaveLength(2);
  });

  it('removes one duplicate instance and falls back to select when list becomes empty', () => {
    const { result } = renderHook(() => useDashboardBuilder(), { wrapper });

    act(() => {
      result.current.enterWizardMode();
      result.current.addCatalogWidget(sampleCatalogItem);
      result.current.addCatalogWidget(sampleCatalogItem);
      result.current.setWizardDashboardName('Dashboard X');
      result.current.setBuilderStep('customize');
    });

    const firstId = result.current.wizardState.selectedWidgets[0].id;
    const secondId = result.current.wizardState.selectedWidgets[1].id;

    act(() => {
      result.current.removeWizardWidget(firstId);
    });
    expect(result.current.wizardState.selectedWidgets).toHaveLength(1);
    expect(result.current.wizardState.selectedCatalogItems ?? []).toHaveLength(1);
    expect(result.current.wizardState.currentStep).toBe('customize');

    act(() => {
      result.current.removeWizardWidget(secondId);
    });
    expect(result.current.wizardState.selectedWidgets).toHaveLength(0);
    expect(result.current.wizardState.currentStep).toBe('select');
  });

  it('hydrates wizard catalog state from existing dashboard in edit mode', () => {
    const { result } = renderHook(() => useDashboardBuilder(), { wrapper });

    act(() => {
      result.current.setDashboard(sampleDashboard);
    });

    expect(result.current.wizardState.dashboardName).toBe('Existing Dashboard');
    expect(result.current.wizardState.dashboardDescription).toBe('existing description');
    expect(result.current.wizardState.selectedBusinessCategory).toBe('all');
    expect(result.current.wizardState.selectedCatalogItems ?? []).toHaveLength(1);
    expect(result.current.wizardState.selectedCatalogItems?.[0].businessCategory).toBe('roas');
  });
});
