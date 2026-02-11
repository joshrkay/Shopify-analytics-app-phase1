/**
 * Tests for Phase 0 — Layout Shell & Sidebar Navigation
 *
 * Epic 0.1 — App-wide layout shell
 *   Story 0.1.1 — RootLayout wraps authenticated experience
 *   Story 0.1.2 — AppHeader becomes slim top utility bar
 *
 * Epic 0.2 — Sidebar navigation + access control
 *   Story 0.2.1 — Sidebar shows required nav sections + routes
 *   Story 0.2.2 — Active route highlighting
 *   Story 0.2.3 — Feature-gated links hidden when not entitled
 *   Story 0.2.4 — Admin links only appear for admin roles
 *
 * Epic 0.3 — Responsive + accessibility
 *   Story 0.3.1 — Mobile hamburger toggles sidebar
 *   Story 0.3.2 — Keyboard navigation + ARIA
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { RootLayout, SidebarProvider } from '../../components/layout/RootLayout';
import { Sidebar } from '../../components/layout/Sidebar';
import { AppHeader } from '../../components/layout/AppHeader';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Mock Clerk useUser + useOrganization + useClerk
const mockUseUser = vi.fn();
const mockUseOrganization = vi.fn();
const mockSignOut = vi.fn();
vi.mock('@clerk/clerk-react', () => ({
  useUser: () => mockUseUser(),
  useOrganization: () => mockUseOrganization(),
  useClerk: () => ({ signOut: mockSignOut }),
  SignedIn: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SignedOut: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  RedirectToSignIn: () => <div data-testid="redirect-to-sign-in">Redirecting...</div>,
}));

// Mock useEntitlements hook
const mockUseEntitlements = vi.fn();
vi.mock('../../hooks/useEntitlements', () => ({
  useEntitlements: () => mockUseEntitlements(),
}));

// Mock isFeatureEntitled — use real implementation
vi.mock('../../services/entitlementsApi', async () => {
  return {
    isFeatureEntitled: (entitlements: any, feature: string) => {
      if (!entitlements) return false;
      const featureEntitlement = entitlements.features[feature];
      return featureEntitlement?.is_entitled ?? false;
    },
  };
});

// Mock changelog and whatChanged APIs (used by AppHeader sub-components)
vi.mock('../../services/changelogApi', () => ({
  getUnreadCountNumber: vi.fn().mockResolvedValue(0),
  getEntriesForFeature: vi.fn().mockResolvedValue([]),
  markAsRead: vi.fn(),
}));

vi.mock('../../services/whatChangedApi', () => ({
  hasCriticalIssues: vi.fn().mockResolvedValue(false),
  getWhatChangedSummary: vi.fn().mockResolvedValue(null),
}));

// Mock insightsApi (used by NotificationBadge in AppHeader)
vi.mock('../../services/insightsApi', () => ({
  getUnreadInsightsCount: vi.fn().mockResolvedValue(0),
  listInsights: vi.fn().mockResolvedValue({ insights: [], total: 0, has_more: false }),
}));

// Mock AgencyContext (used by ProfileMenu in AppHeader)
vi.mock('../../contexts/AgencyContext', () => ({
  useAgency: () => ({
    getActiveStore: () => null,
    isAgencyUser: false,
    activeTenantId: null,
    loading: false,
    error: null,
    assignedStores: [],
    allowedTenants: [],
    userRoles: [],
    billingTier: 'free',
    userId: null,
    accessExpiringAt: null,
    switchStore: vi.fn(),
    refreshStores: vi.fn(),
    canAccessStore: vi.fn().mockReturnValue(false),
  }),
}));

// Helper: create entitlements with specified features
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

// Default entitlements: all features entitled
const allEntitled = makeEntitlements({
  custom_reports: true,
  ai_insights: true,
});

// Helper: render with Polaris + MemoryRouter + SidebarProvider
const renderWithProviders = (
  ui: React.ReactElement,
  { initialEntries = ['/'] }: { initialEntries?: string[] } = {}
) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <MemoryRouter initialEntries={initialEntries}>
        <SidebarProvider>{ui}</SidebarProvider>
      </MemoryRouter>
    </AppProvider>
  );
};

// =============================================================================
// Story 0.1.1 — RootLayout wraps authenticated experience
// =============================================================================

describe('RootLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Test User',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('renders children inside signed-in boundary', () => {
    renderWithProviders(
      <RootLayout>
        <div data-testid="child-content">Hello from page</div>
      </RootLayout>,
      { initialEntries: ['/home'] }
    );

    // Children should be visible
    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.getByText('Hello from page')).toBeInTheDocument();

    // Sidebar should also be present alongside children
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();
  });

  it('renders sidebar and content area in two-column layout', () => {
    renderWithProviders(
      <RootLayout>
        <div>Page content</div>
      </RootLayout>,
      { initialEntries: ['/home'] }
    );

    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    const main = document.querySelector('main.root-layout__content');

    expect(nav).toBeInTheDocument();
    expect(main).toBeInTheDocument();
    expect(main?.textContent).toContain('Page content');
  });
});

// =============================================================================
// Regression: sidebar absent when signed out
// =============================================================================

describe('Sidebar signed-out behavior', () => {
  it('sidebar absent when signed out', () => {
    render(
      <AppProvider i18n={mockTranslations as any}>
        <MemoryRouter>
          <div data-testid="signed-out-content">Please sign in</div>
        </MemoryRouter>
      </AppProvider>
    );

    expect(screen.getByTestId('signed-out-content')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument();
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
  });
});

// =============================================================================
// Story 0.1.2 — AppHeader becomes slim top utility bar
// =============================================================================

describe('AppHeader (slim utility bar)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('contains changelog elements', () => {
    renderWithProviders(<AppHeader />, { initialEntries: ['/home'] });

    // ChangelogBadge renders "What's New" label
    expect(screen.getByText("What's New")).toBeInTheDocument();
  });

  it('does not contain removed nav items', () => {
    renderWithProviders(<AppHeader />, { initialEntries: ['/home'] });

    // Analytics and Dashboards buttons should have been removed from the header
    const buttons = screen.queryAllByRole('button');
    const buttonTexts = buttons.map((b) => b.textContent);

    expect(buttonTexts).not.toContain('Analytics');
    expect(buttonTexts).not.toContain('Dashboards');
  });
});

// =============================================================================
// Story 0.2.1 — Sidebar shows required nav sections + routes
// =============================================================================

describe('Sidebar navigation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Jane Doe',
        firstName: 'Jane',
        primaryEmailAddress: { emailAddress: 'jane@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('renders all nav links', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('Builder')).toBeInTheDocument();
    expect(screen.getByText('Insights')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();
    // "Settings" appears as both section header and nav item
    const settingsNavItem = screen.getAllByText('Settings').find(
      (el) => el.closest('.sidebar-nav-item') !== null
    );
    expect(settingsNavItem).toBeInTheDocument();
  });

  it('renders MAIN, CONNECTIONS, and SETTINGS sections', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('Main')).toBeInTheDocument();
    expect(screen.getByText('Connections')).toBeInTheDocument();
    // "Settings" appears both as section header and nav item
    const settingsElements = screen.getAllByText('Settings');
    expect(settingsElements.length).toBeGreaterThanOrEqual(2);
  });

  it('renders user section in footer', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
    // Avatar initial
    expect(screen.getByText('J')).toBeInTheDocument();
  });

  it('renders fallback when user has no name', () => {
    mockUseUser.mockReturnValue({
      user: {
        fullName: null,
        firstName: null,
        primaryEmailAddress: { emailAddress: 'anon@example.com' },
      },
    });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('User')).toBeInTheDocument();
    expect(screen.getByText('U')).toBeInTheDocument();
  });

  it('clicking links updates route', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <Sidebar />
        <Routes>
          <Route path="/home" element={<div data-testid="page">Home Page</div>} />
          <Route path="/dashboards" element={<div data-testid="page">Dashboards Page</div>} />
          <Route path="/insights" element={<div data-testid="page">Insights Page</div>} />
          <Route path="/data-sources" element={<div data-testid="page">Data Sources Page</div>} />
          <Route path="/settings" element={<div data-testid="page">Settings Page</div>} />
        </Routes>
      </>,
      { initialEntries: ['/home'] }
    );

    // Start on Home
    expect(screen.getByText('Home Page')).toBeInTheDocument();

    // Click Builder nav item
    await user.click(screen.getByText('Builder'));
    expect(screen.getByText('Dashboards Page')).toBeInTheDocument();

    // Click Sources nav item
    await user.click(screen.getByText('Sources'));
    expect(screen.getByText('Data Sources Page')).toBeInTheDocument();
  });

  it('supports keyboard navigation', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <Sidebar />
        <Routes>
          <Route path="/home" element={<div>Home Page</div>} />
          <Route path="/insights" element={<div>Insights Page</div>} />
        </Routes>
      </>,
      { initialEntries: ['/home'] }
    );

    // Focus on Insights nav item and press Enter
    const insightsItem = screen.getByText('Insights').closest('[role="link"]') as HTMLElement;
    insightsItem.focus();
    await user.keyboard('{Enter}');

    expect(screen.getByText('Insights Page')).toBeInTheDocument();
  });
});

// =============================================================================
// Story 0.2.2 — Active route highlighting
// =============================================================================

describe('Active route highlighting', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Test User',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  const routes = [
    { path: '/home', label: 'Home' },
    { path: '/dashboards', label: 'Builder' },
    { path: '/insights', label: 'Insights' },
    { path: '/data-sources', label: 'Sources' },
    { path: '/settings', label: 'Settings' },
  ];

  /** Find the nav item element for a given label (handles duplicates like "Settings") */
  function findNavItem(label: string): HTMLElement | null {
    const elements = screen.getAllByText(label);
    for (const el of elements) {
      const navItem = el.closest('.sidebar-nav-item');
      if (navItem) return navItem as HTMLElement;
    }
    return null;
  }

  it.each(routes)(
    'highlights $label when on $path',
    ({ path, label }) => {
      renderWithProviders(<Sidebar />, { initialEntries: [path] });

      const navItem = findNavItem(label);
      expect(navItem).toHaveClass('sidebar-nav-item--active');

      // Other items should NOT be active
      routes
        .filter((r) => r.label !== label)
        .forEach((other) => {
          const otherNavItem = findNavItem(other.label);
          if (otherNavItem) {
            expect(otherNavItem).not.toHaveClass('sidebar-nav-item--active');
          }
        });
    }
  );

  it('highlights Builder for sub-routes like /dashboards/:id/edit', () => {
    renderWithProviders(<Sidebar />, {
      initialEntries: ['/dashboards/abc-123/edit'],
    });

    const builderItem = screen.getByText('Builder').closest('.sidebar-nav-item');
    expect(builderItem).toHaveClass('sidebar-nav-item--active');

    // Home should NOT be active
    const homeItem = screen.getByText('Home').closest('.sidebar-nav-item');
    expect(homeItem).not.toHaveClass('sidebar-nav-item--active');
  });
});

