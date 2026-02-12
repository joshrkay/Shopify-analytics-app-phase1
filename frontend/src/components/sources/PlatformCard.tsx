/**
 * Platform Card Component
 *
 * Displays a data source platform option in the connection wizard.
 * Shows platform logo, name, description, category badge, and auth type.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard UI
 */

import { Card, InlineStack, BlockStack, Text, Badge, Button } from '@shopify/polaris';
import type { DataSourceDefinition } from '../../types/sourceConnection';

interface PlatformCardProps {
  platform: DataSourceDefinition;
  onSelect: (platform: DataSourceDefinition) => void;
  disabled?: boolean;
}

/**
 * Card component for selecting a data source platform.
 *
 * Displays platform info and "Connect" button.
 * Disabled state grays out card and disables button.
 */
export function PlatformCard({ platform, onSelect, disabled = false }: PlatformCardProps) {
  const getCategoryBadge = (category: string) => {
    switch (category) {
      case 'ecommerce':
        return <Badge tone="success">E-commerce</Badge>;
      case 'ads':
        return <Badge tone="info">Advertising</Badge>;
      case 'email':
        return <Badge tone="attention">Email</Badge>;
      case 'sms':
        return <Badge tone="warning">SMS</Badge>;
      default:
        return <Badge>{category}</Badge>;
    }
  };

  const getAuthBadge = (authType: string) => {
    switch (authType) {
      case 'oauth':
        return <Badge>OAuth</Badge>;
      case 'api_key':
        return <Badge>API Key</Badge>;
      default:
        return <Badge>{authType}</Badge>;
    }
  };

  return (
    <Card>
      <BlockStack gap="300">
        <InlineStack align="space-between" blockAlign="start">
          <BlockStack gap="200">
            <Text as="h3" variant="headingMd" fontWeight="semibold">
              {platform.displayName}
            </Text>
            <InlineStack gap="200">
              {getCategoryBadge(platform.category)}
              {getAuthBadge(platform.authType)}
            </InlineStack>
          </BlockStack>
        </InlineStack>

        <Text as="p" variant="bodySm" tone="subdued">
          {platform.description}
        </Text>

        <Button
          onClick={() => onSelect(platform)}
          disabled={disabled || !platform.isEnabled}
          fullWidth
        >
          {platform.isEnabled ? 'Connect' : 'Coming Soon'}
        </Button>

        {!platform.isEnabled && (
          <Text as="p" variant="bodySm" tone="subdued" alignment="center">
            This integration is not yet available
          </Text>
        )}
      </BlockStack>
    </Card>
  );
}
