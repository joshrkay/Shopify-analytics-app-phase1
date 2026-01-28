/**
 * ProposalCard Component
 *
 * Displays a single action proposal with impact, risk, and approval actions.
 * Supports inline approve/reject with confirmation modal.
 *
 * Story 9.4 - Action Approval UX
 */

import { useState } from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Box,
  Divider,
  Icon,
  Banner,
  Collapsible,
} from '@shopify/polaris';
import {
  AlertTriangleIcon,
  ClockIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from '@shopify/polaris-icons';
import type { ActionProposal } from '../../types/actionProposals';
import {
  getActionTypeLabel,
  getStatusLabel,
  getStatusTone,
  getRiskTone,
  getPlatformLabel,
  canDecideProposal,
  isProposalExpired,
} from '../../types/actionProposals';
import { ApprovalConfirmationModal } from './ApprovalConfirmationModal';

interface ProposalCardProps {
  proposal: ActionProposal;
  onApprove?: (proposalId: string) => void;
  onReject?: (proposalId: string, reason?: string) => void;
  onViewAudit?: (proposalId: string) => void;
  isLoading?: boolean;
  /**
   * Whether user has permission to approve/reject.
   */
  canApprove?: boolean;
}

/**
 * Format relative time for display.
 */
function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 60) {
    return `${diffMins}m ago`;
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  if (diffDays < 7) {
    return `${diffDays}d ago`;
  }
  return date.toLocaleDateString();
}

/**
 * Format expiry time for display.
 */
function formatExpiryTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMs <= 0) {
    return 'Expired';
  }
  if (diffHours < 24) {
    return `Expires in ${diffHours}h`;
  }
  return `Expires in ${diffDays}d`;
}

/**
 * Format proposed change for display.
 */
function formatProposedChange(change: Record<string, unknown>): string {
  const entries = Object.entries(change);
  if (entries.length === 0) return 'No changes specified';

  return entries
    .map(([key, value]) => {
      const formattedKey = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
      return `${formattedKey}: ${JSON.stringify(value)}`;
    })
    .join(', ');
}

