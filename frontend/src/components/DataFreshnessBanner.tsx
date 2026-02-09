/**
 * DataFreshnessBanner Component
 *
 * Displays a merchant-visible banner communicating data freshness status.
 * Only renders for STALE or UNAVAILABLE states; returns null when data is fresh.
 * All copy is sourced from freshness_copy.ts to keep text centralized.
 */

import {
  Banner,
  BlockStack,
  Text,
  InlineStack,
  Tooltip,
} from '@shopify/polaris';
import type { DataFreshnessState } from '../utils/freshness_copy';
import {
  getFreshnessBannerTone,
  getFreshnessBannerTitle,
  getFreshnessBannerMessage,
  getFreshnessTooltip,
} from '../utils/freshness_copy';

interface DataFreshnessBannerProps {
  /** Current data freshness state. */
  state: DataFreshnessState;
  /** Optional backend reason code that refines the banner message. */
  reason?: string;
  /** Optional list of friendly source names affected (e.g. ["Shopify Orders", "Facebook Ads"]). */
  affectedSources?: string[];
  /** Optional dismiss handler passed to Banner's onDismiss. */
  onDismiss?: () => void;
  /** Optional retry handler; renders a "Retry" action button for unavailable state. */
  onRetry?: () => void;
}

/**
 * DataFreshnessBanner renders a Polaris Banner for stale or unavailable data states.
 * Returns null when state is 'fresh' since no banner is needed.
 */
export function DataFreshnessBanner({
  state,
  reason,
  affectedSources,
  onDismiss,
  onRetry,
}: DataFreshnessBannerProps) {
  // No banner for fresh state
  if (state === 'fresh') {
    return null;
  }

  const tone = getFreshnessBannerTone(state);
  const title = getFreshnessBannerTitle(state);
  const message = getFreshnessBannerMessage(state, reason);
  const tooltipContent = getFreshnessTooltip(state, reason);

  // Show retry action only for unavailable state when handler is provided
  const action =
    state === 'unavailable' && onRetry
      ? {
          content: 'Retry',
          onAction: onRetry,
        }
      : undefined;

  return (
    <Banner
      title={title}
      tone={tone}
      action={action}
      onDismiss={onDismiss}
    >
      <BlockStack gap="200">
        <Text as="p">{message}</Text>
        {affectedSources && affectedSources.length > 0 && (
          <Text as="p">
            <Text as="span" fontWeight="semibold">
              Affected:
            </Text>{' '}
            {affectedSources.join(', ')}
          </Text>
        )}
        <InlineStack>
          <Tooltip content={tooltipContent}>
            <Text as="span" tone="subdued">
              Why am I seeing this?
            </Text>
          </Tooltip>
        </InlineStack>
      </BlockStack>
    </Banner>
  );
}
