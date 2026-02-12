/**
 * Sync Configuration Modal
 *
 * Modal for configuring data source sync settings.
 * Allows updating sync frequency and optionally enabled data streams.
 *
 * Reuses patterns from BackfillModal for consistent UX.
 *
 * Phase 3 — Subphase 3.6: Source Management Actions
 */

import { useState, useCallback, useEffect } from 'react';
import { Modal, BlockStack, Select, Banner, Text } from '@shopify/polaris';
import type { Source } from '../../types/sources';
import type { SyncFrequency, UpdateSyncConfigRequest } from '../../types/sourceConnection';

interface SyncConfigModalProps {
  open: boolean;
  source: Source | null;
  configuring: boolean;
  onSave: (sourceId: string, config: UpdateSyncConfigRequest) => Promise<void>;
  onCancel: () => void;
}

const FREQUENCY_OPTIONS = [
  { label: 'Hourly', value: 'hourly' },
  { label: 'Daily', value: 'daily' },
  { label: 'Weekly', value: 'weekly' },
];

/**
 * Modal for configuring sync frequency.
 *
 * Currently supports sync frequency selection.
 * Future: Date range, enabled streams, advanced settings.
 *
 * Usage:
 * ```tsx
 * <SyncConfigModal
 *   open={showConfig}
 *   source={selectedSource}
 *   configuring={configuring}
 *   onSave={async (id, config) => { await updateSyncConfig(id, config); }}
 *   onCancel={() => setShowConfig(false)}
 * />
 * ```
 */
export function SyncConfigModal({
  open,
  source,
  configuring,
  onSave,
  onCancel,
}: SyncConfigModalProps) {
  const [frequency, setFrequency] = useState<SyncFrequency>('daily');
  const [success, setSuccess] = useState(false);

  // Reset state when modal opens
  useEffect(() => {
    if (open) {
      setFrequency('daily'); // Default frequency
      setSuccess(false);
    }
  }, [open]);

  const handleClose = useCallback(() => {
    setFrequency('daily');
    setSuccess(false);
    onCancel();
  }, [onCancel]);

  const handleSave = useCallback(async () => {
    if (!source) return;

    try {
      await onSave(source.id, { sync_frequency: frequency });
      setSuccess(true);
      // Auto-close after success
      setTimeout(() => {
        handleClose();
      }, 1500);
    } catch (err) {
      // Error handled by parent component
      console.error('Failed to update sync config:', err);
    }
  }, [source, frequency, onSave, handleClose]);

  if (!source) return null;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Configure Sync Settings"
      primaryAction={{
        content: 'Save',
        loading: configuring,
        disabled: configuring || success,
        onAction: handleSave,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: handleClose,
        },
      ]}
    >
      <Modal.Section>
        <BlockStack gap="400">
          {success && (
            <Banner tone="success">
              <p>Sync configuration updated successfully!</p>
            </Banner>
          )}

          <Text as="p" tone="subdued">
            Configure how often data should sync from {source.displayName}.
          </Text>

          <Select
            label="Sync Frequency"
            options={FREQUENCY_OPTIONS}
            value={frequency}
            onChange={(value) => setFrequency(value as SyncFrequency)}
            helpText="How frequently should we sync data from this source?"
          />

          <Banner>
            <p>
              <strong>Note:</strong> More frequent syncs may impact API rate limits and costs.
              Daily syncs are recommended for most use cases.
            </p>
          </Banner>
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
