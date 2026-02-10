/**
 * DeleteDashboardModal Component
 *
 * Confirmation modal for permanently deleting a dashboard.
 * Displays the dashboard name and warns that deletion is irreversible.
 * On confirm, calls the delete API and triggers a list refresh.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useCallback } from 'react';
import {
  Modal,
  BlockStack,
  Text,
  Banner,
} from '@shopify/polaris';
import { deleteDashboard } from '../../services/customDashboardsApi';
import type { Dashboard } from '../../types/customDashboards';

interface DeleteDashboardModalProps {
  open: boolean;
  onClose: () => void;
  dashboard: Dashboard | null;
  onSuccess: () => void;
}

export function DeleteDashboardModal({
  open,
  onClose,
  dashboard,
  onSuccess,
}: DeleteDashboardModalProps) {
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClose = useCallback(() => {
    setIsDeleting(false);
    setError(null);
    onClose();
  }, [onClose]);

  const handleDelete = useCallback(async () => {
    if (!dashboard) {
      return;
    }

    setIsDeleting(true);
    setError(null);

    try {
      await deleteDashboard(dashboard.id);
      handleClose();
      onSuccess();
    } catch (err) {
      console.error('Failed to delete dashboard:', err);
      setError('Failed to delete dashboard. Please try again.');
    } finally {
      setIsDeleting(false);
    }
  }, [dashboard, handleClose, onSuccess]);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Delete dashboard"
      primaryAction={{
        content: 'Delete dashboard',
        onAction: handleDelete,
        loading: isDeleting,
        disabled: isDeleting,
        destructive: true,
      }}
      secondaryActions={[
        {
          content: 'Cancel',
          onAction: handleClose,
          disabled: isDeleting,
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

          <Text as="p" variant="bodyMd">
            Are you sure you want to delete{' '}
            <Text as="span" fontWeight="semibold">
              {dashboard?.name ?? 'this dashboard'}
            </Text>
            ?
          </Text>

          <Text as="p" variant="bodyMd" tone="critical">
            This action is permanent and cannot be undone. All reports within
            this dashboard will also be deleted.
          </Text>
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
