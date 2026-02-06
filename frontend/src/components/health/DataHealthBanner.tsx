/**
 * DataHealthBanner Component
 *
 * Displays a merchant-visible banner for DELAYED or UNAVAILABLE health states.
 * Returns null when health is HEALTHY (no banner needed).
 *
 * All copy is sourced from data_health_copy.ts for consistency.
 * Tooltips explain impact, never cause.
 * Mobile responsive via Polaris layout primitives.
 *
 * Story 4.3 - Merchant Data Health Trust Layer
 */

import {
  Banner,
  BlockStack,
  Text,
  InlineStack,
  Tooltip,
} from '@shopify/polaris';
import type { MerchantHealthState } from '../../utils/data_health_copy';
import {
  getMerchantHealthBannerTone,
  getMerchantHealthBannerTitle,
  getMerchantHealthBannerMessage,
  getMerchantHealthTooltip,
} from '../../utils/data_health_copy';

interface DataHealthBannerProps {
  /** Current merchant health state. */
  healthState: MerchantHealthState;
  /** Optional dismiss handler. */
  onDismiss?: () => void;
  /** Optional handler to show support CTA (for UNAVAILABLE state). */
  onContactSupport?: () => void;
}

/**
 * DataHealthBanner renders a Polaris Banner for DELAYED or UNAVAILABLE states.
 * Returns null when state is 'healthy'.
 */
export function DataHealthBanner({
  healthState,
  onDismiss,
  onContactSupport,
}: DataHealthBannerProps) {
  if (healthState === 'healthy') {
    return null;
  }

  const tone = getMerchantHealthBannerTone(healthState);
  const title = getMerchantHealthBannerTitle(healthState);
  const message = getMerchantHealthBannerMessage(healthState);
  const tooltipContent = getMerchantHealthTooltip(healthState);

  const action =
    healthState === 'unavailable' && onContactSupport
      ? {
          content: 'Contact Support',
          onAction: onContactSupport,
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

export default DataHealthBanner;
