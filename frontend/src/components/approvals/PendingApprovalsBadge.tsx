/**
 * PendingApprovalsBadge Component
 *
 * Contextual badge showing pending approvals count.
 * Can be placed on navigation items or dashboard.
 *
 * Story 9.4 - Action Approval UX
 */

import { useEffect, useState } from 'react';
import { Badge, Spinner, InlineStack, Text, Tooltip } from '@shopify/polaris';
import { getPendingProposalsCount } from '../../services/actionProposalsApi';

interface PendingApprovalsBadgeProps {
  /**
   * Optional click handler when badge is clicked.
   */
  onClick?: () => void;
  /**
   * Refresh interval in milliseconds. Set to 0 to disable auto-refresh.
   * Default: 60000 (1 minute)
   */
  refreshInterval?: number;
  /**
   * Show text label alongside count.
   */
  showLabel?: boolean;
  /**
   * Custom label text.
   */
  label?: string;
}

export function PendingApprovalsBadge({
  onClick,
  refreshInterval = 60000,
  showLabel = false,
  label = 'Approvals',
}: PendingApprovalsBadgeProps) {
  const [count, setCount] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCount = async () => {
    try {
      const pendingCount = await getPendingProposalsCount();
      setCount(pendingCount);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch pending approvals count:', err);
      setError('Failed to load');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCount();

    if (refreshInterval > 0) {
      const interval = setInterval(fetchCount, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [refreshInterval]);

  if (isLoading) {
    return <Spinner size="small" />;
  }

  if (error || count === null) {
    return null;
  }

  if (count === 0) {
    return null;
  }

  const badgeContent = (
    <InlineStack gap="100" blockAlign="center">
      {showLabel && (
        <Text as="span" variant="bodySm">
          {label}
        </Text>
      )}
      <Badge tone="warning">{count > 99 ? '99+' : count.toString()}</Badge>
    </InlineStack>
  );

  if (onClick) {
    return (
      <Tooltip content={`${count} pending approval${count !== 1 ? 's' : ''}`}>
        <button
          onClick={onClick}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
          }}
          aria-label={`${count} pending approvals`}
        >
          {badgeContent}
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={`${count} pending approval${count !== 1 ? 's' : ''}`}>
      {badgeContent}
    </Tooltip>
  );
}

export default PendingApprovalsBadge;
