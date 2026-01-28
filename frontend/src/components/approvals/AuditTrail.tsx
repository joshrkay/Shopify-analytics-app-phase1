/**
 * AuditTrail Component
 *
 * Displays the audit trail for an action proposal.
 * Shows all state changes in chronological order.
 *
 * Story 9.4 - Action Approval UX
 */

import React from 'react';
import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Icon,
  Box,
  Divider,
  SkeletonBodyText,
} from '@shopify/polaris';
import {
  PlusCircleIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  AlertCircleIcon,
} from '@shopify/polaris-icons';
import type { AuditEntry, AuditAction } from '../../types/actionProposals';
import { getStatusTone } from '../../types/actionProposals';

interface AuditTrailProps {
  entries: AuditEntry[];
  isLoading?: boolean;
}

/**
 * Get icon for audit action.
 */
function getActionIcon(action: AuditAction) {
  switch (action) {
    case 'created':
      return PlusCircleIcon;
    case 'approved':
    case 'executed':
      return CheckCircleIcon;
    case 'rejected':
    case 'failed':
      return XCircleIcon;
    case 'expired':
    case 'cancelled':
      return ClockIcon;
    case 'rolled_back':
      return AlertCircleIcon;
    default:
      return AlertCircleIcon;
  }
}

/**
 * Get icon tone for audit action.
 */
function getActionTone(action: AuditAction): 'base' | 'subdued' | 'success' | 'critical' | 'warning' {
  switch (action) {
    case 'created':
      return 'base';
    case 'approved':
    case 'executed':
      return 'success';
    case 'rejected':
    case 'failed':
      return 'critical';
    case 'expired':
    case 'cancelled':
      return 'subdued';
    case 'rolled_back':
      return 'warning';
    default:
      return 'base';
  }
}

/**
 * Get human-readable action label.
 */
function getActionLabel(action: AuditAction): string {
  const labels: Record<AuditAction, string> = {
    created: 'Proposal Created',
    approved: 'Approved',
    rejected: 'Rejected',
    expired: 'Expired',
    cancelled: 'Cancelled',
    executed: 'Executed',
    failed: 'Execution Failed',
    rolled_back: 'Rolled Back',
  };
  return labels[action] || action;
}

/**
 * Format datetime for display.
 */
function formatDateTime(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Single audit entry row.
 */
function AuditEntryRow({ entry }: { entry: AuditEntry }) {
  const ActionIcon = getActionIcon(entry.action);
  const iconTone = getActionTone(entry.action);
  const statusTone = getStatusTone(entry.new_status);

  return (
    <Box paddingBlockStart="300" paddingBlockEnd="300">
      <InlineStack gap="300" blockAlign="start">
        <Box>
          <Icon source={ActionIcon} tone={iconTone} />
        </Box>
        <BlockStack gap="100">
          <InlineStack gap="200" blockAlign="center">
            <Text as="span" variant="bodyMd" fontWeight="semibold">
              {getActionLabel(entry.action)}
            </Text>
            <Badge tone={statusTone}>
              {entry.new_status.charAt(0).toUpperCase() + entry.new_status.slice(1)}
            </Badge>
          </InlineStack>

          <Text as="p" variant="bodySm" tone="subdued">
            {formatDateTime(entry.performed_at)}
            {entry.performed_by && (
              <> by {entry.performed_by}</>
            )}
            {entry.performed_by_role && (
              <> ({entry.performed_by_role})</>
            )}
          </Text>

          {entry.reason && (
            <Box paddingBlockStart="100">
              <Text as="p" variant="bodySm">
                Reason: {entry.reason}
              </Text>
            </Box>
          )}

          {entry.previous_status && (
            <Text as="p" variant="bodySm" tone="subdued">
              Changed from: {entry.previous_status}
            </Text>
          )}
        </BlockStack>
      </InlineStack>
    </Box>
  );
}

export function AuditTrail({ entries, isLoading = false }: AuditTrailProps) {
  if (isLoading) {
    return (
      <Card>
        <BlockStack gap="400">
          <Text as="h3" variant="headingSm">
            Audit Trail
          </Text>
          <SkeletonBodyText lines={4} />
        </BlockStack>
      </Card>
    );
  }

  if (entries.length === 0) {
    return (
      <Card>
        <BlockStack gap="300">
          <Text as="h3" variant="headingSm">
            Audit Trail
          </Text>
          <Text as="p" variant="bodySm" tone="subdued">
            No audit entries found.
          </Text>
        </BlockStack>
      </Card>
    );
  }

  return (
    <Card>
      <BlockStack gap="200">
        <Text as="h3" variant="headingSm">
          Audit Trail
        </Text>
        <Divider />
        <BlockStack gap="0">
          {entries.map((entry, index) => (
            <React.Fragment key={entry.id}>
              <AuditEntryRow entry={entry} />
              {index < entries.length - 1 && <Divider />}
            </React.Fragment>
          ))}
        </BlockStack>
      </BlockStack>
    </Card>
  );
}

export default AuditTrail;
