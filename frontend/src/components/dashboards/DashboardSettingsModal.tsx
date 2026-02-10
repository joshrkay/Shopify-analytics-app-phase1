/**
 * DashboardSettingsModal Component
 *
 * Modal for editing dashboard metadata (name and description).
 * Uses the DashboardBuilderContext for state management and persistence.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  FormLayout,
  TextField,
  BlockStack,
  InlineStack,
  Button,
  Banner,
} from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';

interface DashboardSettingsModalProps {
  open: boolean;
  onClose: () => void;
}

export function DashboardSettingsModal({ open, onClose }: DashboardSettingsModalProps) {
  const { dashboard, updateDashboardMeta, saveDashboard, isSaving } = useDashboardBuilder();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Sync form state when modal opens
  useEffect(() => {
    if (open && dashboard) {
      setName(dashboard.name);
      setDescription(dashboard.description ?? '');
      setError(null);
    }
  }, [open, dashboard]);

  const handleSave = useCallback(async () => {
    const trimmedName = name.trim();

    if (!trimmedName) {
      setError('Dashboard name is required.');
      return;
    }

    setError(null);

    updateDashboardMeta({
      name: trimmedName,
      description: description.trim() || undefined,
    });

    try {
      await saveDashboard();
      onClose();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to save dashboard settings.',
      );
    }
  }, [name, description, updateDashboardMeta, saveDashboard, onClose]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Dashboard settings"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          )}
          <FormLayout>
            <TextField
              label="Dashboard name"
              value={name}
              onChange={setName}
              placeholder="My dashboard"
              autoComplete="off"
              requiredIndicator
            />
            <TextField
              label="Description"
              value={description}
              onChange={setDescription}
              placeholder="Optional description..."
              autoComplete="off"
              multiline={3}
            />
          </FormLayout>
        </BlockStack>
      </Modal.Section>
      <Modal.Section>
        <InlineStack align="end" gap="200">
          <Button onClick={onClose} disabled={isSaving}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleSave}
            loading={isSaving}
            disabled={isSaving}
          >
            Save
          </Button>
        </InlineStack>
      </Modal.Section>
    </Modal>
  );
}
