/**
 * FeatureGate Component
 *
 * Wraps content that requires a specific feature entitlement.
 * Shows locked state with tooltip when feature is not entitled.
 */

import React, { ReactNode } from 'react';
import {
  Card,
  BlockStack,
  Text,
  Button,
  Tooltip,
  InlineStack,
  Icon,
} from '@shopify/polaris';
import { LockIcon } from '@shopify/polaris-icons';
import type { EntitlementsResponse } from '../services/entitlementsApi';
import { isFeatureEntitled } from '../services/entitlementsApi';

interface FeatureGateProps {
  /**
   * Feature key to check entitlement for.
   */
  feature: string;
  /**
   * Current entitlements from server.
   */
  entitlements: EntitlementsResponse | null;
  /**
   * Children to render when feature is entitled.
   */
  children: ReactNode;
  /**
   * Custom message to show when locked.
   */
  lockedMessage?: string;
  /**
   * Callback when upgrade button is clicked.
   */
  onUpgrade?: () => void;
  /**
   * Whether to show as disabled card or inline.
   */
  variant?: 'card' | 'inline';
}

/**
 * FeatureGate component that locks content based on entitlements.
 */
export function FeatureGate({
  feature,
  entitlements,
  children,
  lockedMessage,
  onUpgrade,
  variant = 'card',
}: FeatureGateProps) {
  const isEntitled = isFeatureEntitled(entitlements, feature);
  const featureEntitlement = entitlements?.features[feature];
  // Default tooltip message per acceptance criteria
  const reason = lockedMessage || featureEntitlement?.reason || 'Upgrade required';

  // If entitled, render children normally
  if (isEntitled) {
    return <>{children}</>;
  }

  // Locked state
  if (variant === 'inline') {
    return (
      <Tooltip content={reason}>
        <div>
          <InlineStack gap="200" align="start">
            <Icon source={LockIcon} tone="subdued" />
            <div style={{ opacity: 0.5, pointerEvents: 'none' }}>
              {children}
            </div>
          </InlineStack>
        </div>
      </Tooltip>
    );
  }

  // Card variant (default)
  return (
    <Card>
      <BlockStack gap="400">
        <InlineStack gap="200" align="start">
          <Icon source={LockIcon} tone="subdued" />
          <BlockStack gap="200">
            <Text as="h3" variant="headingMd">
              Feature Locked
            </Text>
            <Text as="p" tone="subdued">
              {reason}
            </Text>
          </BlockStack>
        </InlineStack>
        {onUpgrade && (
          <Button
            variant="primary"
            onClick={onUpgrade}
          >
            Upgrade Plan
          </Button>
        )}
        {/* Show locked content with reduced opacity */}
        <div style={{ opacity: 0.3, pointerEvents: 'none' }}>
          {children}
        </div>
      </BlockStack>
    </Card>
  );
}

/**
 * Hook to check if a feature is entitled.
 */
export function useFeatureEntitlement(
  feature: string,
  entitlements: EntitlementsResponse | null
): { isEntitled: boolean; reason: string | null } {
  const isEntitled = isFeatureEntitled(entitlements, feature);
  const featureEntitlement = entitlements?.features[feature];
  const reason = featureEntitlement?.reason || null;

  return { isEntitled, reason };
}
