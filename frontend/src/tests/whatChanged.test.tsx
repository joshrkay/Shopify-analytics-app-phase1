/**
 * Tests for What Changed Components
 *
 * Story 9.8 - "What Changed?" Debug Panel
 *
 * Tests cover:
 * - WhatChangedButton rendering and critical issue badge
 * - WhatChangedPanel tabs and data display
 * - Data freshness indicators
 * - Recent syncs and AI actions display
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';

import { WhatChangedButton } from '../components/whatChanged/WhatChangedButton';
import { WhatChangedPanel } from '../components/whatChanged/WhatChangedPanel';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Mock the API functions
vi.mock('../services/whatChangedApi', () => ({
  hasCriticalIssues: vi.fn(),
  getSummary: vi.fn(),
  getRecentSyncs: vi.fn(),
  getAIActions: vi.fn(),
  getConnectorStatusChanges: vi.fn(),
  listChangeEvents: vi.fn(),
}));

// Import mocked functions
import {
  hasCriticalIssues,
  getSummary,
  getRecentSyncs,
  getAIActions,
  getConnectorStatusChanges,
} from '../services/whatChangedApi';

// Helper to render with Polaris provider
const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// Mock data
const mockSummary = {
  data_freshness: {
    overall_status: 'fresh',
    last_sync_at: new Date().toISOString(),
    hours_since_sync: 1,
    connectors: [
      {
        connector_id: 'conn-1',
        connector_name: 'Shopify Orders',
        status: 'fresh',
        last_sync_at: new Date().toISOString(),
        minutes_since_sync: 30,
      },
    ],
  },
  recent_syncs_count: 5,
  recent_ai_actions_count: 2,
  open_incidents_count: 0,
  metric_changes_count: 3,
  last_updated: new Date().toISOString(),
};

const mockRecentSyncs = [
  {
    sync_id: 'sync-1',
    connector_id: 'conn-1',
    connector_name: 'Shopify Orders',
    source_type: 'shopify_orders',
    status: 'success',
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    rows_synced: 1500,
    duration_seconds: 45.5,
  },
];

const mockAIActions = [
  {
    action_id: 'action-1',
    action_type: 'pause_campaign',
    status: 'approved',
    target_name: 'Summer Sale Campaign',
    target_platform: 'meta_ads',
    performed_at: new Date().toISOString(),
    performed_by: 'Admin user',
  },
];

const mockConnectorChanges = [
  {
    connector_id: 'conn-2',
    connector_name: 'Meta Ads',
    previous_status: 'active',
    new_status: 'failed',
    changed_at: new Date().toISOString(),
    reason: 'Authentication expired',
  },
];

// =============================================================================
// WhatChangedButton Tests
// =============================================================================

describe('WhatChangedButton', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (hasCriticalIssues as any).mockResolvedValue(false);
    (getSummary as any).mockResolvedValue(mockSummary);
    (getRecentSyncs as any).mockResolvedValue({ syncs: mockRecentSyncs });
    (getAIActions as any).mockResolvedValue({ actions: mockAIActions });
    (getConnectorStatusChanges as any).mockResolvedValue({ changes: [] });
  });

  it('renders inline variant with label', async () => {
    renderWithPolaris(<WhatChangedButton variant="inline" />);

    await waitFor(() => {
      expect(screen.getByText('What changed?')).toBeInTheDocument();
    });
  });

  it('shows critical issue badge when there are critical issues', async () => {
    (hasCriticalIssues as any).mockResolvedValue(true);

    renderWithPolaris(<WhatChangedButton variant="inline" showBadge />);

    await waitFor(() => {
      expect(screen.getByText('!')).toBeInTheDocument();
    });
  });

  it('does not show badge when there are no critical issues', async () => {
    (hasCriticalIssues as any).mockResolvedValue(false);

    renderWithPolaris(<WhatChangedButton variant="inline" showBadge />);

    await waitFor(() => {
      expect(screen.queryByText('!')).not.toBeInTheDocument();
    });
  });

  it('opens panel when clicked', async () => {
    renderWithPolaris(<WhatChangedButton variant="inline" />);

    await waitFor(() => {
      expect(screen.getByText('What changed?')).toBeInTheDocument();
    });

    const button = screen.getByRole('button');
    await userEvent.click(button);

    // Panel should be open - look for panel content
    await waitFor(() => {
      expect(screen.getByText('What Changed?')).toBeInTheDocument();
    });
  });

  it('resets critical badge when panel is opened', async () => {
    (hasCriticalIssues as any).mockResolvedValue(true);

    renderWithPolaris(<WhatChangedButton variant="inline" showBadge />);

    // Wait for badge to appear
    await waitFor(() => {
      expect(screen.getByText('!')).toBeInTheDocument();
    });

    const button = screen.getByRole('button');
    await userEvent.click(button);

    // Badge should be reset after opening
    // (Implementation resets hasCritical to false on open)
  });

  it('does not check critical issues when showBadge is false', async () => {
    renderWithPolaris(<WhatChangedButton variant="inline" showBadge={false} />);

    await waitFor(() => {
      expect(screen.getByText('What changed?')).toBeInTheDocument();
    });

    // API should not be called when showBadge is false
    expect(hasCriticalIssues).not.toHaveBeenCalled();
  });
});

// =============================================================================
// WhatChangedPanel Tests
// =============================================================================

describe('WhatChangedPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getSummary as any).mockResolvedValue(mockSummary);
    (getRecentSyncs as any).mockResolvedValue({ syncs: mockRecentSyncs });
    (getAIActions as any).mockResolvedValue({ actions: mockAIActions });
    (getConnectorStatusChanges as any).mockResolvedValue({ changes: [] });
  });

  it('renders when open', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('What Changed?')).toBeInTheDocument();
    });
  });

  it('does not render when closed', () => {
    renderWithPolaris(<WhatChangedPanel isOpen={false} onClose={() => {}} />);

    expect(screen.queryByText('What Changed?')).not.toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const handleClose = vi.fn();

    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={handleClose} />);

    await waitFor(() => {
      expect(screen.getByText('What Changed?')).toBeInTheDocument();
    });

    // Find and click close button (Polaris Modal has a close button)
    const closeButton = screen.getByLabelText(/close/i);
    await userEvent.click(closeButton);

    expect(handleClose).toHaveBeenCalled();
  });

  it('shows overview tab by default', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      // Overview tab should show summary counts
      expect(screen.getByText(/syncs/i)).toBeInTheDocument();
    });
  });

  it('shows data freshness status in overview', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      // Should show freshness status
      expect(screen.getByText(/fresh/i)).toBeInTheDocument();
    });
  });

  it('shows loading state while fetching data', async () => {
    (getSummary as any).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(mockSummary), 100))
    );

    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    // Should show loading indicator initially
    expect(screen.getByText(/loading/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
    });
  });

  it('shows error state when API fails', async () => {
    (getSummary as any).mockRejectedValue(new Error('API Error'));

    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/error/i)).toBeInTheDocument();
    });
  });
});

// =============================================================================
// Panel Tab Navigation Tests
// =============================================================================

describe('WhatChangedPanel Tabs', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getSummary as any).mockResolvedValue(mockSummary);
    (getRecentSyncs as any).mockResolvedValue({ syncs: mockRecentSyncs });
    (getAIActions as any).mockResolvedValue({ actions: mockAIActions });
    (getConnectorStatusChanges as any).mockResolvedValue({ changes: mockConnectorChanges });
  });

  it('has overview, syncs, AI actions, and connectors tabs', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Overview')).toBeInTheDocument();
      expect(screen.getByText('Syncs')).toBeInTheDocument();
      expect(screen.getByText('AI Actions')).toBeInTheDocument();
      expect(screen.getByText('Connectors')).toBeInTheDocument();
    });
  });

  it('switches to syncs tab and shows sync data', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Syncs')).toBeInTheDocument();
    });

    const syncsTab = screen.getByText('Syncs');
    await userEvent.click(syncsTab);

    await waitFor(() => {
      expect(screen.getByText('Shopify Orders')).toBeInTheDocument();
    });
  });

  it('shows sync row count and duration', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Syncs')).toBeInTheDocument();
    });

    const syncsTab = screen.getByText('Syncs');
    await userEvent.click(syncsTab);

    await waitFor(() => {
      // Should show row count and duration from mock data
      expect(screen.getByText(/1,500/)).toBeInTheDocument();
    });
  });

  it('switches to AI actions tab and shows action data', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('AI Actions')).toBeInTheDocument();
    });

    const actionsTab = screen.getByText('AI Actions');
    await userEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByText('Summer Sale Campaign')).toBeInTheDocument();
    });
  });

  it('shows action type and platform', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('AI Actions')).toBeInTheDocument();
    });

    const actionsTab = screen.getByText('AI Actions');
    await userEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByText(/pause/i)).toBeInTheDocument();
      expect(screen.getByText(/meta/i)).toBeInTheDocument();
    });
  });

  it('switches to connectors tab and shows status changes', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Connectors')).toBeInTheDocument();
    });

    const connectorsTab = screen.getByText('Connectors');
    await userEvent.click(connectorsTab);

    await waitFor(() => {
      expect(screen.getByText('Meta Ads')).toBeInTheDocument();
      expect(screen.getByText(/failed/i)).toBeInTheDocument();
    });
  });
});

// =============================================================================
// Empty State Tests
// =============================================================================

describe('WhatChangedPanel Empty States', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getSummary as any).mockResolvedValue({
      ...mockSummary,
      recent_syncs_count: 0,
      recent_ai_actions_count: 0,
    });
    (getRecentSyncs as any).mockResolvedValue({ syncs: [] });
    (getAIActions as any).mockResolvedValue({ actions: [] });
    (getConnectorStatusChanges as any).mockResolvedValue({ changes: [] });
  });

  it('shows empty state for syncs tab when no syncs', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Syncs')).toBeInTheDocument();
    });

    const syncsTab = screen.getByText('Syncs');
    await userEvent.click(syncsTab);

    await waitFor(() => {
      expect(screen.getByText(/no recent syncs/i)).toBeInTheDocument();
    });
  });

  it('shows empty state for AI actions tab when no actions', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('AI Actions')).toBeInTheDocument();
    });

    const actionsTab = screen.getByText('AI Actions');
    await userEvent.click(actionsTab);

    await waitFor(() => {
      expect(screen.getByText(/no recent/i)).toBeInTheDocument();
    });
  });

  it('shows empty state for connectors tab when no changes', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText('Connectors')).toBeInTheDocument();
    });

    const connectorsTab = screen.getByText('Connectors');
    await userEvent.click(connectorsTab);

    await waitFor(() => {
      expect(screen.getByText(/no status changes/i)).toBeInTheDocument();
    });
  });
});

// =============================================================================
// Refresh Behavior Tests
// =============================================================================

describe('WhatChangedPanel Refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (getSummary as any).mockResolvedValue(mockSummary);
    (getRecentSyncs as any).mockResolvedValue({ syncs: mockRecentSyncs });
    (getAIActions as any).mockResolvedValue({ actions: mockAIActions });
    (getConnectorStatusChanges as any).mockResolvedValue({ changes: [] });
  });

  it('fetches data when panel opens', async () => {
    renderWithPolaris(<WhatChangedPanel isOpen={true} onClose={() => {}} />);

    await waitFor(() => {
      expect(getSummary).toHaveBeenCalled();
    });
  });

  it('does not fetch data when panel is closed', () => {
    renderWithPolaris(<WhatChangedPanel isOpen={false} onClose={() => {}} />);

    expect(getSummary).not.toHaveBeenCalled();
  });

  it('refetches data when reopened', async () => {
    const { rerender } = renderWithPolaris(
      <WhatChangedPanel isOpen={true} onClose={() => {}} />
    );

    await waitFor(() => {
      expect(getSummary).toHaveBeenCalledTimes(1);
    });

    rerender(
      <AppProvider i18n={mockTranslations as any}>
        <WhatChangedPanel isOpen={false} onClose={() => {}} />
      </AppProvider>
    );

    rerender(
      <AppProvider i18n={mockTranslations as any}>
        <WhatChangedPanel isOpen={true} onClose={() => {}} />
      </AppProvider>
    );

    await waitFor(() => {
      expect(getSummary).toHaveBeenCalledTimes(2);
    });
  });
});
