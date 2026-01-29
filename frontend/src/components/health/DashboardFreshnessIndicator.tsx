/**
 * DashboardFreshnessIndicator Component
 *
 * Shows data freshness summary within dashboard context.
 * More detailed than header badge.
 *
 * Variants:
 * - compact: Inline text with icon
 * - detailed: Shows stale count
 *
 * Story 9.5 - Freshness visible where analytics appear
 */

import { InlineStack, Text, Icon, Badge } from '@shopify/polaris';
import { ClockIcon, CheckCircleIcon, AlertCircleIcon } from '@shopify/polaris-icons';
import { useFreshnessStatus } from '../../contexts/DataHealthContext';

interface DashboardFreshnessIndicatorProps {
  /**
   * Display variant.
   * - compact: Just icon + text
   * - detailed: Icon + text + stale count badge
   */
  variant?: 'compact' | 'detailed';
}

export function DashboardFreshnessIndicator({
  variant = 'compact',
}: DashboardFreshnessIndicatorProps) {
  const { status, hasStaleData, hasCriticalIssues, freshnessLabel, loading } =
    useFreshnessStatus();

  if (loading) {
    return (
      <InlineStack gap="100" blockAlign="center">
        <Icon source={ClockIcon} tone="subdued" />
        <Text as="span" tone="subdued" variant="bodySm">
          Checking data freshness...
        </Text>
      </InlineStack>
    );
  }

  // Determine icon and color
  const getIcon = () => {
    if (hasCriticalIssues) return AlertCircleIcon;
    if (hasStaleData) return ClockIcon;
    return CheckCircleIcon;
  };

  const getTone = (): 'success' | 'caution' | 'critical' => {
    if (hasCriticalIssues) return 'critical';
    if (hasStaleData) return 'caution';
    return 'success';
  };

  const getText = (): string => {
    if (hasCriticalIssues) return 'Data issues detected';
    if (hasStaleData) return `Last sync: ${freshnessLabel}`;
    return 'All data fresh';
  };

  const IconComponent = getIcon();
  const tone = getTone();
  const text = getText();

  if (variant === 'compact') {
    return (
      <InlineStack gap="100" blockAlign="center">
        <Icon source={IconComponent} tone={tone} />
        <Text as="span" tone={tone === 'success' ? 'success' : 'subdued'} variant="bodySm">
          {text}
        </Text>
      </InlineStack>
    );
  }

  // Detailed variant
  return (
    <InlineStack gap="200" blockAlign="center">
      <Icon source={IconComponent} tone={tone} />
      <Text as="span" tone={tone === 'success' ? 'success' : 'subdued'} variant="bodySm">
        {text}
      </Text>
      {hasStaleData && status === 'degraded' && (
        <Badge tone="attention">Some data delayed</Badge>
      )}
      {hasCriticalIssues && (
        <Badge tone="critical">Action required</Badge>
      )}
    </InlineStack>
  );
}

export default DashboardFreshnessIndicator;
