/**
 * CreateDashboardModal Component
 *
 * Modal for creating a new custom dashboard.
 * Provides a name field, optional description, and two actions:
 * - Create blank dashboard (calls API, then navigates to editor)
 * - Browse templates (navigates to template gallery)
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useCallback } from 'react';
import {
  Modal,
  TextField,
  BlockStack,
  InlineStack,
  Button,
  Banner,
} from '@shopify/polaris';
import { useNavigate } from 'react-router-dom';
import { createDashboard } from '../../services/customDashboardsApi';
import { getErrorMessage } from '../../services/apiUtils';

interface CreateDashboardModalProps {
  open: boolean;
  onClose: () => void;
  atLimit?: boolean;
  maxCount?: number | null;
  onSuccess?: () => void;
}

export function CreateDashboardModal({
  open,
  onClose,
  atLimit = false,
  maxCount = null,
  onSuccess,
}: CreateDashboardModalProps) {
  const navigate = useNavigate();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [nameError, setNameError] = useState<string | undefined>(undefined);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = useCallback(() => {
    setName('');
    setDescription('');
    setNameError(undefined);
    setIsCreating(false);
    setError(null);
  }, []);

  const handleClose = useCallback(() => {
    resetForm();
    onClose();
  }, [onClose, resetForm]);

  const validateName = useCallback((): boolean => {
    const trimmed = name.trim();
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
  }, [name]);

  const handleCreateBlank = useCallback(async () => {
    if (!validateName()) {
      return;
    }

    setIsCreating(true);
    setError(null);

    try {
      const dashboard = await createDashboard({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      resetForm();
      onClose();
      onSuccess?.();
      navigate(`/dashboards/${dashboard.id}/edit`);
    } catch (err) {
      console.error('Failed to create dashboard:', err);
      setError(getErrorMessage(err, 'Failed to create dashboard. Please try again.'));
    } finally {
      setIsCreating(false);
    }
  }, [name, description, validateName, resetForm, onClose, navigate]);

  const handleBrowseTemplates = useCallback(() => {
    resetForm();
    onClose();
    navigate('/dashboards/templates');
  }, [resetForm, onClose, navigate]);

  const handleNameChange = useCallback((value: string) => {
    setName(value);
    if (nameError) {
      setNameError(undefined);
    }
  }, [nameError]);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Create dashboard"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {atLimit && (
            <Banner tone="warning">
              You&apos;ve reached the maximum of {maxCount} dashboards for your current plan.
              Delete an existing dashboard or upgrade to create more.
            </Banner>
          )}
          {error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          )}

          <TextField
            label="Name"
            value={name}
            onChange={handleNameChange}
            error={nameError}
            placeholder="e.g., Sales Overview"
            autoComplete="off"
            requiredIndicator
            disabled={isCreating}
          />

          <TextField
            label="Description"
            value={description}
            onChange={setDescription}
            placeholder="Optional description for this dashboard"
            autoComplete="off"
            multiline={3}
            disabled={isCreating}
          />

          <InlineStack gap="300" align="end">
            <Button
              onClick={handleBrowseTemplates}
              disabled={isCreating}
            >
              Browse templates
            </Button>
            <Button
              variant="primary"
              onClick={handleCreateBlank}
              loading={isCreating}
              disabled={isCreating || atLimit}
            >
              Create blank dashboard
            </Button>
          </InlineStack>
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
