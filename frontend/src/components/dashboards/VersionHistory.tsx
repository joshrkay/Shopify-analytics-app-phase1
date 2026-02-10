/**
 * VersionHistory Component
 *
 * Slide-out panel (Polaris Modal, large) with two tabs:
 *   1. Versions — timeline of version snapshots with preview/restore
 *   2. Activity — audit trail via AuditTimeline
 *
 * Edge cases handled:
 * - Restoring to version with deleted datasets: Post-restore banner warns
 *   user to check for chart warnings
 * - Concurrent edit detection: Compares version total on refetch and
 *   shows "New changes available" banner
 * - Empty state: Shows message when no versions exist
 *
 * Phase 4A - Version History UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  Tabs,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  Spinner,
  Banner,
  Box,
  Divider,
} from '@shopify/polaris';
import type { Dashboard, DashboardVersion } from '../../types/customDashboards';
import { useVersions } from '../../hooks/useVersions';
import { formatRelativeTime, formatDate } from '../../utils/dateUtils';
import { VersionPreviewModal } from './VersionPreviewModal';
import { AuditTimeline } from './AuditTimeline';

// ============================================================================
// Sub-component (co-located per cursor rules §1.4)
// ============================================================================

interface VersionTimelineItemProps {
  version: DashboardVersion;
  isCurrent: boolean;
  isConfirming: boolean;
  restoring: boolean;
  onPreview: (version: DashboardVersion) => void;
  onConfirmRestore: (versionNumber: number) => void;
  onRestore: (versionNumber: number) => void;
  onCancelRestore: () => void;
}

function VersionTimelineItem({
  version,
  isCurrent,
  isConfirming,
  restoring,
  onPreview,
  onConfirmRestore,
  onRestore,
  onCancelRestore,
}: VersionTimelineItemProps) {
  return (
    <Box
      paddingInlineStart="400"
      borderInlineStartWidth="025"
      borderColor={isCurrent ? 'border-success' : 'border'}
    >
      <BlockStack gap="200">
        {/* Header row */}
        <InlineStack gap="200" align="space-between" blockAlign="center">
          <InlineStack gap="200" blockAlign="center">
            <Text as="span" variant="bodyMd" fontWeight="semibold">
              Version {version.version_number}
            </Text>
            {isCurrent && (
              <Badge tone="success">Current</Badge>
            )}
          </InlineStack>
          <Text as="span" variant="bodySm" tone="subdued">
            {formatRelativeTime(version.created_at, { verbose: true })}
          </Text>
        </InlineStack>

        {/* Change summary */}
        <Text as="p" variant="bodySm">
          {version.change_summary}
        </Text>

        {/* Metadata */}
        <Text as="p" variant="bodySm" tone="subdued">
          {formatDate(version.created_at)} by {version.created_by.substring(0, 8)}...
        </Text>

        {/* Restore confirmation inline */}
        {isConfirming && (
          <Banner tone="warning">
            <BlockStack gap="200">
              <Text as="p" variant="bodySm">
                Restore to version {version.version_number}? This will overwrite the current dashboard state.
              </Text>
              <InlineStack gap="200">
                <Button
                  variant="primary"
                  tone="critical"
                  onClick={() => onRestore(version.version_number)}
                  loading={restoring}
                >
                  Restore
                </Button>
                <Button
                  onClick={onCancelRestore}
                  disabled={restoring}
                >
                  Cancel
                </Button>
              </InlineStack>
            </BlockStack>
          </Banner>
        )}

        {/* Action buttons */}
        {!isConfirming && (
          <InlineStack gap="200">
            <Button
              variant="plain"
              size="slim"
              onClick={() => onPreview(version)}
              disabled={restoring}
            >
              Preview
            </Button>
            {!isCurrent && (
              <Button
                variant="plain"
                size="slim"
                onClick={() => onConfirmRestore(version.version_number)}
                disabled={restoring}
              >
                Restore
              </Button>
            )}
          </InlineStack>
        )}

        <Divider />
      </BlockStack>
    </Box>
  );
}

// ============================================================================
// Main component
// ============================================================================

interface VersionHistoryProps {
  dashboardId: string;
  currentVersionNumber: number;
  open: boolean;
  onClose: () => void;
  onRestore: (dashboard: Dashboard) => void;
}

