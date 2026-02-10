/**
 * DuplicateDashboardModal Component
 *
 * Modal for duplicating an existing dashboard under a new name.
 * Pre-fills the name field with "Copy of {originalName}".
 * On confirm, calls the duplicate API and triggers a list refresh.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  TextField,
  BlockStack,
  Banner,
} from '@shopify/polaris';
import { duplicateDashboard } from '../../services/customDashboardsApi';
import type { Dashboard } from '../../types/customDashboards';

interface DuplicateDashboardModalProps {
  open: boolean;
  onClose: () => void;
  dashboard: Dashboard | null;
  onSuccess: () => void;
}

export function DuplicateDashboardModal({
  open,
  onClose,
  dashboard,
  onSuccess,
}: DuplicateDashboardModalProps) {
  const [newName, setNewName] = useState('');
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [isDuplicating, setIsDuplicating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-fill name when dashboard changes or modal opens
  useEffect(() => {
    if (dashboard && open) {
      setNewName(`Copy of ${dashboard.name}`);
      setNameError(undefined);
      setError(null);
    }
  }, [dashboard, open]);

  const handleClose = useCallback(() => {
    setNewName('');
    setNameError(undefined);
    setIsDuplicating(false);
    setError(null);
    onClose();
  }, [onClose]);

  const validateName = useCallback((): boolean => {
    const trimmed = newName.trim();
    if (!trimmed) {
      setNameError('Dashboard name is required');
      return false;
    }
    if (trimmed.length > 255) {
      setNameError('Dashboard name must be 255 characters or fewer');
      return false;
    }
    setNameError(undefined);
    return true;
  }, [newName]);

  const handleDuplicate = useCallback(async () => {
    if (!dashboard) {
      return;
    }

    if (!validateName()) {
      return;
    }

    setIsDuplicating(true);
    setError(null);

    try {
      await duplicateDashboard(dashboard.id, newName.trim());
      handleClose();
      onSuccess();
    } catch (err) {
      console.error('Failed to duplicate dashboard:', err);
      setError('Failed to duplicate dashboard. Please try again.');
    } finally {
      setIsDuplicating(false);
    }
  }, [dashboard, newName, validateName, handleClose, onSuccess]);

  const handleNameChange = useCallback((value: string) => {
    setNewName(value);
    if (nameError) {
      setNameError(undefined);
    }
  }, [nameError]);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Duplicate dashboard"
      primaryAction={{
        content: 'Duplicate',
        onAction: handleDuplicate,
        loading: isDuplicating,
        disabled: isDuplicating,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: handleClose,
          disabled: isDuplicating,
        },
      ]}
    >
      <Modal.Section>
        <BlockStack gap="400">
          {error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          )}

          <TextField
            label="New dashboard name"
            value={newName}
            onChange={handleNameChange}
            error={nameError}
            autoComplete="off"
            requiredIndicator
            disabled={isDuplicating}
          />
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
