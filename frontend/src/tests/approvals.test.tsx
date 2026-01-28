/**
 * Tests for Approval Components
 *
 * Story 9.4 - Action Approval UX
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { ProposalCard } from '../components/approvals/ProposalCard';
import { ApprovalConfirmationModal } from '../components/approvals/ApprovalConfirmationModal';
import { AuditTrail } from '../components/approvals/AuditTrail';
import { PendingApprovalsBadge } from '../components/approvals/PendingApprovalsBadge';
import type { ActionProposal, AuditEntry } from '../types/actionProposals';

// Mock translations
const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

// Helper to render with Polaris provider
const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// Mock proposal data
const createMockProposal = (overrides?: Partial<ActionProposal>): ActionProposal => ({
  proposal_id: 'prop-123',
  action_type: 'adjust_budget',
  status: 'proposed',
  target: {
    platform: 'meta',
    entity_type: 'campaign',
    entity_id: 'camp-456',
    entity_name: 'Summer Sale Campaign',
  },
  proposed_change: { budget: 1500 },
  current_value: { budget: 1000 },
  expected_effect: 'May increase reach by 15% based on historical data',
  risk_disclaimer: 'Budget changes may affect campaign performance',
  risk_level: 'medium',
  confidence_score: 0.82,
  requires_approval: true,
  expires_at: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString(), // 7 days from now
  created_at: new Date().toISOString(),
  decided_at: null,
  decided_by: null,
  decision_reason: null,
  source_recommendation_id: 'rec-789',
  ...overrides,
});

// Mock audit entries
const createMockAuditEntries = (): AuditEntry[] => [
  {
    id: 'audit-1',
    action: 'created',
    performed_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString(),
    performed_by: null,
    performed_by_role: null,
    previous_status: null,
    new_status: 'proposed',
    reason: null,
  },
  {
    id: 'audit-2',
    action: 'approved',
    performed_at: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(),
    performed_by: 'user-123',
    performed_by_role: 'MERCHANT_ADMIN',
    previous_status: 'proposed',
    new_status: 'approved',
    reason: null,
  },
];

// Mock API
vi.mock('../services/actionProposalsApi', () => ({
  getPendingProposalsCount: vi.fn().mockResolvedValue(3),
}));

describe('ProposalCard', () => {
  describe('rendering', () => {
    it('displays proposal details', () => {
      const proposal = createMockProposal();
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText(/Summer Sale Campaign/)).toBeInTheDocument();
      // Adjust Budget appears in badge and heading - use getAllByText
      expect(screen.getAllByText(/Adjust Budget/).length).toBeGreaterThan(0);
      // Meta Ads appears combined with entity type as "Meta Ads • campaign"
      expect(screen.getByText(/Meta Ads/)).toBeInTheDocument();
    });

    it('shows status badge', () => {
      const proposal = createMockProposal({ status: 'proposed' });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText('Pending Approval')).toBeInTheDocument();
    });

    it('shows risk level badge', () => {
      const proposal = createMockProposal({ risk_level: 'high' });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText('High Risk')).toBeInTheDocument();
    });

    it('shows expected effect', () => {
      const proposal = createMockProposal();
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(
        screen.getByText(/May increase reach by 15%/)
      ).toBeInTheDocument();
    });

    it('shows risk disclaimer warning', () => {
      const proposal = createMockProposal();
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(
        screen.getByText(/Budget changes may affect campaign performance/)
      ).toBeInTheDocument();
    });

    it('shows expiry countdown for pending proposals', () => {
      const proposal = createMockProposal({ status: 'proposed' });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText(/Expires in/)).toBeInTheDocument();
    });

    it('shows approved status for approved proposals', () => {
      const proposal = createMockProposal({ status: 'approved' });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText('Approved')).toBeInTheDocument();
    });

    it('shows rejected status for rejected proposals', () => {
      const proposal = createMockProposal({ status: 'rejected' });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(screen.getByText('Rejected')).toBeInTheDocument();
    });
  });

  describe('expandable details', () => {
    it('shows details when expanded', async () => {
      const user = userEvent.setup();
      const proposal = createMockProposal();
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      await user.click(screen.getByText('Show details'));

      expect(screen.getByText(/Proposed Change/)).toBeInTheDocument();
      expect(screen.getByText(/Current Value/)).toBeInTheDocument();
      expect(screen.getByText(/Confidence/)).toBeInTheDocument();
    });
  });

  describe('actions', () => {
    it('shows approve and reject buttons for pending proposals', () => {
      const proposal = createMockProposal({ status: 'proposed' });
      renderWithPolaris(
        <ProposalCard
          proposal={proposal}
          onApprove={vi.fn()}
          onReject={vi.fn()}
        />
      );

      expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
    });

    it('hides action buttons for decided proposals', () => {
      const proposal = createMockProposal({ status: 'approved' });
      renderWithPolaris(
        <ProposalCard
          proposal={proposal}
          onApprove={vi.fn()}
          onReject={vi.fn()}
        />
      );

      expect(
        screen.queryByRole('button', { name: /approve/i })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /reject/i })
      ).not.toBeInTheDocument();
    });

    it('shows permission message when user cannot approve', () => {
      const proposal = createMockProposal({ status: 'proposed' });
      renderWithPolaris(
        <ProposalCard
          proposal={proposal}
          onApprove={vi.fn()}
          onReject={vi.fn()}
          canApprove={false}
        />
      );

      expect(
        screen.getByText(/do not have permission/)
      ).toBeInTheDocument();
    });

    it('calls onViewAudit when audit trail link clicked', async () => {
      const user = userEvent.setup();
      const onViewAudit = vi.fn();
      const proposal = createMockProposal();

      renderWithPolaris(
        <ProposalCard proposal={proposal} onViewAudit={onViewAudit} />
      );

      await user.click(screen.getByText('View audit trail'));

      expect(onViewAudit).toHaveBeenCalledWith('prop-123');
    });
  });

  describe('expired proposals', () => {
    it('shows expired notice for expired proposals', () => {
      const proposal = createMockProposal({
        status: 'proposed',
        expires_at: new Date(Date.now() - 1000).toISOString(), // Expired
      });
      renderWithPolaris(<ProposalCard proposal={proposal} />);

      expect(
        screen.getByText(/has expired and can no longer be approved/)
      ).toBeInTheDocument();
    });

    it('hides action buttons for expired proposals', () => {
      const proposal = createMockProposal({
        status: 'proposed',
        expires_at: new Date(Date.now() - 1000).toISOString(), // Expired
      });
      renderWithPolaris(
        <ProposalCard
          proposal={proposal}
          onApprove={vi.fn()}
          onReject={vi.fn()}
        />
      );

      expect(
        screen.queryByRole('button', { name: /approve/i })
      ).not.toBeInTheDocument();
    });
  });
});

describe('ApprovalConfirmationModal', () => {
  describe('approve action', () => {
    it('shows approval confirmation content', () => {
      const proposal = createMockProposal();
      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="approve"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(screen.getByText('Confirm Approval')).toBeInTheDocument();
      expect(screen.getByText(/authorize this action/)).toBeInTheDocument();
    });

    it('requires acknowledgment for high risk proposals', () => {
      const proposal = createMockProposal({ risk_level: 'high' });
      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="approve"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(
        screen.getByText(/understand the risks/)
      ).toBeInTheDocument();
    });

    it('calls onConfirm when approve button clicked', async () => {
      const user = userEvent.setup();
      const onConfirm = vi.fn();
      const proposal = createMockProposal({ risk_level: 'low' });

      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="approve"
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );

      await user.click(screen.getByRole('button', { name: /approve/i }));

      expect(onConfirm).toHaveBeenCalled();
    });

    it('calls onCancel when cancel button clicked', async () => {
      const user = userEvent.setup();
      const onCancel = vi.fn();
      const proposal = createMockProposal();

      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="approve"
          onConfirm={vi.fn()}
          onCancel={onCancel}
        />
      );

      await user.click(screen.getByRole('button', { name: /cancel/i }));

      expect(onCancel).toHaveBeenCalled();
    });
  });

  describe('reject action', () => {
    it('shows rejection confirmation content', () => {
      const proposal = createMockProposal();
      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="reject"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(screen.getByText('Confirm Rejection')).toBeInTheDocument();
    });

    it('shows reason field for rejection', () => {
      const proposal = createMockProposal();
      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="reject"
          onConfirm={vi.fn()}
          onCancel={vi.fn()}
        />
      );

      expect(
        screen.getByLabelText(/Reason for rejection/)
      ).toBeInTheDocument();
    });

    it('passes reason to onConfirm when provided', async () => {
      const user = userEvent.setup();
      const onConfirm = vi.fn();
      const proposal = createMockProposal();

      renderWithPolaris(
        <ApprovalConfirmationModal
          open={true}
          proposal={proposal}
          action="reject"
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );

      const reasonInput = screen.getByLabelText(/Reason for rejection/);
      await user.type(reasonInput, 'Not the right time');
      await user.click(screen.getByRole('button', { name: /reject/i }));

      expect(onConfirm).toHaveBeenCalledWith('Not the right time');
    });
  });
});

describe('AuditTrail', () => {
  it('shows audit entries in order', () => {
    const entries = createMockAuditEntries();
    renderWithPolaris(<AuditTrail entries={entries} />);

    expect(screen.getByText('Proposal Created')).toBeInTheDocument();
    // 'Approved' appears both as action and as status badge, so use getAllByText
    expect(screen.getAllByText('Approved').length).toBeGreaterThan(0);
  });

  it('shows performer info when available', () => {
    const entries = createMockAuditEntries();
    renderWithPolaris(<AuditTrail entries={entries} />);

    expect(screen.getByText(/user-123/)).toBeInTheDocument();
    expect(screen.getByText(/MERCHANT_ADMIN/)).toBeInTheDocument();
  });

  it('shows empty state when no entries', () => {
    renderWithPolaris(<AuditTrail entries={[]} />);

    expect(screen.getByText(/No audit entries found/)).toBeInTheDocument();
  });

  it('shows loading state', () => {
    renderWithPolaris(<AuditTrail entries={[]} isLoading />);

    // Skeleton should be present
    expect(screen.getByText('Audit Trail')).toBeInTheDocument();
  });

  it('shows reason when provided', () => {
    const entries: AuditEntry[] = [
      {
        id: 'audit-1',
        action: 'rejected',
        performed_at: new Date().toISOString(),
        performed_by: 'user-123',
        performed_by_role: 'MERCHANT_ADMIN',
        previous_status: 'proposed',
        new_status: 'rejected',
        reason: 'Budget constraints',
      },
    ];
    renderWithPolaris(<AuditTrail entries={entries} />);

    expect(screen.getByText(/Budget constraints/)).toBeInTheDocument();
  });
});

describe('PendingApprovalsBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows count of pending approvals', async () => {
    renderWithPolaris(<PendingApprovalsBadge refreshInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument();
    });
  });

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    renderWithPolaris(<PendingApprovalsBadge onClick={onClick} refreshInterval={0} />);

    await waitFor(() => {
      expect(screen.getByText('3')).toBeInTheDocument();
    });

    await user.click(screen.getByLabelText(/pending approvals/i));
    expect(onClick).toHaveBeenCalled();
  });

  it('shows label when showLabel is true', async () => {
    renderWithPolaris(
      <PendingApprovalsBadge showLabel label="My Approvals" refreshInterval={0} />
    );

    await waitFor(() => {
      expect(screen.getByText('My Approvals')).toBeInTheDocument();
    });
  });
});
