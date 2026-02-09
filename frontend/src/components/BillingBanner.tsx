/**
 * BillingBanner Component
 *
 * Displays banners for different billing states:
 * - past_due: Payment issue warning
 * - grace_period: Countdown banner with days remaining
 * - expired: Paywall redirect
 */

import {
  Banner,
  Text,
  BlockStack,
} from '@shopify/polaris';
import type { EntitlementsResponse } from '../services/entitlementsApi';
import { getBillingState } from '../services/entitlementsApi';

interface BillingBannerProps {
  /**
   * Current entitlements from server.
   */
  entitlements: EntitlementsResponse | null;
  /**
   * Callback when upgrade button is clicked.
   */
  onUpgrade?: () => void;
  /**
   * Callback when payment update button is clicked.
   */
  onUpdatePayment?: () => void;
}

/**
 * BillingBanner component that shows appropriate banner based on billing state.
 */
export function BillingBanner({
  entitlements,
  onUpgrade,
  onUpdatePayment,
}: BillingBannerProps) {
  const billingState = getBillingState(entitlements);

  // No banner for active or none states
  if (billingState === 'active' || billingState === 'none') {
    return null;
  }

  // Past due - payment issue
  if (billingState === 'past_due') {
    return (
      <Banner
        title="Payment Issue"
        tone="critical"
        action={
          onUpdatePayment
            ? {
                content: 'Update Payment Method',
                onAction: onUpdatePayment,
              }
            : undefined
        }
      >
        <BlockStack gap="200">
          <Text as="p">
            Your payment method failed. Please update your payment information to continue using premium features.
          </Text>
        </BlockStack>
      </Banner>
    );
  }

  // Grace period - countdown (format: "2 days left" per acceptance criteria)
  if (billingState === 'grace_period') {
    const daysRemaining = entitlements?.grace_period_days_remaining ?? 0;
    const daysText = daysRemaining === 1 ? 'day' : 'days';

    return (
      <Banner
        title={`${daysRemaining} ${daysText} left`}
        tone="warning"
        action={
          onUpdatePayment
            ? {
                content: 'Update Payment',
                onAction: onUpdatePayment,
              }
            : undefined
        }
      >
        <BlockStack gap="200">
          <Text as="p">
            Your payment method failed, but you still have access for {daysRemaining} more {daysText}.
            Please update your payment information to avoid service interruption.
          </Text>
        </BlockStack>
      </Banner>
    );
  }

  // Expired - redirect to paywall handled by parent
  if (billingState === 'expired') {
    return (
      <Banner
        title="Subscription Expired"
        tone="critical"
        action={
          onUpgrade
            ? {
                content: 'Upgrade Now',
                onAction: onUpgrade,
              }
            : undefined
        }
      >
        <BlockStack gap="200">
          <Text as="p">
            Your subscription has expired. Please upgrade to continue using premium features.
          </Text>
        </BlockStack>
      </Banner>
    );
  }

  // Canceled - similar to expired
  if (billingState === 'canceled') {
    return (
      <Banner
        title="Subscription Canceled"
        tone="warning"
        action={
          onUpgrade
            ? {
                content: 'Reactivate',
                onAction: onUpgrade,
              }
            : undefined
        }
      >
        <BlockStack gap="200">
          <Text as="p">
            Your subscription has been canceled. Upgrade to reactivate premium features.
          </Text>
        </BlockStack>
      </Banner>
    );
  }

  return null;
}
