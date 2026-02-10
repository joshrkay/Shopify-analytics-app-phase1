/**
 * Tests for DashboardBuilder
 *
 * Phase 3 - Dashboard Builder UI
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import { DashboardBuilder } from '../pages/DashboardBuilder';
import { getDashboard } from '../services/customDashboardsApi';
import type { Dashboard, Report } from '../types/customDashboards';

// ---------------------------------------------------------------------------
// Mutable mock values for per-test overrides
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();
let mockParams: Record<string, string> = { dashboardId: 'db-1' };

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

// Partial mock react-router-dom – keep MemoryRouter real
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => mockParams,
  };
});

// Mock react-grid-layout default export
vi.mock('react-grid-layout', async () => {
  const R = await import('react');
  return {
    default: (props: any) =>
      R.createElement('div', { 'data-testid': 'grid-layout' }, props.children),
  };
});

// Auto-mock API services
vi.mock('../services/customDashboardsApi');
vi.mock('../services/customReportsApi');
vi.mock('../services/datasetsApi');
vi.mock('../services/apiUtils');

// ---------------------------------------------------------------------------
// Factories & helpers
// ---------------------------------------------------------------------------

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithProviders = (ui: React.ReactElement, initialEntries?: string[]) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <MemoryRouter initialEntries={initialEntries}>
        {ui}
      </MemoryRouter>
    </AppProvider>,
  );
};

const createMockDashboard = (overrides?: Partial<Dashboard>): Dashboard => ({
  id: 'db-1',
  name: 'Test Dashboard',
  description: 'Test description',
  status: 'draft',
  layout_json: {},
  filters_json: null,
  template_id: null,
  is_template_derived: false,
  version_number: 1,
  reports: [],
  access_level: 'owner',
  created_by: 'user-1',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  ...overrides,
});

const createMockReport = (overrides?: Partial<Report>): Report => ({
  id: 'report-1',
  dashboard_id: 'db-1',
  name: 'Test Report',
  description: null,
  chart_type: 'bar',
  dataset_name: 'test_dataset',
  config_json: {
    metrics: [{ column: 'revenue', aggregation: 'SUM' }],
    dimensions: ['date'],
    time_range: 'last_7_days',
    time_grain: 'P1D',
    filters: [],
    display: { show_legend: true },
  },
  position_json: { x: 0, y: 0, w: 6, h: 3 },
  sort_order: 0,
  created_by: 'user-1',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
  warnings: [],
  ...overrides,
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardBuilder', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockParams = { dashboardId: 'db-1' };
    vi.mocked(getDashboard).mockResolvedValue(createMockDashboard());
  });

  it('shows the dashboard name after loading', async () => {
    renderWithProviders(<DashboardBuilder />, ['/dashboards/db-1/edit']);

    await waitFor(() => {
      expect(screen.getByText('Test Dashboard')).toBeInTheDocument();
    });
  });

  it("shows 'No dashboard ID provided' banner when dashboardId is missing", () => {
    mockParams = {};

    renderWithProviders(<DashboardBuilder />);

    expect(screen.getByText('No dashboard ID provided')).toBeInTheDocument();
  });

  it('renders the grid container after loading', async () => {
    vi.mocked(getDashboard).mockResolvedValue(
      createMockDashboard({ reports: [createMockReport()] }),
    );

    renderWithProviders(<DashboardBuilder />, ['/dashboards/db-1/edit']);

    await waitFor(() => {
      expect(screen.getByTestId('grid-layout')).toBeInTheDocument();
    });
  });
});
