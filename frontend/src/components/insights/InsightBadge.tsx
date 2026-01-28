/**
 * InsightBadge Component
 *
 * Contextual badge showing unread insights count.
 * Can be placed on dashboards or navigation items.
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import { useEffect, useState } from 'react';
import { Badge, Spinner, InlineStack, Text, Tooltip } from '@shopify/polaris';
import { getUnreadInsightsCount } from '../../services/insightsApi';

interface InsightBadgeProps {
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

export function InsightBadge({
  onClick,
  refreshInterval = 60000,
  showLabel = false,
  label = 'Insights',
}: InsightBadgeProps) {
  const [count, setCount] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchCount = async () => {
    try {
      const unreadCount = await getUnreadInsightsCount();
      setCount(unreadCount);
      setError(null);
    } catch (err) {
      console.error('Failed to fetch insights count:', err);
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
      <Badge tone="attention">{count > 99 ? '99+' : count.toString()}</Badge>
    </InlineStack>
  );

  if (onClick) {
    return (
      <Tooltip content={`${count} unread insight${count !== 1 ? 's' : ''}`}>
        <button
          onClick={onClick}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
          }}
          aria-label={`${count} unread insights`}
        >
          {badgeContent}
        </button>
      </Tooltip>
    );
  }

  return (
    <Tooltip content={`${count} unread insight${count !== 1 ? 's' : ''}`}>
      {badgeContent}
    </Tooltip>
  );
}

export default InsightBadge;
