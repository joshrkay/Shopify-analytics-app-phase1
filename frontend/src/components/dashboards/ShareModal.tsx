/**
 * ShareModal Component
 *
 * Modal for managing dashboard sharing. Features:
 * - List of existing shares with permission and revoke controls
 * - Add share form: user ID input, permission selector, share button
 * - Loading and error states
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  FormLayout,
  TextField,
  Select,
  BlockStack,
  InlineStack,
  Button,
  Banner,
  Text,
  Spinner,
  Divider,
  Box,
  Card,
} from '@shopify/polaris';
import {
  listShares,
  createShare,
  revokeShare,
} from '../../services/dashboardSharesApi';
import type {
  DashboardShare,
  SharePermission,
  CreateShareRequest,
} from '../../types/customDashboards';

interface ShareModalProps {
  dashboardId: string;
  open: boolean;
  onClose: () => void;
}

const PERMISSION_OPTIONS: { label: string; value: SharePermission }[] = [
  { label: 'View', value: 'view' },
  { label: 'Edit', value: 'edit' },
  { label: 'Admin', value: 'admin' },
];

function getPermissionLabel(permission: SharePermission): string {
  const found = PERMISSION_OPTIONS.find((o) => o.value === permission);
  return found ? found.label : permission;
}

export function ShareModal({ dashboardId, open, onClose }: ShareModalProps) {
  const [shares, setShares] = useState<DashboardShare[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add share form state
  const [userId, setUserId] = useState('');
  const [permission, setPermission] = useState<SharePermission>('view');
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Revoke state
  const [revokingId, setRevokingId] = useState<string | null>(null);

  // Fetch shares on modal open
  useEffect(() => {
    if (!open) return;

    let cancelled = false;

    async function fetchShares() {
      setLoading(true);
      setError(null);

      try {
        const response = await listShares(dashboardId);
        if (!cancelled) {
          setShares(response.shares);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to fetch shares:', err);
          setError(
            err instanceof Error ? err.message : 'Failed to load shares',
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchShares();

    return () => {
      cancelled = true;
    };
  }, [open, dashboardId]);

  // Reset add form when modal opens
  useEffect(() => {
    if (open) {
      setUserId('');
      setPermission('view');
      setAddError(null);
    }
  }, [open]);

  const handleAddShare = useCallback(async () => {
    const trimmedUserId = userId.trim();
    if (!trimmedUserId) {
      setAddError('User ID is required.');
      return;
    }

    setAddLoading(true);
    setAddError(null);

    try {
      const body: CreateShareRequest = {
        shared_with_user_id: trimmedUserId,
        permission,
      };

      const newShare = await createShare(dashboardId, body);
      setShares((prev) => [...prev, newShare]);
      setUserId('');
      setPermission('view');
    } catch (err) {
      console.error('Failed to create share:', err);
      setAddError(
        err instanceof Error ? err.message : 'Failed to share dashboard.',
      );
    } finally {
      setAddLoading(false);
    }
  }, [dashboardId, userId, permission]);

  const handleRevoke = useCallback(
    async (shareId: string) => {
      setRevokingId(shareId);

      try {
        await revokeShare(dashboardId, shareId);
        setShares((prev) => prev.filter((s) => s.id !== shareId));
      } catch (err) {
        console.error('Failed to revoke share:', err);
        setError(
          err instanceof Error ? err.message : 'Failed to revoke share.',
        );
      } finally {
        setRevokingId(null);
      }
    },
    [dashboardId],
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Share dashboard"
    >
      <Modal.Section>
        <BlockStack gap="400">
          {error && (
            <Banner tone="critical" onDismiss={() => setError(null)}>
              {error}
            </Banner>
          )}

          {/* Add share form */}
          <BlockStack gap="300">
            <Text as="h3" variant="headingSm">
              Invite a user
            </Text>
            {addError && (
              <Banner tone="critical" onDismiss={() => setAddError(null)}>
                {addError}
              </Banner>
            )}
            <FormLayout>
              <FormLayout.Group>
                <TextField
                  label="User ID"
                  value={userId}
                  onChange={setUserId}
                  placeholder="Enter user ID"
                  autoComplete="off"
                />
                <Select
                  label="Permission"
                  options={PERMISSION_OPTIONS}
                  value={permission}
                  onChange={(val) => setPermission(val as SharePermission)}
                />
              </FormLayout.Group>
            </FormLayout>
            <InlineStack align="end">
              <Button
                variant="primary"
                onClick={handleAddShare}
                loading={addLoading}
                disabled={addLoading || !userId.trim()}
              >
                Share
              </Button>
            </InlineStack>
          </BlockStack>

          <Divider />

          {/* Existing shares list */}
          <BlockStack gap="300">
            <Text as="h3" variant="headingSm">
              Current shares
            </Text>

            {loading && (
              <InlineStack gap="200" blockAlign="center">
                <Spinner size="small" />
                <Text as="p" variant="bodySm" tone="subdued">
                  Loading shares...
                </Text>
              </InlineStack>
            )}

            {!loading && shares.length === 0 && (
              <Text as="p" variant="bodySm" tone="subdued">
                This dashboard has not been shared with anyone yet.
              </Text>
            )}

            {!loading &&
              shares.map((share) => (
                <Card key={share.id} padding="300">
                  <InlineStack align="space-between" blockAlign="center">
                    <BlockStack gap="050">
                      <Text as="p" variant="bodyMd">
                        {share.shared_with_user_id ?? share.shared_with_role ?? 'Unknown'}
                      </Text>
                      <Text as="p" variant="bodySm" tone="subdued">
                        {getPermissionLabel(share.permission)}
                        {share.is_expired ? ' (expired)' : ''}
                      </Text>
                    </BlockStack>
                    <Button
                      variant="plain"
                      tone="critical"
                      onClick={() => handleRevoke(share.id)}
                      loading={revokingId === share.id}
                      disabled={revokingId === share.id}
                    >
                      Revoke
                    </Button>
                  </InlineStack>
                </Card>
              ))}
          </BlockStack>
        </BlockStack>
      </Modal.Section>

      <Modal.Section>
        <InlineStack align="end">
          <Button onClick={onClose}>Done</Button>
        </InlineStack>
      </Modal.Section>
    </Modal>
  );
}
