/**
 * NotificationBadge Component
 *
 * Generic badge component for displaying notification counts.
 * Used for insights, changelog, and other notification indicators.
 *
 * Consolidates duplicate logic from InsightBadge and ChangelogBadge.
 */

import { useState, useEffect, useCallback } from 'react';
import { Badge, Spinner, InlineStack, Text, Tooltip } from '@shopify/polaris';

interface NotificationBadgeProps {
  /**
   * Function to fetch the count. Should return a Promise<number>.
   */
  fetchCount: () => Promise<number>;
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
  /**
   * Tooltip text template. Use {count} as placeholder for the count.
   * Default: "{count} new item(s)"
   */
  tooltipTemplate?: string;
  /**
   * Badge tone.
   * Default: "attention"
   */
  tone?: 'info' | 'success' | 'warning' | 'critical' | 'attention';
  /**
   * Singular noun for tooltip (e.g., "insight", "update").
   */
  singularNoun?: string;
  /**
   * Plural noun for tooltip (e.g., "insights", "updates").
   */
  pluralNoun?: string;
}

export function NotificationBadge({
  fetchCount,
  onClick,
  refreshInterval = 60000,
  showLabel = false,
  label = 'Notifications',
  tone = 'attention',
  singularNoun = 'item',
  pluralNoun = 'items',
}: NotificationBadgeProps) {
  const [count, setCount] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  const loadCount = useCallback(async () => {
    try {
      const unreadCount = await fetchCount();
      setCount(unreadCount);
      setError(false);
    } catch (err) {
      console.error('Failed to fetch notification count:', err);
      setError(true);
    } finally {
      setIsLoading(false);
    }
  }, [fetchCount]);

  useEffect(() => {
    loadCount();

    if (refreshInterval > 0) {
      const interval = setInterval(loadCount, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [loadCount, refreshInterval]);

  // Loading state
  if (isLoading && count === null) {
    if (showLabel) {
      return (
        <InlineStack gap="100" blockAlign="center">
          <Text as="span" variant="bodySm">
            {label}
          </Text>
          <Spinner size="small" />
        </InlineStack>
      );
    }
    return <Spinner size="small" />;
  }

  // Error or no items state
  if (error || count === null || count === 0) {
    if (showLabel) {
      return (
        <Text as="span" variant="bodySm" tone="subdued">
          {label}
        </Text>
      );
    }
    return null;
  }

  const displayCount = count > 99 ? '99+' : count.toString();
  const tooltipText = `${count} ${count === 1 ? singularNoun : pluralNoun}`;

  const badge = <Badge tone={tone}>{displayCount}</Badge>;

  const badgeContent = showLabel ? (
    <InlineStack gap="100" blockAlign="center">
      <Text as="span" variant="bodySm">
        {label}
      </Text>
      {badge}
    </InlineStack>
  ) : (
    badge
  );

  if (onClick) {
    return (
      <Tooltip content={tooltipText}>
        <button
          type="button"
          onClick={onClick}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
          }}
          aria-label={tooltipText}
        >
          {badgeContent}
        </button>
      </Tooltip>
    );
  }

  return <Tooltip content={tooltipText}>{badgeContent}</Tooltip>;
}

export default NotificationBadge;