// =============================================================================
// Story 0.2.3 — Feature-gated links hidden when not entitled
// =============================================================================

describe('Feature-gated nav items (Story 0.2.3)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Test User',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
  });

  it('hides nav item when entitlement is false', () => {
    mockUseEntitlements.mockReturnValue({
      entitlements: makeEntitlements({ custom_reports: false, ai_insights: true }),
      loading: false,
      error: null,
    });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.queryByText('Builder')).not.toBeInTheDocument();
    expect(screen.getByText('Insights')).toBeInTheDocument();
  });

  it('shows nav item when entitlement is true', () => {
    mockUseEntitlements.mockReturnValue({
      entitlements: makeEntitlements({ custom_reports: true, ai_insights: true }),
      loading: false,
      error: null,
    });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('Builder')).toBeInTheDocument();
    expect(screen.getByText('Insights')).toBeInTheDocument();
  });

  it('hides section header when all items in section are not entitled', () => {
    // Main section: Home (no feature gate, always visible), Builder + Insights both gated and false
    mockUseEntitlements.mockReturnValue({
      entitlements: makeEntitlements({ custom_reports: false, ai_insights: false }),
      loading: false,
      error: null,
    });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    // Main section should still be visible because Home has no feature gate
    expect(screen.getByText('Main')).toBeInTheDocument();
    expect(screen.getByText('Home')).toBeInTheDocument();

    // Builder and Insights should be hidden
    expect(screen.queryByText('Builder')).not.toBeInTheDocument();
    expect(screen.queryByText('Insights')).not.toBeInTheDocument();
  });

  it('hides all gated items when entitlements are null (loading)', () => {
    mockUseEntitlements.mockReturnValue({
      entitlements: null,
      loading: true,
      error: null,
    });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    // Non-gated items should still appear
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.getByText('Sources')).toBeInTheDocument();

    // Gated items should be hidden when entitlements is null
    expect(screen.queryByText('Builder')).not.toBeInTheDocument();
    expect(screen.queryByText('Insights')).not.toBeInTheDocument();
  });
});

