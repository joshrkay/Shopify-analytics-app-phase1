/**
 * Success Step Component
 *
 * Step 6 of the connection wizard.
 * Shows success confirmation and next steps.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import { BlockStack, Text, Banner, Button, InlineStack, List } from '@shopify/polaris';
import type { DataSourceDefinition } from '../../../types/sourceConnection';

interface SuccessStepProps {
  platform: DataSourceDefinition;
  onConnectAnother?: () => void;
  onViewDashboard: () => void;
}

export function SuccessStep({ platform, onConnectAnother, onViewDashboard }: SuccessStepProps) {
  return (
    <BlockStack gap="500">
      <Banner tone="success" title="Successfully Connected!">
        <p>
          {platform.displayName} is now connected and your data is syncing.
        </p>
      </Banner>

      <BlockStack gap="300">
        <Text as="h3" variant="headingSm">
          What's next?
        </Text>
        <List>
          <List.Item>View your dashboard to see incoming data</List.Item>
          <List.Item>Connect another data source for richer insights</List.Item>
          <List.Item>Configure sync settings in the Data Sources page</List.Item>
          <List.Item>Set up alerts for data quality issues</List.Item>
        </List>
      </BlockStack>

      <InlineStack gap="200" align="end">
        {onConnectAnother && (
          <Button onClick={onConnectAnother}>Connect Another Source</Button>
        )}
        <Button variant="primary" onClick={onViewDashboard}>
          Go to Dashboard
        </Button>
      </InlineStack>
    </BlockStack>
  );
}
