/**
 * ShareModal Component
 *
 * Modal for managing dashboard sharing. Features:
 * - List of existing shares with permission editing and revoke controls
 * - Add share form: user ID input, permission selector, optional expiry
 * - Expired shares section with renew/remove actions
 * - Share count limit enforcement
 * - Self-share prevention
 * - Revoke-self-access warning
 *
 * Edge cases handled:
 * - Sharing with yourself: Pre-check blocks API call with warning
 * - Sharing with user outside tenant: API error shown in banner
 * - Revoking your own access: Confirmation dialog with warning
 * - Expired shares: Grayed section with Expired badge, renew/remove
 * - Share count limit: Disabled invite at limit with explanation
 *
 * Phase 4B - Enhanced Sharing UI
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
  Badge,
} from '@shopify/polaris';
import {
  listShares,
  createShare,
  updateShare,
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
  ownerId?: string;
  currentUserId?: string;
  maxShares?: number;
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

export function ShareModal({
  dashboardId,
  open,
  onClose,
  ownerId,
  currentUserId,
  maxShares,
}: ShareModalProps) {
  const [shares, setShares] = useState<DashboardShare[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Add share form state
  const [userId, setUserId] = useState('');
  const [permission, setPermission] = useState<SharePermission>('view');
  const [expiresAt, setExpiresAt] = useState('');
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Revoke state
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [confirmRevokeSelf, setConfirmRevokeSelf] = useState<string | null>(null);

  // Permission editing state
  const [editingShareId, setEditingShareId] = useState<string | null>(null);

  // Renew expiry state
  const [renewingShareId, setRenewingShareId] = useState<string | null>(null);
  const [renewDate, setRenewDate] = useState('');

  // Derived state
  const activeShares = shares.filter((s) => !s.is_expired);
  const expiredShares = shares.filter((s) => s.is_expired);
  const atLimit = maxShares !== undefined && maxShares !== -1 && activeShares.length >= maxShares;

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
      setExpiresAt('');
      setAddError(null);
      setConfirmRevokeSelf(null);
      setRenewingShareId(null);
    }
  }, [open]);

  const handleAddShare = useCallback(async () => {
    const trimmedUserId = userId.trim();
    if (!trimmedUserId) {
      setAddError('User ID is required.');
      return;
    }

    // Edge case: Self-share prevention
    if (ownerId && trimmedUserId === ownerId) {
      setAddError('You already own this dashboard.');
      return;
    }

    // Edge case: Expiry must be in the future
    if (expiresAt) {
      const expiryDate = new Date(expiresAt);
      if (expiryDate <= new Date()) {
        setAddError('Expiry date must be in the future.');
        return;
      }
    }

    setAddLoading(true);
    setAddError(null);

    try {
      const body: CreateShareRequest = {
        shared_with_user_id: trimmedUserId,
        permission,
      };

      if (expiresAt) {
        body.expires_at = new Date(expiresAt).toISOString();
      }

      const newShare = await createShare(dashboardId, body);
      setShares((prev) => [...prev, newShare]);
      setUserId('');
      setPermission('view');
      setExpiresAt('');
    } catch (err) {
      console.error('Failed to create share:', err);
      setAddError(
        err instanceof Error ? err.message : 'Failed to share dashboard.',
      );
    } finally {
      setAddLoading(false);
    }
  }, [dashboardId, userId, permission, expiresAt, ownerId]);

  const handlePermissionChange = useCallback(
    async (shareId: string, newPermission: string) => {
      setEditingShareId(shareId);
      try {
        const updated = await updateShare(dashboardId, shareId, {
          permission: newPermission,
        });
        setShares((prev) =>
          prev.map((s) => (s.id === shareId ? updated : s)),
        );
      } catch (err) {
        console.error('Failed to update share:', err);
        setError(
          err instanceof Error ? err.message : 'Failed to update permission.',
        );
      } finally {
        setEditingShareId(null);
      }
    },
    [dashboardId],
  );

  const handleRevoke = useCallback(
    async (shareId: string) => {
      // Edge case: Revoking own access
      const share = shares.find((s) => s.id === shareId);
      if (
        share &&
        currentUserId &&
        share.shared_with_user_id === currentUserId &&
        confirmRevokeSelf !== shareId
      ) {
        setConfirmRevokeSelf(shareId);
        return;
      }

      setRevokingId(shareId);
      setConfirmRevokeSelf(null);

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
    [dashboardId, shares, currentUserId, confirmRevokeSelf],
  );

  const handleRenew = useCallback(
    async (shareId: string) => {
      if (!renewDate) return;

      const newExpiry = new Date(renewDate);
      if (newExpiry <= new Date()) {
        setError('Renewal date must be in the future.');
        return;
      }

      setEditingShareId(shareId);
      try {
        const updated = await updateShare(dashboardId, shareId, {
          expires_at: newExpiry.toISOString(),
        });
        setShares((prev) =>
          prev.map((s) => (s.id === shareId ? updated : s)),
        );
        setRenewingShareId(null);
        setRenewDate('');
      } catch (err) {
        console.error('Failed to renew share:', err);
        setError(
          err instanceof Error ? err.message : 'Failed to renew share.',
        );
      } finally {
        setEditingShareId(null);
      }
    },
    [dashboardId, renewDate],
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
            <InlineStack align="space-between" blockAlign="center">
              <Text as="h3" variant="headingSm">
                Invite a user
              </Text>
              {maxShares !== undefined && maxShares !== -1 && (
                <Text as="span" variant="bodySm" tone="subdued">
                  Shares: {activeShares.length}/{maxShares}
                </Text>
              )}
            </InlineStack>

            {atLimit && (
              <Banner tone="warning">
                Share limit reached. Upgrade your plan for more shares.
              </Banner>
            )}

            {addError && (
              <Banner tone="critical" onDismiss={() => setAddError(null)}>
                {addError}
              </Banner>
            )}

            <FormLayout>
              <FormLayout.Group>
                <TextField
                  label="User email or ID"
                  value={userId}
                  onChange={setUserId}
                  placeholder="Enter user ID"
                  autoComplete="off"
                  disabled={atLimit}
                />
                <Select
                  label="Permission"
                  options={PERMISSION_OPTIONS}
                  value={permission}
                  onChange={(val) => setPermission(val as SharePermission)}
                  disabled={atLimit}
                />
              </FormLayout.Group>
              <TextField
                label="Expires on (optional)"
                type="date"
                value={expiresAt}
                onChange={setExpiresAt}
                disabled={atLimit}
                autoComplete="off"
              />
            </FormLayout>
            <InlineStack align="end">
              <Button
                variant="primary"
                onClick={handleAddShare}
                loading={addLoading}
                disabled={addLoading || !userId.trim() || atLimit}
              >
                Share
              </Button>
            </InlineStack>
          </BlockStack>

          <Divider />

          {/* Active shares list */}
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

            {!loading && activeShares.length === 0 && expiredShares.length === 0 && (
              <Text as="p" variant="bodySm" tone="subdued">
                This dashboard has not been shared with anyone yet.
              </Text>
            )}

            {!loading &&
              activeShares.map((share) => (
                <Card key={share.id} padding="300">
                  <BlockStack gap="200">
                    <InlineStack align="space-between" blockAlign="center">
                      <BlockStack gap="050">
                        <Text as="p" variant="bodyMd">
                          {share.shared_with_user_id ?? share.shared_with_role ?? 'Unknown'}
                        </Text>
                        {share.expires_at && (
                          <Text as="p" variant="bodySm" tone="subdued">
                            Expires: {new Date(share.expires_at).toLocaleDateString()}
                          </Text>
                        )}
                      </BlockStack>
                      <InlineStack gap="200" blockAlign="center">
                        <Select
                          label=""
                          labelHidden
                          options={PERMISSION_OPTIONS}
                          value={share.permission}
                          onChange={(val) => handlePermissionChange(share.id, val)}
                          disabled={editingShareId === share.id}
                        />
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
                    </InlineStack>

                    {/* Revoke-self confirmation */}
                    {confirmRevokeSelf === share.id && (
                      <Banner tone="warning">
                        <BlockStack gap="200">
                          <Text as="p" variant="bodySm">
                            You will lose access to this dashboard. Continue?
                          </Text>
                          <InlineStack gap="200">
                            <Button
                              variant="primary"
                              tone="critical"
                              size="slim"
                              onClick={() => handleRevoke(share.id)}
                            >
                              Confirm
                            </Button>
                            <Button
                              size="slim"
                              onClick={() => setConfirmRevokeSelf(null)}
                            >
                              Cancel
                            </Button>
                          </InlineStack>
                        </BlockStack>
                      </Banner>
                    )}
                  </BlockStack>
                </Card>
              ))}
          </BlockStack>

          {/* Expired shares section */}
          {!loading && expiredShares.length > 0 && (
            <>
              <Divider />
              <BlockStack gap="300">
                <Text as="h3" variant="headingSm" tone="subdued">
                  Expired shares
                </Text>

                {expiredShares.map((share) => (
                  <Box key={share.id} opacity="60">
                    <Card padding="300">
                      <BlockStack gap="200">
                        <InlineStack align="space-between" blockAlign="center">
                          <BlockStack gap="050">
                            <Text as="p" variant="bodyMd">
                              {share.shared_with_user_id ?? share.shared_with_role ?? 'Unknown'}
                            </Text>
                            <Badge tone="warning">Expired</Badge>
                          </BlockStack>
                          <InlineStack gap="200">
                            <Button
                              variant="plain"
                              size="slim"
                              onClick={() => {
                                setRenewingShareId(share.id);
                                setRenewDate('');
                              }}
                            >
                              Renew
                            </Button>
                            <Button
                              variant="plain"
                              tone="critical"
                              size="slim"
                              onClick={() => handleRevoke(share.id)}
                              loading={revokingId === share.id}
                            >
                              Remove
                            </Button>
                          </InlineStack>
                        </InlineStack>

                        {/* Renew date picker */}
                        {renewingShareId === share.id && (
                          <InlineStack gap="200" blockAlign="end">
                            <Box minWidth="180px">
                              <TextField
                                label="New expiry date"
                                type="date"
                                value={renewDate}
                                onChange={setRenewDate}
                                autoComplete="off"
                              />
                            </Box>
                            <Button
                              variant="primary"
                              size="slim"
                              onClick={() => handleRenew(share.id)}
                              disabled={!renewDate}
                              loading={editingShareId === share.id}
                            >
                              Set
                            </Button>
                            <Button
                              size="slim"
                              onClick={() => setRenewingShareId(null)}
                            >
                              Cancel
                            </Button>
                          </InlineStack>
                        )}
                      </BlockStack>
                    </Card>
                  </Box>
                ))}
              </BlockStack>
            </>
          )}
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