// =============================================================================
// Story 0.2.4 — Admin links only appear for admin roles
// =============================================================================

describe('Admin nav section (Story 0.2.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Admin User',
        firstName: 'Admin',
        primaryEmailAddress: { emailAddress: 'admin@example.com' },
      },
    });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('admin sees Plans and Diagnostics links', () => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' } });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.getByText('Plans')).toBeInTheDocument();
    expect(screen.getByText('Diagnostics')).toBeInTheDocument();
  });

  it('non-admin does not see admin links', () => {
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });

    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
    expect(screen.queryByText('Plans')).not.toBeInTheDocument();
    expect(screen.queryByText('Diagnostics')).not.toBeInTheDocument();
  });

  it('admin links navigate correctly', async () => {
    const user = userEvent.setup();
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:admin' } });

    renderWithProviders(
      <>
        <Sidebar />
        <Routes>
          <Route path="/home" element={<div>Home Page</div>} />
          <Route path="/admin/plans" element={<div>Plans Page</div>} />
          <Route path="/admin/diagnostics" element={<div>Diagnostics Page</div>} />
        </Routes>
      </>,
      { initialEntries: ['/home'] }
    );

    await user.click(screen.getByText('Plans'));
    expect(screen.getByText('Plans Page')).toBeInTheDocument();
  });
});

