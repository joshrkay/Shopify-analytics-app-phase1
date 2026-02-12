/**
 * Sync Config Step Component
 *
 * Step 4 of the connection wizard.
 * Configures historical data range, sync frequency, and metrics.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import { BlockStack, Text, Select, Banner, Button, InlineStack } from '@shopify/polaris';
import type { DataSourceDefinition, WizardSyncConfig } from '../../../types/sourceConnection';

interface SyncConfigStepProps {
  platform: DataSourceDefinition;
  syncConfig: WizardSyncConfig;
  onUpdateConfig: (config: Partial<WizardSyncConfig>) => void;
  onConfirm: () => void;
  onBack: () => void;
  loading: boolean;
}

const RANGE_OPTIONS = [
  { label: 'Last 30 days', value: '30d' },
  { label: 'Last 90 days (Recommended)', value: '90d' },
  { label: 'Last 365 days', value: '365d' },
  { label: 'All time', value: 'all' },
];

const FREQUENCY_OPTIONS = [
  { label: 'Every 1 hour (Recommended)', value: 'hourly' },
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
];

export function SyncConfigStep({
  platform,
  syncConfig,
  onUpdateConfig,
  onConfirm,
  onBack,
  loading,
}: SyncConfigStepProps) {
  return (
    <BlockStack gap="500">
      <BlockStack gap="200">
        <Text as="h2" variant="headingLg">
          Configure Sync
        </Text>
        <Text as="p" variant="bodyMd" tone="subdued">
          Choose how much data to import and how often to sync from {platform.displayName}.
        </Text>
      </BlockStack>

      <Select
        label="Historical Data Range"
        options={RANGE_OPTIONS}
        value={syncConfig.historicalRange}
        onChange={(value) =>
          onUpdateConfig({ historicalRange: value as WizardSyncConfig['historicalRange'] })
        }
        helpText="How far back should we import your historical data?"
      />

      <Select
        label="Sync Frequency"
        options={FREQUENCY_OPTIONS}
        value={syncConfig.frequency}
        onChange={(value) =>
          onUpdateConfig({ frequency: value as WizardSyncConfig['frequency'] })
        }
        helpText="How often should we sync new data?"
      />

      <Banner>
        <p>
          <strong>Note:</strong> More frequent syncs may impact API rate limits and costs.
          Initial sync will take approximately 5-10 minutes depending on your data volume.
        </p>
      </Banner>

      <InlineStack gap="200" align="end">
        <Button onClick={onBack}>Back</Button>
        <Button variant="primary" onClick={onConfirm} loading={loading}>
          Start Sync →
        </Button>
      </InlineStack>
    </BlockStack>
  );
}
