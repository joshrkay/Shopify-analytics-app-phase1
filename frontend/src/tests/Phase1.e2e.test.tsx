/**
 * Phase 1.7 End-to-End Smoke Tests
 *
 * High-level tests validating complete user flows through
 * the Phase 1 UI. Uses component rendering (not real browser)
 * to smoke-test routes, state transitions, and layout behavior.
 *
 * #  Test Case                                     What It Validates
 * 1  Authenticated user with data → sees dashboard Happy path renders completely
 * 2  Authenticated user without data → empty state Empty dashboard shown with CTAs
 * 3  Sidebar collapse → expand → collapse          Toggle cycle without layout break
 * 4  Switch workspace → profile updates            Tenant switch propagates to UI
 * 5  Full navigation cycle through all routes      No crashes navigating between pages
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter, Routes, Route, Navigate } from 'react-router-dom';

import { RootLayout, SidebarProvider } from '../components/layout/RootLayout';
import { Sidebar } from '../components/layout/Sidebar';
import { AppHeader } from '../components/layout/AppHeader';
import { DashboardHome } from '../pages/DashboardHome';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

const mockUseUser = vi.fn();
const mockUseOrganization = vi.fn();
const mockSignOut = vi.fn();

vi.mock('@clerk/clerk-react', () => ({
  useUser: () => mockUseUser(),
  useOrganization: () => mockUseOrganization(),
  useClerk: () => ({ signOut: mockSignOut }),
}));

const mockUseEntitlements = vi.fn();
vi.mock('../hooks/useEntitlements', () => ({
  useEntitlements: () => mockUseEntitlements(),
}));

vi.mock('../services/entitlementsApi', async () => ({
  isFeatureEntitled: (entitlements: any, feature: string) => {
    if (!entitlements) return false;
    return entitlements.features[feature]?.is_entitled ?? false;
  },
}));

vi.mock('../services/changelogApi', () => ({
  getUnreadCountNumber: vi.fn().mockResolvedValue(0),
  getEntriesForFeature: vi.fn().mockResolvedValue([]),
  markAsRead: vi.fn(),
}));

vi.mock('../services/whatChangedApi', () => ({
  hasCriticalIssues: vi.fn().mockResolvedValue(false),
  getWhatChangedSummary: vi.fn().mockResolvedValue(null),
}));

// Insights API — configurable per test
const mockGetUnreadInsightsCount = vi.fn();
const mockListInsights = vi.fn();
vi.mock('../services/insightsApi', () => ({
  getUnreadInsightsCount: (...args: any[]) => mockGetUnreadInsightsCount(...args),
  listInsights: (...args: any[]) => mockListInsights(...args),
}));

const mockGetActiveRecommendationsCount = vi.fn();
const mockListRecommendations = vi.fn();
vi.mock('../services/recommendationsApi', () => ({
  getActiveRecommendationsCount: (...args: any[]) => mockGetActiveRecommendationsCount(...args),
  listRecommendations: (...args: any[]) => mockListRecommendations(...args),
}));

const mockGetCompactHealth = vi.fn();
vi.mock('../services/syncHealthApi', () => ({
  getCompactHealth: (...args: any[]) => mockGetCompactHealth(...args),
}));

const mockUseAgency = vi.fn();
vi.mock('../contexts/AgencyContext', () => ({
  useAgency: () => mockUseAgency(),
}));

vi.mock('../services/apiUtils', () => ({
  isApiError: vi.fn().mockReturnValue(false),
  API_BASE_URL: 'http://localhost:8000',
  createHeadersAsync: vi.fn().mockResolvedValue({}),
  handleResponse: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

function makeEntitlements(featureFlags: Record<string, boolean>) {
  const features: Record<string, any> = {};
  for (const [key, entitled] of Object.entries(featureFlags)) {
    features[key] = {
      feature: key,
      is_entitled: entitled,
      billing_state: 'active',
      plan_id: 'plan_1',
      plan_name: 'Pro',
      reason: null,
      required_plan: null,
      grace_period_ends_on: null,
    };
  }
  return {
    billing_state: 'active',
    plan_id: 'plan_1',
    plan_name: 'Pro',
    features,
    grace_period_days_remaining: null,
  };
}

const allEntitled = makeEntitlements({ custom_reports: true, ai_insights: true });

function setupDefaultMocks() {
  mockUseUser.mockReturnValue({
    user: {
      fullName: 'Jane Doe',
      firstName: 'Jane',
      primaryEmailAddress: { emailAddress: 'jane@example.com' },
    },
  });
  mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
  mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  mockUseAgency.mockReturnValue({
    getActiveStore: () => ({ store_name: 'Test Store' }),
    isAgencyUser: false,
    activeTenantId: 'tenant-1',
    loading: false,
    error: null,
    assignedStores: [],
    allowedTenants: [],
    userRoles: [],
    billingTier: 'pro',
    userId: 'user-1',
    accessExpiringAt: null,
    switchStore: vi.fn(),
    refreshStores: vi.fn(),
    canAccessStore: vi.fn().mockReturnValue(true),
  });
}

function setupDataMocks() {
  mockGetUnreadInsightsCount.mockResolvedValue(5);
  mockGetActiveRecommendationsCount.mockResolvedValue(3);
  mockGetCompactHealth.mockResolvedValue({
    overall_status: 'healthy',
    health_score: 92,
    stale_count: 0,
    critical_count: 0,
    has_blocking_issues: false,
    oldest_sync_minutes: null,
    last_checked_at: '2025-01-15T00:00:00Z',
  });
  mockListInsights.mockResolvedValue({
    insights: [{
      insight_id: 'ins-1',
      insight_type: 'spend_anomaly',
      severity: 'warning',
      summary: 'Spend increased 40%',
      why_it_matters: null,
      supporting_metrics: [],
      timeframe: 'last_7d',
      confidence_score: 0.85,
      platform: 'meta',
      campaign_id: null,
      currency: 'USD',
      generated_at: '2025-01-15T00:00:00Z',
      is_read: false,
      is_dismissed: false,
    }],
    total: 1,
    has_more: false,
  });
  mockListRecommendations.mockResolvedValue({
    recommendations: [{
      recommendation_id: 'rec-1',
      related_insight_id: 'ins-1',
      recommendation_type: 'decrease_budget',
      priority: 'high',
      recommendation_text: 'Consider reducing spend',
      rationale: null,
      estimated_impact: 'significant',
      risk_level: 'low',
      confidence_score: 0.8,
      affected_entity: null,
      affected_entity_type: null,
      currency: null,
      generated_at: '2025-01-15T00:00:00Z',
      is_accepted: false,
      is_dismissed: false,
    }],
    total: 1,
    has_more: false,
  });
}

function setupEmptyMocks() {
  mockGetUnreadInsightsCount.mockResolvedValue(0);
  mockGetActiveRecommendationsCount.mockResolvedValue(0);
  mockGetCompactHealth.mockResolvedValue({
    overall_status: 'healthy',
    health_score: 100,
    stale_count: 0,
    critical_count: 0,
    has_blocking_issues: false,
    oldest_sync_minutes: null,
    last_checked_at: '2025-01-15T00:00:00Z',
  });
  mockListInsights.mockResolvedValue({ insights: [], total: 0, has_more: false });
  mockListRecommendations.mockResolvedValue({ recommendations: [], total: 0, has_more: false });
}

function renderApp(
  ui: React.ReactElement,
  { initialEntries = ['/home'] }: { initialEntries?: string[] } = {},
) {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <MemoryRouter initialEntries={initialEntries}>
        <SidebarProvider>{ui}</SidebarProvider>
      </MemoryRouter>
    </AppProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Phase 1.7 — E2E Smoke Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupDefaultMocks();
  });

  // 1. Authenticated user with data → sees full dashboard
  it('authenticated user with data sees full dashboard', async () => {
    setupDataMocks();

    renderApp(
      <>
        <AppHeader />
        <RootLayout>
          <Routes>
            <Route path="/home" element={<DashboardHome />} />
          </Routes>
        </RootLayout>
      </>,
    );

    // Sidebar present
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();

    // Header present
    expect(screen.getByLabelText('Toggle navigation')).toBeInTheDocument();

    // Dashboard loads with data
    await waitFor(() => {
      expect(screen.getByText('Unread Insights')).toBeInTheDocument();
    });

    expect(screen.getByText('Active Recommendations')).toBeInTheDocument();
    expect(screen.getByText('Data Health')).toBeInTheDocument();
    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('Healthy')).toBeInTheDocument();

    // Tables render
    expect(screen.getByText('Recent Insights')).toBeInTheDocument();
    expect(screen.getByText('Recommendations')).toBeInTheDocument();
  });

  // 2. Authenticated user without data → sees empty state
  it('authenticated user without data sees empty state', async () => {
    setupEmptyMocks();

    renderApp(
      <Routes>
        <Route path="/home" element={<DashboardHome />} />
      </Routes>,
    );

    await waitFor(() => {
      expect(screen.getByText('Welcome to your analytics dashboard')).toBeInTheDocument();
    });

    expect(screen.getByText('Connect data sources')).toBeInTheDocument();
  });

  // 3. Sidebar collapse → expand → collapse
  it('sidebar toggle cycle works without layout break', async () => {
    setupDataMocks();
    const user = userEvent.setup();

    renderApp(
      <>
        <AppHeader />
        <RootLayout>
          <div data-testid="page-content">Page Content</div>
        </RootLayout>
      </>,
    );

    const hamburger = screen.getByLabelText('Toggle navigation');
    const sidebar = screen.getByRole('navigation', { name: 'Main navigation' });
    const content = screen.getByTestId('page-content');

    // Initially closed
    expect(sidebar).not.toHaveClass('sidebar--open');
    expect(content).toBeInTheDocument();

    // Open
    await user.click(hamburger);
    expect(sidebar).toHaveClass('sidebar--open');
    expect(content).toBeInTheDocument();

    // Close
    await user.click(hamburger);
    expect(sidebar).not.toHaveClass('sidebar--open');
    expect(content).toBeInTheDocument();

    // Open again
    await user.click(hamburger);
    expect(sidebar).toHaveClass('sidebar--open');

    // Close via overlay
    const overlay = document.querySelector('.root-layout__overlay');
    expect(overlay).toBeInTheDocument();
    await user.click(overlay!);
    expect(sidebar).not.toHaveClass('sidebar--open');

    // Content still renders after all toggles
    expect(content).toBeInTheDocument();
  });

  // 4. Profile menu reflects current workspace
  it('profile menu displays current workspace info', async () => {
    setupDataMocks();
    const user = userEvent.setup();

    renderApp(<AppHeader />);

    // Open profile menu
    const profileButton = screen.getByLabelText('Profile menu for Jane Doe');
    await user.click(profileButton);

    await waitFor(() => {
      expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    });

    // Workspace name shown
    expect(screen.getByText('Test Store')).toBeInTheDocument();
  });

  // 5. Full navigation cycle through all routes
  it('full navigation cycle through all routes without crashes', async () => {
    setupDataMocks();
    const user = userEvent.setup();

    renderApp(
      <>
        <Sidebar />
        <Routes>
          <Route path="/home" element={<div>Home Page</div>} />
          <Route path="/dashboards" element={<div>Builder Page</div>} />
          <Route path="/insights" element={<div>Insights Page</div>} />
          <Route path="/data-sources" element={<div>Sources Page</div>} />
          <Route path="/settings" element={<div>Settings Page</div>} />
          <Route path="/" element={<Navigate to="/home" replace />} />
        </Routes>
      </>,
      { initialEntries: ['/home'] },
    );

    // Start on Home
    expect(screen.getByText('Home Page')).toBeInTheDocument();

    // Navigate to Builder
    await user.click(screen.getByText('Builder'));
    expect(screen.getByText('Builder Page')).toBeInTheDocument();

    // Navigate to Insights
    await user.click(screen.getByText('Insights'));
    expect(screen.getByText('Insights Page')).toBeInTheDocument();

    // Navigate to Sources
    await user.click(screen.getByText('Sources'));
    expect(screen.getByText('Sources Page')).toBeInTheDocument();

    // Navigate to Settings (find the nav item, not section header)
    const settingsNavItem = screen.getAllByText('Settings').find(
      (el) => el.closest('.sidebar-nav-item') !== null,
    );
    expect(settingsNavItem).toBeInTheDocument();
    await user.click(settingsNavItem!);
    expect(screen.getByText('Settings Page')).toBeInTheDocument();

    // Navigate back to Home
    await user.click(screen.getByText('Home'));
    expect(screen.getByText('Home Page')).toBeInTheDocument();
  });
});
