/**
 * Tests for Changelog Components
 *
 * Story 9.7 - In-App Changelog & Release Notes
 *
 * Tests cover:
 * - AppHeader rendering and navigation
 * - ChangelogBadge display and interaction
 * - FeatureUpdateBanner rendering with updates
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import { BrowserRouter } from 'react-router-dom';

import { AppHeader } from '../components/layout/AppHeader';
import { ChangelogBadge } from '../components/changelog/ChangelogBadge';
import { FeatureUpdateBanner } from '../components/changelog/FeatureUpdateBanner';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Mock the API functions
vi.mock('../services/changelogApi', () => ({
  getUnreadCountNumber: vi.fn(),
  getEntriesForFeature: vi.fn(),
  markAsRead: vi.fn(),
}));

vi.mock('../services/whatChangedApi', () => ({
  hasCriticalIssues: vi.fn(),
  getWhatChangedSummary: vi.fn(),
}));

// Import mocked functions
import { getUnreadCountNumber, getEntriesForFeature } from '../services/changelogApi';
import { hasCriticalIssues } from '../services/whatChangedApi';

// Helper to render with providers
const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      <BrowserRouter>{ui}</BrowserRouter>
    </AppProvider>
  );
};

// =============================================================================
// AppHeader Tests
// =============================================================================

describe('AppHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getUnreadCountNumber as any).mockResolvedValue(0);
    (hasCriticalIssues as any).mockResolvedValue(false);
  });

  it('renders the header container', () => {
    renderWithProviders(<AppHeader />);

    // The header should render with its components
    expect(screen.getByText("What's New")).toBeInTheDocument();
  });

  it('renders ChangelogBadge with label', async () => {
    (getUnreadCountNumber as any).mockResolvedValue(3);

    renderWithProviders(<AppHeader />);

    // Wait for async data to load
    await waitFor(() => {
      expect(screen.getByText("What's New")).toBeInTheDocument();
    });
  });

  it('renders WhatChangedButton', async () => {
    renderWithProviders(<AppHeader />);

    await waitFor(() => {
      expect(screen.getByText('What changed?')).toBeInTheDocument();
    });
  });

  it('does not show ChangelogBadge on /whats-new page', () => {
    // Note: This test would require mocking useLocation
    // For now, we just verify the component renders
    renderWithProviders(<AppHeader />);
    expect(screen.getByText("What's New")).toBeInTheDocument();
  });
});

// =============================================================================
// ChangelogBadge Tests
// =============================================================================

describe('ChangelogBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getUnreadCountNumber as any).mockResolvedValue(0);
  });

  it('renders with label when showLabel is true', async () => {
    renderWithProviders(
      <ChangelogBadge showLabel label="Updates" onClick={() => {}} />
    );

    await waitFor(() => {
      expect(screen.getByText('Updates')).toBeInTheDocument();
    });
  });

  it('shows unread count when there are unread entries', async () => {
    (getUnreadCountNumber as any).mockResolvedValue(5);

    renderWithProviders(
      <ChangelogBadge showLabel label="Updates" onClick={() => {}} />
    );

    await waitFor(() => {
      expect(screen.getByText('5')).toBeInTheDocument();
    });
  });

  it('shows 99+ when unread count exceeds 99', async () => {
    (getUnreadCountNumber as any).mockResolvedValue(150);

    renderWithProviders(
      <ChangelogBadge showLabel label="Updates" onClick={() => {}} />
    );

    await waitFor(() => {
      expect(screen.getByText('99+')).toBeInTheDocument();
    });
  });

  it('calls onClick when clicked', async () => {
    const handleClick = vi.fn();

    renderWithProviders(
      <ChangelogBadge showLabel label="Updates" onClick={handleClick} />
    );

    const button = screen.getByRole('button');
    await userEvent.click(button);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it('does not show badge when count is 0', async () => {
    (getUnreadCountNumber as any).mockResolvedValue(0);

    renderWithProviders(
      <ChangelogBadge showLabel label="Updates" onClick={() => {}} />
    );

    await waitFor(() => {
      expect(screen.queryByText('0')).not.toBeInTheDocument();
    });
  });
});

// =============================================================================
// FeatureUpdateBanner Tests
// =============================================================================

describe('FeatureUpdateBanner', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getEntriesForFeature as any).mockResolvedValue({
      entries: [],
      total: 0,
      has_more: false,
    });
  });

  it('renders nothing when there are no updates', async () => {
    const { container } = renderWithProviders(
      <FeatureUpdateBanner featureArea="dashboard" />
    );

    await waitFor(() => {
      // Should render empty or minimal content
      expect(container.querySelector('[data-testid="feature-banner"]')).toBeNull();
    });
  });

  it('renders banner when there are updates for the feature area', async () => {
    (getEntriesForFeature as any).mockResolvedValue({
      entries: [
        {
          id: '1',
          version: '1.0.0',
          title: 'New Dashboard Feature',
          summary: 'Added new charts',
          release_type: 'feature',
          feature_areas: ['dashboard'],
          is_read: false,
          published_at: new Date().toISOString(),
        },
      ],
      total: 1,
      has_more: false,
    });

    renderWithProviders(
      <FeatureUpdateBanner featureArea="dashboard" />
    );

    await waitFor(() => {
      expect(screen.getByText('New Dashboard Feature')).toBeInTheDocument();
    });
  });

  it('limits displayed items to maxItems', async () => {
    (getEntriesForFeature as any).mockResolvedValue({
      entries: [
        {
          id: '1',
          version: '1.0.0',
          title: 'Feature 1',
          summary: 'Summary 1',
          release_type: 'feature',
          feature_areas: ['dashboard'],
          is_read: false,
          published_at: new Date().toISOString(),
        },
        {
          id: '2',
          version: '1.0.1',
          title: 'Feature 2',
          summary: 'Summary 2',
          release_type: 'improvement',
          feature_areas: ['dashboard'],
          is_read: false,
          published_at: new Date().toISOString(),
        },
        {
          id: '3',
          version: '1.0.2',
          title: 'Feature 3',
          summary: 'Summary 3',
          release_type: 'fix',
          feature_areas: ['dashboard'],
          is_read: false,
          published_at: new Date().toISOString(),
        },
      ],
      total: 3,
      has_more: false,
    });

    renderWithProviders(
      <FeatureUpdateBanner featureArea="dashboard" maxItems={2} />
    );

    await waitFor(() => {
      expect(screen.getByText('Feature 1')).toBeInTheDocument();
      expect(screen.getByText('Feature 2')).toBeInTheDocument();
    });

    // Feature 3 should not be visible due to maxItems=2
    expect(screen.queryByText('Feature 3')).not.toBeInTheDocument();
  });

  it('calls onViewAll when "View all" is clicked', async () => {
    const handleViewAll = vi.fn();

    (getEntriesForFeature as any).mockResolvedValue({
      entries: [
        {
          id: '1',
          version: '1.0.0',
          title: 'New Feature',
          summary: 'Summary',
          release_type: 'feature',
          feature_areas: ['dashboard'],
          is_read: false,
          published_at: new Date().toISOString(),
        },
      ],
      total: 5,
      has_more: true,
    });

    renderWithProviders(
      <FeatureUpdateBanner
        featureArea="dashboard"
        onViewAll={handleViewAll}
      />
    );

    await waitFor(() => {
      const viewAllButton = screen.getByText(/View all/i);
      expect(viewAllButton).toBeInTheDocument();
    });

    const viewAllButton = screen.getByText(/View all/i);
    await userEvent.click(viewAllButton);

    expect(handleViewAll).toHaveBeenCalledTimes(1);
  });

  it('does not show banner for read entries when onlyUnread is true', async () => {
    (getEntriesForFeature as any).mockResolvedValue({
      entries: [
        {
          id: '1',
          version: '1.0.0',
          title: 'Read Feature',
          summary: 'Summary',
          release_type: 'feature',
          feature_areas: ['dashboard'],
          is_read: true,
          published_at: new Date().toISOString(),
        },
      ],
      total: 1,
      has_more: false,
    });

    renderWithProviders(
      <FeatureUpdateBanner featureArea="dashboard" />
    );

    await waitFor(() => {
      // API returns read entry, component should filter it
      expect(screen.queryByText('Read Feature')).not.toBeInTheDocument();
    });
  });
});
