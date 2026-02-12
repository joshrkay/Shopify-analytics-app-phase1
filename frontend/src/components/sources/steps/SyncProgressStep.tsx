/**
 * Sync Progress Step Component
 *
 * Step 5 of the connection wizard.
 * Shows real-time sync progress with a progress bar and stage indicators.
 * Uses DetailedSyncProgress from the wizard hook for accurate percentages.
 *
 * Phase 3 — Subphase 3.5: Connection Wizard Steps 4-6
 */

import { useState } from 'react';
import { BlockStack, Text, ProgressBar, Spinner, Banner, InlineStack, Button } from '@shopify/polaris';
import type { DataSourceDefinition, DetailedSyncProgress } from '../../../types/sourceConnection';

interface SyncProgressStepProps {
  platform: DataSourceDefinition;
  progress: DetailedSyncProgress | null;
  error: string | null;
  onNavigateDashboard?: () => void;
}

function getSyncStages(progress: DetailedSyncProgress | null) {
  if (!progress) {
    return [
      { label: 'Connecting to source', status: 'pending' as const },
      { label: 'Retrieving account information', status: 'pending' as const },
      { label: 'Fetching data', status: 'pending' as const },
      { label: 'Processing metrics', status: 'pending' as const },
    ];
  }

  const isRunning = progress.status === 'running';
  const isComplete = progress.status === 'completed' || progress.lastSyncStatus === 'succeeded';
  const isFailed = progress.status === 'failed' || progress.lastSyncStatus === 'failed';

  if (isComplete) {
    return [
      { label: 'Connected to source', status: 'completed' as const },
      { label: 'Retrieved account information', status: 'completed' as const },
      { label: 'Fetched data', status: 'completed' as const },
      { label: 'Processed metrics', status: 'completed' as const },
    ];
  }

  if (isFailed) {
    return [
      { label: 'Connected to source', status: 'completed' as const },
      { label: 'Retrieved account information', status: 'completed' as const },
      { label: 'Fetching data', status: 'failed' as const },
      { label: 'Processing metrics', status: 'pending' as const },
    ];
  }

  if (isRunning) {
    return [
      { label: 'Connected to source', status: 'completed' as const },
      { label: 'Retrieved account information', status: 'completed' as const },
      { label: 'Fetching data', status: 'in_progress' as const },
      { label: 'Processing metrics', status: 'pending' as const },
    ];
  }

  return [
    { label: 'Connecting to source', status: 'in_progress' as const },
    { label: 'Retrieving account information', status: 'pending' as const },
    { label: 'Fetching data', status: 'pending' as const },
    { label: 'Processing metrics', status: 'pending' as const },
  ];
}

function getStageIcon(status: 'completed' | 'in_progress' | 'pending' | 'failed') {
  switch (status) {
    case 'completed': return '✓';
    case 'in_progress': return '◎';
    case 'failed': return '✗';
    default: return '○';
  }
}

export function SyncProgressStep({ platform, progress, error, onNavigateDashboard }: SyncProgressStepProps) {
  const [ctaDismissed, setCtaDismissed] = useState(false);
  const stages = getSyncStages(progress);
  const percent = progress?.percentComplete ?? 0;

  return (
    <BlockStack gap="500">
      <BlockStack gap="200" inlineAlign="center">
        <InlineStack align="center" gap="200">
          <Spinner size="small" />
          <Text as="h2" variant="headingLg" alignment="center">
            Syncing your {platform.displayName} data
          </Text>
        </InlineStack>
      </BlockStack>

      <ProgressBar progress={percent} size="small" />

      <BlockStack gap="200">
        {stages.map((stage) => (
          <InlineStack key={stage.label} gap="200" blockAlign="center">
            <Text
              as="span"
              variant="bodyMd"
              tone={stage.status === 'failed' ? 'critical' : stage.status === 'completed' ? 'success' : 'subdued'}
            >
              {getStageIcon(stage.status)}
            </Text>
            <Text
              as="span"
              variant="bodyMd"
              fontWeight={stage.status === 'in_progress' ? 'semibold' : 'regular'}
              tone={stage.status === 'pending' ? 'subdued' : undefined}
            >
              {stage.label}
            </Text>
          </InlineStack>
        ))}
      </BlockStack>

      {error && (
        <Banner tone="critical" title="Sync Error">
          <p>{error}</p>
        </Banner>
      )}

      <Banner tone="info">
        <p>Feel free to explore the app while your data syncs. We'll notify you when it's complete.</p>
      </Banner>

      {!error && !ctaDismissed && onNavigateDashboard && (
        <InlineStack gap="200" align="end">
          <Button onClick={() => setCtaDismissed(true)}>Stay here</Button>
          <Button variant="primary" onClick={onNavigateDashboard}>
            Continue to Dashboard
          </Button>
        </InlineStack>
      )}
    </BlockStack>
  );
}
