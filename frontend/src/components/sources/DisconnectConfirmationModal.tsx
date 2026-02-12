/**
 * Disconnect Confirmation Modal
 *
 * Confirmation dialog for disconnecting a data source.
 * Requires typing the source name to confirm the destructive action.
 *
 * Phase 3 — Subphase 3.6: Source Management Actions
 */

import { useState, useCallback } from 'react';
import { Modal, BlockStack, Text, TextField, Banner } from '@shopify/polaris';
import type { Source } from '../../types/sources';

interface DisconnectConfirmationModalProps {
  open: boolean;
  source: Source | null;
  disconnecting: boolean;
  onConfirm: (sourceId: string) => Promise<void>;
  onCancel: () => void;
}

/**
 * Modal for confirming source disconnection.
 *
 * Requires user to type the source name to prevent accidental deletion.
 * Warns about data sync停止 and credential removal.
 *
 * Usage:
 * ```tsx
 * <DisconnectConfirmationModal
 *   open={showDisconnect}
 *   source={selectedSource}
 *   disconnecting={disconnecting}
 *   onConfirm={async (id) => { await disconnect(id); }}
 *   onCancel={() => setShowDisconnect(false)}
 * />
 * ```
 */
export function DisconnectConfirmationModal({
  open,
  source,
  disconnecting,
  onConfirm,
  onCancel,
}: DisconnectConfirmationModalProps) {
  const [confirmationText, setConfirmationText] = useState('');

  const handleClose = useCallback(() => {
    setConfirmationText('');
    onCancel();
  }, [onCancel]);

  const handleConfirm = useCallback(async () => {
    if (!source) return;
    try {
      await onConfirm(source.id);
      setConfirmationText('');
    } catch (err) {
      // Error handled by parent component
      console.error('Disconnect failed:', err);
    }
  }, [source, onConfirm]);

  const isConfirmed = source ? confirmationText === source.displayName : false;

  if (!source) return null;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Disconnect Data Source"
      primaryAction={{
        content: 'Disconnect',
        destructive: true,
        disabled: !isConfirmed,
        loading: disconnecting,
        onAction: handleConfirm,
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
          <Banner tone="warning">
            <p>
              <strong>Warning:</strong> This action cannot be undone.
            </p>
          </Banner>

          <Text as="p">
            Disconnecting <strong>{source.displayName}</strong> will:
          </Text>

          <ul>
            <li>Stop all data syncing from this source</li>
            <li>Remove stored credentials</li>
            <li>
              Historical data will remain available in dashboards, but no new data will be synced
            </li>
          </ul>

          <Text as="p">
            To confirm, type <strong>{source.displayName}</strong> below:
          </Text>

          <TextField
            label="Source name"
            value={confirmationText}
            onChange={setConfirmationText}
            autoComplete="off"
            placeholder={source.displayName}
          />
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