export function ProposalCard({
  proposal,
  onApprove,
  onReject,
  onViewAudit,
  isLoading = false,
  canApprove = true,
}: ProposalCardProps) {
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [isDetailsExpanded, setIsDetailsExpanded] = useState(false);

  const canDecide = canDecideProposal(proposal) && canApprove;
  const expired = isProposalExpired(proposal);
  const statusTone = getStatusTone(proposal.status);

  const handleApproveClick = () => {
    setShowApproveModal(true);
  };

  const handleRejectClick = () => {
    setShowRejectModal(true);
  };

  const handleApproveConfirm = () => {
    if (onApprove) {
      onApprove(proposal.proposal_id);
    }
    setShowApproveModal(false);
  };

  const handleRejectConfirm = (reason?: string) => {
    if (onReject) {
      onReject(proposal.proposal_id, reason);
    }
    setShowRejectModal(false);
  };

  return (
    <>
      <Card>
        <BlockStack gap="300">
          {/* Header with badges */}
          <InlineStack align="space-between" blockAlign="start">
            <InlineStack gap="200" blockAlign="center">
              <Badge tone={statusTone}>
                {getStatusLabel(proposal.status)}
              </Badge>
              <Badge tone={getRiskTone(proposal.risk_level)}>
                {`${proposal.risk_level.charAt(0).toUpperCase()}${proposal.risk_level.slice(1)} Risk`}
              </Badge>
              <Badge tone="info">
                {getActionTypeLabel(proposal.action_type)}
              </Badge>
            </InlineStack>
            <InlineStack gap="100" blockAlign="center">
              <Icon source={ClockIcon} tone="subdued" />
              <Text as="span" variant="bodySm" tone="subdued">
                {formatRelativeTime(proposal.created_at)}
              </Text>
            </InlineStack>
          </InlineStack>

          {/* Target info */}
          <BlockStack gap="100">
            <Text as="h3" variant="headingSm">
              {getActionTypeLabel(proposal.action_type)} on {proposal.target.entity_name || proposal.target.entity_id}
            </Text>
            <Text as="p" variant="bodySm" tone="subdued">
              {getPlatformLabel(proposal.target.platform)} • {proposal.target.entity_type}
            </Text>
          </BlockStack>

          {/* Expected effect */}
          <Box paddingBlockStart="100">
            <Text as="p" variant="bodyMd">
              {proposal.expected_effect}
            </Text>
          </Box>

          {/* Risk disclaimer */}
          {proposal.risk_disclaimer && (
            <Banner tone="warning" icon={AlertTriangleIcon}>
              <Text as="p" variant="bodySm">
                {proposal.risk_disclaimer}
              </Text>
            </Banner>
          )}

          {/* Expiry warning for pending proposals */}
          {proposal.status === 'proposed' && !expired && (
            <InlineStack gap="100" blockAlign="center">
              <Icon source={ClockIcon} tone="warning" />
              <Text as="span" variant="bodySm" tone="caution">
                {formatExpiryTime(proposal.expires_at)}
              </Text>
            </InlineStack>
          )}

          {/* Expired notice */}
          {expired && (
            <Banner tone="critical">
              <Text as="p" variant="bodySm">
                This proposal has expired and can no longer be approved.
              </Text>
            </Banner>
          )}

          {/* Expandable details */}
          <Button
            variant="plain"
            onClick={() => setIsDetailsExpanded(!isDetailsExpanded)}
            icon={isDetailsExpanded ? ChevronUpIcon : ChevronDownIcon}
            disclosure={isDetailsExpanded ? 'up' : 'down'}
          >
            {isDetailsExpanded ? 'Hide details' : 'Show details'}
          </Button>
          <Collapsible
            open={isDetailsExpanded}
            id={`details-${proposal.proposal_id}`}
            transition={{ duration: '200ms', timingFunction: 'ease-in-out' }}
          >
            <Box paddingBlockStart="200">
              <BlockStack gap="200">
                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" fontWeight="semibold">
                    Proposed Change:
                  </Text>
                  <Text as="span" variant="bodySm">
                    {formatProposedChange(proposal.proposed_change)}
                  </Text>
                </InlineStack>
                {proposal.current_value && (
                  <InlineStack gap="200">
                    <Text as="span" variant="bodySm" fontWeight="semibold">
                      Current Value:
                    </Text>
                    <Text as="span" variant="bodySm">
                      {formatProposedChange(proposal.current_value)}
                    </Text>
                  </InlineStack>
                )}
                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" fontWeight="semibold">
                    Confidence:
                  </Text>
                  <Text as="span" variant="bodySm">
                    {Math.round(proposal.confidence_score * 100)}%
                  </Text>
                </InlineStack>
                {proposal.decided_at && (
                  <InlineStack gap="200">
                    <Text as="span" variant="bodySm" fontWeight="semibold">
                      Decided:
                    </Text>
                    <Text as="span" variant="bodySm">
                      {new Date(proposal.decided_at).toLocaleString()}
                      {proposal.decided_by && ` by ${proposal.decided_by}`}
                    </Text>
                  </InlineStack>
                )}
                {proposal.decision_reason && (
                  <InlineStack gap="200">
                    <Text as="span" variant="bodySm" fontWeight="semibold">
                      Reason:
                    </Text>
                    <Text as="span" variant="bodySm">
                      {proposal.decision_reason}
                    </Text>
                  </InlineStack>
                )}
              </BlockStack>
            </Box>
          </Collapsible>

          <Divider />

          {/* Actions */}
          <InlineStack align="space-between">
            <div>
              {onViewAudit && (
                <Button
                  variant="plain"
                  onClick={() => onViewAudit(proposal.proposal_id)}
                >
                  View audit trail
                </Button>
              )}
            </div>
            {canDecide && (
              <InlineStack gap="200">
                <Button
                  variant="secondary"
                  tone="critical"
                  onClick={handleRejectClick}
                  loading={isLoading}
                >
                  Reject
                </Button>
                <Button
                  variant="primary"
                  onClick={handleApproveClick}
                  loading={isLoading}
                >
                  Approve
                </Button>
              </InlineStack>
            )}
            {!canDecide && !canApprove && proposal.status === 'proposed' && (
              <Text as="span" variant="bodySm" tone="subdued">
                You do not have permission to approve this proposal
              </Text>
            )}
          </InlineStack>
        </BlockStack>
      </Card>

      {/* Approval confirmation modal */}
      <ApprovalConfirmationModal
        open={showApproveModal}
        proposal={proposal}
        action="approve"
        onConfirm={handleApproveConfirm}
        onCancel={() => setShowApproveModal(false)}
        isLoading={isLoading}
      />

      {/* Rejection confirmation modal */}
      <ApprovalConfirmationModal
        open={showRejectModal}
        proposal={proposal}
        action="reject"
        onConfirm={handleRejectConfirm}
        onCancel={() => setShowRejectModal(false)}
        isLoading={isLoading}
      />
    </>
  );
}

export default ProposalCard;
