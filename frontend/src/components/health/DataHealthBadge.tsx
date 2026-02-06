/**
 * DataHealthBadge Component
 *
 * Compact badge showing the merchant-facing data health state.
 * Designed for placement near dashboards and in the app header.
 *
 * Visual states:
 * - Green (success): HEALTHY - all features enabled
 * - Yellow (attention): DELAYED - some data updating
 * - Red (critical): UNAVAILABLE - data temporarily unavailable
 *
 * Story 4.3 - Merchant Data Health Trust Layer
 */

import { Badge, Spinner, InlineStack, Text, Tooltip, Icon } from '@shopify/polaris';
import { CheckCircleIcon, ClockIcon, AlertCircleIcon } from '@shopify/polaris-icons';
import type { MerchantHealthState } from '../../utils/data_health_copy';
import {
  getMerchantHealthLabel,
  getMerchantHealthTooltip,
  getMerchantHealthBadgeTone,
} from '../../utils/data_health_copy';

interface DataHealthBadgeProps {
  /** Current merchant health state. Null while loading. */
  healthState: MerchantHealthState | null;
  /** Whether data is currently loading. */
  loading?: boolean;
  /** Optional click handler (e.g., navigate to health details). */
  onClick?: () => void;
  /** Show text label alongside badge. */
  showLabel?: boolean;
  /** Show only colored icon without text. */
  compact?: boolean;
}

export function DataHealthBadge({
  healthState,
  loading = false,
  onClick,
  showLabel = false,
  compact = false,
}: DataHealthBadgeProps) {
  if (loading || healthState === null) {
    return <Spinner size="small" accessibilityLabel="Loading data health" />;
  }

  const tone = getMerchantHealthBadgeTone(healthState);
  const label = getMerchantHealthLabel(healthState);
  const tooltipContent = getMerchantHealthTooltip(healthState);

  const getIcon = () => {
    switch (healthState) {
      case 'healthy':
        return CheckCircleIcon;
      case 'delayed':
        return ClockIcon;
      case 'unavailable':
        return AlertCircleIcon;
    }
  };

  const badgeContent = (
    <InlineStack gap="100" blockAlign="center">
      {showLabel && (
        <Text as="span" variant="bodySm">
          Data
        </Text>
      )}
      {compact ? (
        <Icon
          source={getIcon()}
          tone={tone === 'attention' ? 'warning' : tone}
        />
      ) : (
        <Badge tone={tone}>{label}</Badge>
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

export default DataHealthBadge;
