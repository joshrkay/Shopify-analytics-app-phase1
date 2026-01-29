/**
 * DataFreshnessBadge Component
 *
 * Compact badge showing data freshness status.
 * Designed for header/navigation placement.
 *
 * Visual states:
 * - Green (success): All data fresh
 * - Yellow (attention): Some data stale
 * - Red (critical): Critical issues
 *
 * Story 9.5 - Data Freshness Indicators
 */

import { Badge, Spinner, InlineStack, Text, Tooltip, Icon } from '@shopify/polaris';
import { ClockIcon, AlertCircleIcon } from '@shopify/polaris-icons';
import { useFreshnessStatus } from '../../contexts/DataHealthContext';

interface DataFreshnessBadgeProps {
  /**
   * Optional click handler (e.g., navigate to SyncHealth page).
   */
  onClick?: () => void;
  /**
   * Show text label alongside badge.
   */
  showLabel?: boolean;
  /**
   * Show only colored dot without time.
   */
  compact?: boolean;
}

export function DataFreshnessBadge({
  onClick,
  showLabel = false,
  compact = false,
}: DataFreshnessBadgeProps) {
  const { hasStaleData, hasCriticalIssues, freshnessLabel, loading } =
    useFreshnessStatus();

  if (loading) {
    return <Spinner size="small" accessibilityLabel="Loading data health" />;
  }

  // Determine badge tone based on status
  const getTone = (): 'success' | 'attention' | 'critical' => {
    if (hasCriticalIssues) return 'critical';
    if (hasStaleData) return 'attention';
    return 'success';
  };

  // Get tooltip message
  const getTooltipContent = (): string => {
    if (hasCriticalIssues) return 'Critical data issues detected';
    if (hasStaleData) return `Data freshness: ${freshnessLabel}`;
    return 'All data is fresh';
  };

  // Get badge text
  const getBadgeText = (): string => {
    if (compact) return '';
    if (hasCriticalIssues) return '!';
    if (hasStaleData) return freshnessLabel.replace(' ago', '');
    return 'Fresh';
  };

  const tone = getTone();
  const tooltipContent = getTooltipContent();
  const badgeText = getBadgeText();

  const badgeContent = (
    <InlineStack gap="100" blockAlign="center">
      {showLabel && (
        <Text as="span" variant="bodySm">
          Data
        </Text>
      )}
      {compact ? (
        <Icon
          source={hasCriticalIssues ? AlertCircleIcon : ClockIcon}
          tone={tone === 'attention' ? 'warning' : tone}
        />
      ) : (
        <Badge tone={tone}>{badgeText}</Badge>
      )}
    </InlineStack>
  );

  if (onClick) {
    return (
      <Tooltip content={tooltipContent}>
        <button
          onClick={onClick}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
          }}
          aria-label={tooltipContent}
        >
          {badgeContent}
        </button>
      </Tooltip>
    );
  }

  return <Tooltip content={tooltipContent}>{badgeContent}</Tooltip>;
}

export default DataFreshnessBadge;
