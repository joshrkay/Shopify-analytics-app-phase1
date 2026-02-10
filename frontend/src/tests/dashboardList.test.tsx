/**
 * Tests for DashboardList
 *
 * Phase 3 - Dashboard Builder UI
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import { DashboardList } from '../pages/DashboardList';
import { listDashboards } from '../services/customDashboardsApi';
import { fetchEntitlements, isFeatureEntitled } from '../services/entitlementsApi';
import type { Dashboard } from '../types/customDashboards';
import type { EntitlementsResponse } from '../services/entitlementsApi';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

// Partial mock react-router-dom – keep MemoryRouter real
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Auto-mock API services
vi.mock('../services/customDashboardsApi');
vi.mock('../services/entitlementsApi');
vi.mock('../services/apiUtils');

// ---------------------------------------------------------------------------
// Factories & helpers
// ---------------------------------------------------------------------------

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <MemoryRouter>
        {ui}
      </MemoryRouter>
    </AppProvider>,
  );
};

const createMockDashboard = (overrides?: Partial<Dashboard>): Dashboard => ({
  id: 'db-1',
  name: 'My Dashboard',
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

const createMockEntitlements = (overrides?: Partial<EntitlementsResponse>): EntitlementsResponse => ({
  billing_state: 'active',
  plan_id: 'plan-1',
  plan_name: 'Pro',
  features: {
    custom_dashboards: {
      feature: 'custom_dashboards',
      is_entitled: true,
      billing_state: 'active',
      plan_id: 'plan-1',
      plan_name: 'Pro',
      reason: null,
      required_plan: null,
      grace_period_ends_on: null,
    },
  },
  grace_period_days_remaining: null,
  ...overrides,
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('DashboardList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listDashboards).mockResolvedValue({
      dashboards: [createMockDashboard()],
      total: 1,
      offset: 0,
      limit: 10,
      has_more: false,
    });
    vi.mocked(fetchEntitlements).mockResolvedValue(createMockEntitlements());
    vi.mocked(isFeatureEntitled).mockReturnValue(true);
  });

  it("renders 'Dashboards' page title", () => {
    renderWithProviders(<DashboardList />);

    expect(screen.getByText('Dashboards')).toBeInTheDocument();
  });

  it('shows status tabs', () => {
    renderWithProviders(<DashboardList />);

    // Polaris Tabs renders both visible tabs and hidden measurer tabs,
    // so each tab label appears more than once in the DOM.
    expect(screen.getAllByText('All').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Draft').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Published').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Archived').length).toBeGreaterThanOrEqual(1);
  });

  it('shows dashboard name in the table after loading', async () => {
    renderWithProviders(<DashboardList />);

    await waitFor(() => {
      expect(screen.getByText('My Dashboard')).toBeInTheDocument();
    });
  });

  it('shows empty state when no dashboards', async () => {
    vi.mocked(listDashboards).mockResolvedValue({
      dashboards: [],
      total: 0,
      offset: 0,
      limit: 10,
      has_more: false,
    });

    renderWithProviders(<DashboardList />);

    await waitFor(() => {
      expect(screen.getByText('Create your first dashboard')).toBeInTheDocument();
    });
  });
});
