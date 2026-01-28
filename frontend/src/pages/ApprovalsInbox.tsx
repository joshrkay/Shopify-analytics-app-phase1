/**
 * ApprovalsInbox Page
 *
 * Central inbox for action proposal approvals.
 * Supports filtering by status, inline approve/reject, and audit trail viewing.
 *
 * Story 9.4 - Action Approval UX
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  BlockStack,
  InlineStack,
  Text,
  Select,
  Tabs,
  Banner,
  Spinner,
  EmptyState,
  Pagination,
  Modal,
} from '@shopify/polaris';
import { ProposalCard } from '../components/approvals/ProposalCard';
import { AuditTrail } from '../components/approvals/AuditTrail';
import type {
  ActionProposal,
  ActionStatus,
  TargetPlatform,
  RiskLevel,
  AuditEntry,
} from '../types/actionProposals';
import {
  listActionProposals,
  approveProposal,
  rejectProposal,
  getProposalAuditTrail,
} from '../services/actionProposalsApi';

const PAGE_SIZE = 10;

type TabId = 'pending' | 'decided' | 'all';

const statusOptions = [
  { label: 'All Statuses', value: '' },
  { label: 'Pending Approval', value: 'proposed' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'Expired', value: 'expired' },
  { label: 'Executed', value: 'executed' },
  { label: 'Failed', value: 'failed' },
];

const platformOptions = [
  { label: 'All Platforms', value: '' },
  { label: 'Meta Ads', value: 'meta' },
  { label: 'Google Ads', value: 'google' },
  { label: 'TikTok Ads', value: 'tiktok' },
];

const riskOptions = [
  { label: 'All Risk Levels', value: '' },
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];

export function ApprovalsInbox() {
  // State
  const [proposals, setProposals] = useState<ActionProposal[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState<TabId>('pending');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [platformFilter, setPlatformFilter] = useState<string>('');
  const [riskFilter, setRiskFilter] = useState<string>('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);

  // Audit trail modal state
  const [auditModalOpen, setAuditModalOpen] = useState(false);
  const [, setSelectedProposalId] = useState<string | null>(null);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [isLoadingAudit, setIsLoadingAudit] = useState(false);

  // Action loading states
  const [actionLoadingIds, setActionLoadingIds] = useState<Set<string>>(new Set());

  // Determine status filter based on tab
  const getEffectiveStatusFilter = useCallback((): ActionStatus | undefined => {
    if (statusFilter) {
      return statusFilter as ActionStatus;
    }
    switch (selectedTab) {
      case 'pending':
        return 'proposed';
      case 'decided':
        return undefined; // Will filter client-side
      default:
        return undefined;
    }
  }, [selectedTab, statusFilter]);

  // Fetch proposals
  const fetchProposals = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const effectiveStatus = getEffectiveStatusFilter();
      const response = await listActionProposals({
        status: effectiveStatus,
        platform: platformFilter as TargetPlatform | undefined,
        risk_level: riskFilter as RiskLevel | undefined,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      });

      // Filter based on tab if no explicit status filter
      let filtered = response.proposals;
      if (!statusFilter && selectedTab === 'decided') {
        filtered = filtered.filter(p =>
          p.status !== 'proposed'
        );
      }

      setProposals(filtered);
      setTotal(response.total);
      setHasMore(response.has_more);
      setPendingCount(response.pending_count);
    } catch (err) {
      console.error('Failed to fetch proposals:', err);
      setError('Failed to load action proposals. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter, platformFilter, riskFilter, selectedTab, page, getEffectiveStatusFilter]);

  useEffect(() => {
    fetchProposals();
  }, [fetchProposals]);

  // Handle approve
  const handleApprove = async (proposalId: string) => {
    setActionLoadingIds(prev => new Set(prev).add(proposalId));
    try {
      const response = await approveProposal(proposalId);
      // Update local state
      setProposals(prev =>
        prev.map(p =>
          p.proposal_id === proposalId
            ? { ...p, status: response.new_status, decided_at: new Date().toISOString() }
            : p
        )
      );
      // If on pending tab, remove from list
      if (selectedTab === 'pending') {
        setProposals(prev => prev.filter(p => p.proposal_id !== proposalId));
        setPendingCount(prev => Math.max(0, prev - 1));
      }
    } catch (err) {
      console.error('Failed to approve proposal:', err);
      setError('Failed to approve proposal. Please try again.');
    } finally {
      setActionLoadingIds(prev => {
        const next = new Set(prev);
        next.delete(proposalId);
        return next;
      });
    }
  };

  // Handle reject
  const handleReject = async (proposalId: string, reason?: string) => {
    setActionLoadingIds(prev => new Set(prev).add(proposalId));
    try {
      const response = await rejectProposal(proposalId, reason);
      // Update local state
      setProposals(prev =>
        prev.map(p =>
          p.proposal_id === proposalId
            ? {
                ...p,
                status: response.new_status,
                decided_at: new Date().toISOString(),
                decision_reason: reason || null,
              }
            : p
        )
      );
      // If on pending tab, remove from list
      if (selectedTab === 'pending') {
        setProposals(prev => prev.filter(p => p.proposal_id !== proposalId));
        setPendingCount(prev => Math.max(0, prev - 1));
      }
    } catch (err) {
      console.error('Failed to reject proposal:', err);
      setError('Failed to reject proposal. Please try again.');
    } finally {
      setActionLoadingIds(prev => {
        const next = new Set(prev);
        next.delete(proposalId);
        return next;
      });
    }
  };

  // Handle view audit trail
  const handleViewAudit = async (proposalId: string) => {
    setSelectedProposalId(proposalId);
    setAuditModalOpen(true);
    setIsLoadingAudit(true);

    try {
      const response = await getProposalAuditTrail(proposalId);
      setAuditEntries(response.entries);
    } catch (err) {
      console.error('Failed to fetch audit trail:', err);
      setAuditEntries([]);
    } finally {
      setIsLoadingAudit(false);
    }
  };

  // Tab change handler
  const handleTabChange = (selectedTabIndex: number) => {
    const tabIds: TabId[] = ['pending', 'decided', 'all'];
    setSelectedTab(tabIds[selectedTabIndex]);
    setPage(1);
    setStatusFilter(''); // Reset status filter on tab change
  };

  // Pagination handlers
  const handleNextPage = () => {
    if (hasMore) {
      setPage(prev => prev + 1);
    }
  };

  const handlePreviousPage = () => {
    if (page > 1) {
      setPage(prev => prev - 1);
    }
  };

  const tabs = [
    {
      id: 'pending',
      content: pendingCount > 0 ? `Pending (${pendingCount})` : 'Pending',
      accessibilityLabel: 'Pending approvals',
      panelID: 'pending-panel',
    },
    {
      id: 'decided',
      content: 'Decided',
      accessibilityLabel: 'Decided proposals',
      panelID: 'decided-panel',
    },
    {
      id: 'all',
      content: 'All',
      accessibilityLabel: 'All proposals',
      panelID: 'all-panel',
    },
  ];

  const selectedTabIndex = tabs.findIndex(t => t.id === selectedTab);

  return (
    <Page
      title="Action Approvals"
      subtitle="Review and approve AI-proposed actions"
    >
      <Layout>
        <Layout.Section>
          <Card>
            <Tabs
              tabs={tabs}
              selected={selectedTabIndex}
              onSelect={handleTabChange}
            >
              <BlockStack gap="400">
                {/* Filters */}
                <InlineStack gap="400">
                  {selectedTab === 'all' && (
                    <Select
                      label="Status"
                      labelInline
                      options={statusOptions}
                      value={statusFilter}
                      onChange={setStatusFilter}
                    />
                  )}
                  <Select
                    label="Platform"
                    labelInline
                    options={platformOptions}
                    value={platformFilter}
                    onChange={setPlatformFilter}
                  />
                  <Select
                    label="Risk"
                    labelInline
                    options={riskOptions}
                    value={riskFilter}
                    onChange={setRiskFilter}
                  />
                </InlineStack>

                {/* Error banner */}
                {error && (
                  <Banner tone="critical" onDismiss={() => setError(null)}>
                    {error}
                  </Banner>
                )}

                {/* Loading state */}
                {isLoading && (
                  <InlineStack align="center">
                    <Spinner size="large" />
                  </InlineStack>
                )}

                {/* Empty state */}
                {!isLoading && proposals.length === 0 && (
                  <EmptyState
                    heading={
                      selectedTab === 'pending'
                        ? 'No pending approvals'
                        : selectedTab === 'decided'
                        ? 'No decided proposals'
                        : 'No action proposals'
                    }
                    image=""
                  >
                    <Text as="p" variant="bodyMd" tone="subdued">
                      {selectedTab === 'pending'
                        ? 'All action proposals have been reviewed. Check back later for new proposals.'
                        : selectedTab === 'decided'
                        ? 'No proposals have been approved or rejected yet.'
                        : 'No action proposals have been generated yet.'}
                    </Text>
                  </EmptyState>
                )}

                {/* Proposals list */}
                {!isLoading && proposals.length > 0 && (
                  <BlockStack gap="400">
                    {proposals.map(proposal => (
                      <ProposalCard
                        key={proposal.proposal_id}
                        proposal={proposal}
                        onApprove={handleApprove}
                        onReject={handleReject}
                        onViewAudit={handleViewAudit}
                        isLoading={actionLoadingIds.has(proposal.proposal_id)}
                        canApprove={true}
                      />
                    ))}
                  </BlockStack>
                )}

                {/* Pagination */}
                {!isLoading && total > PAGE_SIZE && (
                  <InlineStack align="center">
                    <Pagination
                      hasPrevious={page > 1}
                      hasNext={hasMore}
                      onPrevious={handlePreviousPage}
                      onNext={handleNextPage}
                    />
                  </InlineStack>
                )}

                {/* Total count */}
                {!isLoading && proposals.length > 0 && (
                  <Text as="p" variant="bodySm" tone="subdued" alignment="center">
                    Showing {proposals.length} of {total} proposals
                  </Text>
                )}
              </BlockStack>
            </Tabs>
          </Card>
        </Layout.Section>
      </Layout>

      {/* Audit Trail Modal */}
      <Modal
        open={auditModalOpen}
        onClose={() => setAuditModalOpen(false)}
        title="Audit Trail"
        size="large"
      >
        <Modal.Section>
          {isLoadingAudit ? (
            <InlineStack align="center">
              <Spinner size="large" />
            </InlineStack>
          ) : (
            <AuditTrail entries={auditEntries} />
          )}
        </Modal.Section>
      </Modal>
    </Page>
  );
}

export default ApprovalsInbox;
