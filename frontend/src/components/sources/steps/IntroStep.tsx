/**
 * Intro Step Component
 *
 * Step 1 of the connection wizard.
 * Shows source info, features, required permissions, and a security notice.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import { BlockStack, Text, List, Banner, Button, InlineStack, Box } from '@shopify/polaris';
import type { DataSourceDefinition } from '../../../types/sourceConnection';
import type { SourcePlatform } from '../../../types/sources';

interface IntroStepProps {
  platform: DataSourceDefinition;
  onContinue: () => void;
  onCancel: () => void;
}

const PLATFORM_FEATURES: Record<string, string[]> = {
  shopify: [
    'Order and revenue tracking',
    'Product performance analytics',
    'Customer behavior insights',
    'Inventory sync',
  ],
  meta_ads: [
    'Campaign performance metrics',
    'Ad spend tracking and ROAS',
    'Audience insights',
    'Creative performance analysis',
  ],
  google_ads: [
    'Search and display campaign metrics',
    'Keyword performance tracking',
    'Conversion attribution',
    'Budget utilization reports',
  ],
  tiktok_ads: [
    'Video ad performance metrics',
    'Audience engagement analytics',
    'Conversion tracking',
    'Creative performance insights',
  ],
};

const PLATFORM_PERMISSIONS: Record<string, string[]> = {
  shopify: [
    'Read access to orders and products',
    'Read access to customer data',
    'Read access to store analytics',
  ],
  meta_ads: [
    'Read access to ad campaigns',
    'Read access to ad insights and reporting',
    'Read access to ad account settings',
  ],
  google_ads: [
    'Read access to campaigns and ad groups',
    'Read access to performance reports',
    'Read access to conversion data',
  ],
  tiktok_ads: [
    'Read access to ad campaigns',
    'Read access to ad performance data',
    'Read access to audience data',
  ],
};

const DEFAULT_FEATURES = [
  'Data sync and analytics',
  'Performance metrics',
  'Historical data import',
];

const DEFAULT_PERMISSIONS = [
  'Read access to account data',
  'Read access to performance metrics',
];

function getFeatures(platform: SourcePlatform): string[] {
  return PLATFORM_FEATURES[platform] ?? DEFAULT_FEATURES;
}

function getPermissions(platform: SourcePlatform): string[] {
  return PLATFORM_PERMISSIONS[platform] ?? DEFAULT_PERMISSIONS;
}

export function IntroStep({ platform, onContinue, onCancel }: IntroStepProps) {
  const features = getFeatures(platform.platform);
  const permissions = getPermissions(platform.platform);

  return (
    <BlockStack gap="500">
      <BlockStack gap="200" inlineAlign="center">
        <Text as="h2" variant="headingLg" alignment="center">
          {platform.displayName}
        </Text>
        <Text as="p" variant="bodyMd" tone="subdued" alignment="center">
          {platform.description}
        </Text>
      </BlockStack>

      <Box>
        <BlockStack gap="200">
          <Text as="h3" variant="headingSm">
            What you'll get
          </Text>
          <List>
            {features.map((feature) => (
              <List.Item key={feature}>{feature}</List.Item>
            ))}
          </List>
        </BlockStack>
      </Box>

      <Banner tone="warning" title="Required Permissions">
        <List>
          {permissions.map((permission) => (
            <List.Item key={permission}>{permission}</List.Item>
          ))}
        </List>
      </Banner>

      <Banner tone="info">
        <p>Your data is encrypted and secure. We only request read-only access.</p>
      </Banner>

      <InlineStack gap="200" align="end">
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={onContinue}>
          Continue with {platform.displayName}
        </Button>
      </InlineStack>
    </BlockStack>
  );
}
