/**
 * ApprovalConfirmationModal Component
 *
 * Modal for explicit confirmation before approving or rejecting a proposal.
 * Shows impact and risk summary, requires acknowledgment.
 *
 * Story 9.4 - Action Approval UX
 */

import { useState, useCallback } from 'react';
import {
  Modal,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  TextField,
  Banner,
  Checkbox,
  Box,
} from '@shopify/polaris';
import { AlertTriangleIcon } from '@shopify/polaris-icons';
import type { ActionProposal } from '../../types/actionProposals';
import {
  getActionTypeLabel,
  getRiskTone,
  getPlatformLabel,
} from '../../types/actionProposals';

interface ApprovalConfirmationModalProps {
  open: boolean;
  proposal: ActionProposal;
  action: 'approve' | 'reject';
  onConfirm: (reason?: string) => void;
  onCancel: () => void;
  isLoading?: boolean;
}

export function ApprovalConfirmationModal({
  open,
  proposal,
  action,
  onConfirm,
  onCancel,
  isLoading = false,
}: ApprovalConfirmationModalProps) {
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);

  const isApprove = action === 'approve';
  const isHighRisk = proposal.risk_level === 'high';

  const handleConfirm = useCallback(() => {
    onConfirm(reason || undefined);
    setReason('');
    setAcknowledged(false);
  }, [onConfirm, reason]);

  const handleCancel = useCallback(() => {
    onCancel();
    setReason('');
    setAcknowledged(false);
  }, [onCancel]);

  const canConfirm = isApprove
    ? (isHighRisk ? acknowledged : true)
    : true; // Rejection always allowed

  return (
    <Modal
      open={open}
      onClose={handleCancel}
      title={isApprove ? 'Confirm Approval' : 'Confirm Rejection'}
      primaryAction={{
        content: isApprove ? 'Approve' : 'Reject',
        onAction: handleConfirm,
        loading: isLoading,
        disabled: !canConfirm,
        destructive: !isApprove,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: handleCancel,
        },
      ]}
    >
      <Modal.Section>
        <BlockStack gap="400">
          {/* Proposal summary */}
          <BlockStack gap="200">
            <Text as="h3" variant="headingSm">
              {getActionTypeLabel(proposal.action_type)}
            </Text>
            <Text as="p" variant="bodyMd">
              {proposal.target.entity_name || proposal.target.entity_id}
            </Text>
            <Text as="p" variant="bodySm" tone="subdued">
              {getPlatformLabel(proposal.target.platform)} • {proposal.target.entity_type}
            </Text>
          </BlockStack>

          {/* Impact and Risk */}
          <InlineStack gap="400">
            <InlineStack gap="100" blockAlign="center">
              <Text as="span" variant="bodySm" tone="subdued">
                Risk Level:
              </Text>
              <Badge tone={getRiskTone(proposal.risk_level)}>
                {proposal.risk_level.charAt(0).toUpperCase() + proposal.risk_level.slice(1)}
              </Badge>
            </InlineStack>
            <InlineStack gap="100" blockAlign="center">
              <Text as="span" variant="bodySm" tone="subdued">
                Confidence:
              </Text>
              <Text as="span" variant="bodySm">
                {Math.round(proposal.confidence_score * 100)}%
              </Text>
            </InlineStack>
          </InlineStack>

          {/* Expected effect */}
          <Box>
            <Text as="p" variant="bodyMd">
              <Text as="span" fontWeight="semibold">Expected Effect: </Text>
              {proposal.expected_effect}
            </Text>
          </Box>

          {/* Risk disclaimer for approval */}
          {isApprove && proposal.risk_disclaimer && (
            <Banner tone="warning" icon={AlertTriangleIcon}>
              <Text as="p" variant="bodySm">
                {proposal.risk_disclaimer}
              </Text>
            </Banner>
          )}

          {/* High risk acknowledgment for approval */}
          {isApprove && isHighRisk && (
            <Checkbox
              label="I understand the risks and want to proceed with this high-risk action"
              checked={acknowledged}
              onChange={setAcknowledged}
            />
          )}

          {/* Approval confirmation message */}
          {isApprove && (
            <Banner tone="info">
              <Text as="p" variant="bodySm">
                By approving, you authorize this action to be executed. An audit record will be created.
              </Text>
            </Banner>
          )}

          {/* Rejection reason (optional) */}
          {!isApprove && (
            <TextField
              label="Reason for rejection (optional)"
              value={reason}
              onChange={setReason}
              multiline={3}
              autoComplete="off"
              helpText="Providing a reason helps improve future recommendations"
            />
          )}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}

export default ApprovalConfirmationModal;