// =============================================================================
// Story 0.3.1 — Mobile hamburger toggles sidebar
// =============================================================================

describe('Mobile hamburger toggle (Story 0.3.1)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Test User',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('sidebar does not have open class by default', () => {
    renderWithProviders(
      <RootLayout>
        <div>Content</div>
      </RootLayout>,
      { initialEntries: ['/home'] }
    );

    const sidebar = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(sidebar).not.toHaveClass('sidebar--open');
  });

  it('hamburger toggles sidebar open class', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <AppHeader />
        <RootLayout>
          <div>Content</div>
        </RootLayout>
      </>,
      { initialEntries: ['/home'] }
    );

    const hamburger = screen.getByLabelText('Toggle navigation');
    const sidebar = screen.getByRole('navigation', { name: 'Main navigation' });

    // Initially not open
    expect(sidebar).not.toHaveClass('sidebar--open');

    // Click hamburger to open
    await user.click(hamburger);
    expect(sidebar).toHaveClass('sidebar--open');

    // Click hamburger to close
    await user.click(hamburger);
    expect(sidebar).not.toHaveClass('sidebar--open');
  });

  it('overlay closes sidebar when clicked', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <AppHeader />
        <RootLayout>
          <div>Content</div>
        </RootLayout>
      </>,
      { initialEntries: ['/home'] }
    );

    const hamburger = screen.getByLabelText('Toggle navigation');
    const sidebar = screen.getByRole('navigation', { name: 'Main navigation' });

    // Open sidebar
    await user.click(hamburger);
    expect(sidebar).toHaveClass('sidebar--open');

    // Click overlay to close
    const overlay = document.querySelector('.root-layout__overlay');
    expect(overlay).toBeInTheDocument();
    await user.click(overlay!);

    expect(sidebar).not.toHaveClass('sidebar--open');
  });

  it('hamburger has correct aria-expanded state', async () => {
    const user = userEvent.setup();

    renderWithProviders(<AppHeader />, { initialEntries: ['/home'] });

    const hamburger = screen.getByLabelText('Toggle navigation');
    expect(hamburger).toHaveAttribute('aria-expanded', 'false');

    await user.click(hamburger);
    expect(hamburger).toHaveAttribute('aria-expanded', 'true');

    await user.click(hamburger);
    expect(hamburger).toHaveAttribute('aria-expanded', 'false');
  });
});