export function VersionHistory({
  dashboardId,
  currentVersionNumber,
  open,
  onClose,
  onRestore,
}: VersionHistoryProps) {
  const [selectedTab, setSelectedTab] = useState(0);
  const [previewVersion, setPreviewVersion] = useState<DashboardVersion | null>(null);
  const [confirmRestore, setConfirmRestore] = useState<number | null>(null);
  const [restoreSuccess, setRestoreSuccess] = useState<number | null>(null);

  const {
    versions,
    total,
    loading,
    loadingMore,
    restoring,
    error,
    staleWarning,
    fetchVersions,
    loadMore,
    restore,
    clearError,
    dismissStaleWarning,
  } = useVersions(dashboardId);

  // Fetch versions when panel opens
  useEffect(() => {
    if (open) {
      fetchVersions();
      setRestoreSuccess(null);
      setConfirmRestore(null);
    }
  }, [open, fetchVersions]);

  const handleRestore = useCallback(async (versionNumber: number) => {
    try {
      const dashboard = await restore(versionNumber);
      setRestoreSuccess(versionNumber);
      setConfirmRestore(null);
      setPreviewVersion(null);
      onRestore(dashboard);
    } catch (err) {
      // useVersions hook sets error state for UI display; log here for debugging
      console.error('Version restore failed:', err);
    }
  }, [restore, onRestore]);

  const handlePreviewRestore = useCallback((versionNumber: number) => {
    setPreviewVersion(null);
    setConfirmRestore(versionNumber);
  }, []);

  const tabs = [
    { id: 'versions', content: 'Versions', panelID: 'versions-panel' },
    { id: 'activity', content: 'Activity', panelID: 'activity-panel' },
  ];

  const hasMore = versions.length < total;

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title="Version History"
        large
      >
        <Modal.Section>
          <Tabs tabs={tabs} selected={selectedTab} onSelect={setSelectedTab}>
            {selectedTab === 0 ? (
              /* Versions Tab */
              <Box paddingBlockStart="400">
                <BlockStack gap="400">
                  {/* Stale warning — concurrent edit detection */}
                  {staleWarning && (
                    <Banner
                      tone="info"
                      onDismiss={dismissStaleWarning}
                      action={{ content: 'Refresh', onAction: fetchVersions }}
                    >
                      New changes have been made to this dashboard. Refresh to see the latest versions.
                    </Banner>
                  )}

                  {/* Restore success banner */}
                  {restoreSuccess !== null && (
                    <Banner tone="success" onDismiss={() => setRestoreSuccess(null)}>
                      Dashboard restored to version {restoreSuccess}. Check individual charts for any warnings.
                    </Banner>
                  )}

                  {/* Error banner */}
                  {error && (
                    <Banner
                      tone="critical"
                      onDismiss={clearError}
                      action={{ content: 'Retry', onAction: fetchVersions }}
                    >
                      {error}
                    </Banner>
                  )}

                  {/* Loading */}
                  {loading && (
                    <Box paddingBlock="800">
                      <InlineStack align="center">
                        <Spinner size="large" />
                      </InlineStack>
                    </Box>
                  )}

                  {/* Empty state */}
                  {!loading && versions.length === 0 && !error && (
                    <Box paddingBlock="400">
                      <Text as="p" tone="subdued" alignment="center">
                        No version history available yet.
                      </Text>
                    </Box>
                  )}

                  {/* Version timeline */}
                  {!loading && versions.map((version) => (
                    <VersionTimelineItem
                      key={version.id}
                      version={version}
                      isCurrent={version.version_number === currentVersionNumber}
                      isConfirming={confirmRestore === version.version_number}
                      restoring={restoring}
                      onPreview={setPreviewVersion}
                      onConfirmRestore={setConfirmRestore}
                      onRestore={handleRestore}
                      onCancelRestore={() => setConfirmRestore(null)}
                    />
                  ))}

                  {/* Load more */}
                  {hasMore && !loading && (
                    <InlineStack align="center">
                      <Button
                        variant="plain"
                        onClick={loadMore}
                        loading={loadingMore}
                      >
                        Load older versions
                      </Button>
                    </InlineStack>
                  )}
                </BlockStack>
              </Box>
            ) : (
              /* Activity Tab */
              <Box paddingBlockStart="400">
                <AuditTimeline dashboardId={dashboardId} />
              </Box>
            )}
          </Tabs>
        </Modal.Section>
      </Modal>

      {/* Version preview modal (nested) */}
      <VersionPreviewModal
        dashboardId={dashboardId}
        version={previewVersion}
        onClose={() => setPreviewVersion(null)}
        onRestore={handlePreviewRestore}
        restoring={restoring}
      />
    </>
  );
}