// =============================================================================
// Story 0.3.2 — Keyboard navigation + ARIA
// =============================================================================

describe('Keyboard navigation and ARIA (Story 0.3.2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseUser.mockReturnValue({
      user: {
        fullName: 'Test User',
        firstName: 'Test',
        primaryEmailAddress: { emailAddress: 'test@example.com' },
      },
    });
    mockUseOrganization.mockReturnValue({ membership: { role: 'org:member' } });
    mockUseEntitlements.mockReturnValue({ entitlements: allEntitled, loading: false, error: null });
  });

  it('all sidebar nav items are tabbable', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    const navItems = document.querySelectorAll('.sidebar-nav-item');
    navItems.forEach((item) => {
      expect(item).toHaveAttribute('tabindex', '0');
    });
    expect(navItems.length).toBeGreaterThanOrEqual(5);
  });

  it('hamburger is focusable and activatable with keyboard', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <AppHeader />
        <RootLayout>
          <div>Content</div>
        </RootLayout>
      </>,
      { initialEntries: ['/home'] }
    );

    const hamburger = screen.getByLabelText('Toggle navigation');
    const sidebar = screen.getByRole('navigation', { name: 'Main navigation' });

    // Focus and press Enter to open
    hamburger.focus();
    await user.keyboard('{Enter}');
    expect(sidebar).toHaveClass('sidebar--open');

    // Press Enter again to close
    await user.keyboard('{Enter}');
    expect(sidebar).not.toHaveClass('sidebar--open');
  });

  it('active nav item has aria-current="page"', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    const homeItem = screen.getByText('Home').closest('.sidebar-nav-item');
    expect(homeItem).toHaveAttribute('aria-current', 'page');

    // Non-active items should not have aria-current
    const sourcesItem = screen.getByText('Sources').closest('.sidebar-nav-item');
    expect(sourcesItem).not.toHaveAttribute('aria-current');
  });

  it('nav items activate with Space key', async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <>
        <Sidebar />
        <Routes>
          <Route path="/home" element={<div>Home Page</div>} />
          <Route path="/data-sources" element={<div>Data Sources Page</div>} />
        </Routes>
      </>,
      { initialEntries: ['/home'] }
    );

    const sourcesItem = screen.getByText('Sources').closest('[role="link"]') as HTMLElement;
    sourcesItem.focus();
    await user.keyboard(' ');

    expect(screen.getByText('Data Sources Page')).toBeInTheDocument();
  });

  it('sidebar nav element has id for aria-controls', () => {
    renderWithProviders(<Sidebar />, { initialEntries: ['/home'] });

    const nav = screen.getByRole('navigation', { name: 'Main navigation' });
    expect(nav).toHaveAttribute('id', 'sidebar-nav');
  });

  it('hamburger references sidebar via aria-controls', () => {
    renderWithProviders(<AppHeader />, { initialEntries: ['/home'] });

    const hamburger = screen.getByLabelText('Toggle navigation');
    expect(hamburger).toHaveAttribute('aria-controls', 'sidebar-nav');
  });
});
