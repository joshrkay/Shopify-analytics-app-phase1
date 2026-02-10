/**
 * VersionPreviewModal Component
 *
 * Modal showing a read-only preview of a historical version's dashboard state.
 * Fetches the version snapshot via the detail endpoint and renders report
 * cards in a static (non-draggable) grid layout.
 *
 * Edge cases handled:
 * - Backend unavailable: Falls back to metadata-only view
 * - Reports referencing deleted datasets: Shows chart type + dataset name as summary
 *
 * Phase 4A - Version History UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Modal,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Spinner,
  Banner,
  Card,
  Box,
  Divider,
} from '@shopify/polaris';
import type { DashboardVersion, DashboardVersionDetail } from '../../types/customDashboards';
import { getVersion } from '../../services/customDashboardsApi';
import { isApiError } from '../../services/apiUtils';
import { formatDate, formatRelativeTime } from '../../utils/dateUtils';
import { getChartTypeLabel } from '../../types/customDashboards';

interface VersionPreviewModalProps {
  dashboardId: string;
  version: DashboardVersion | null;
  onClose: () => void;
  onRestore: (versionNumber: number) => void;
  restoring?: boolean;
}

export function VersionPreviewModal({
  dashboardId,
  version,
  onClose,
  onRestore,
  restoring = false,
}: VersionPreviewModalProps) {
  const [detail, setDetail] = useState<DashboardVersionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch version detail when modal opens
  useEffect(() => {
    if (!version) {
      setDetail(null);
      setError(null);
      return;
    }

    let cancelled = false;

    async function fetchDetail() {
      try {
        setLoading(true);
        setError(null);
        const data = await getVersion(dashboardId, version!.version_number);
        if (!cancelled) {
          setDetail(data);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to fetch version detail:', err);
          const message = isApiError(err)
            ? err.detail || err.message
            : 'Could not load version preview';
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchDetail();

    return () => {
      cancelled = true;
    };
  }, [dashboardId, version]);

  const handleRestore = useCallback(() => {
    if (version) {
      onRestore(version.version_number);
    }
  }, [version, onRestore]);

  if (!version) return null;

  return (
    <Modal
      open={!!version}
      onClose={onClose}
      title={`Version ${version.version_number} Preview`}
      primaryAction={{
        content: 'Restore this version',
        onAction: handleRestore,
        loading: restoring,
        disabled: loading,
        destructive: true,
      }}
      secondaryActions={[
        { content: 'Close', onAction: onClose },
      ]}
      large
    >
      <Modal.Section>
        <BlockStack gap="400">
          {/* Version metadata */}
          <InlineStack gap="300" align="start" blockAlign="center">
            <Badge>v{version.version_number}</Badge>
            <Text as="span" variant="bodySm" tone="subdued">
              {formatRelativeTime(version.created_at, { verbose: true })}
              {' '}({formatDate(version.created_at)})
            </Text>
          </InlineStack>

          <Text as="p" variant="bodyMd">
            {version.change_summary}
          </Text>

          <Text as="p" variant="bodySm" tone="subdued">
            By {version.created_by.substring(0, 8)}...
          </Text>

          <Divider />

          {/* Snapshot content */}
          {loading && (
            <Box paddingBlock="800">
              <InlineStack align="center">
                <Spinner size="large" />
              </InlineStack>
            </Box>
          )}

          {error && (
            <BlockStack gap="300">
              <Banner tone="warning">
                {error}. You can still restore this version.
              </Banner>
              {/* Metadata-only fallback */}
              <Text as="p" variant="bodySm" tone="subdued">
                Full preview is unavailable. Click "Restore this version" to apply
                this snapshot to your dashboard.
              </Text>
            </BlockStack>
          )}

          {detail && !loading && (
            <BlockStack gap="400">
              {/* Dashboard info from snapshot */}
              <BlockStack gap="200">
                <Text as="h3" variant="headingMd">
                  {detail.snapshot_json.dashboard.name}
                </Text>
                {detail.snapshot_json.dashboard.description && (
                  <Text as="p" variant="bodySm" tone="subdued">
                    {detail.snapshot_json.dashboard.description}
                  </Text>
                )}
              </BlockStack>

              {/* Report cards from snapshot */}
              {detail.snapshot_json.reports.length === 0 ? (
                <Text as="p" tone="subdued">No charts in this version.</Text>
              ) : (
                <BlockStack gap="300">
                  <Text as="h3" variant="headingSm">
                    Charts ({detail.snapshot_json.reports.length})
                  </Text>
                  {detail.snapshot_json.reports.map((report, index) => (
                    <Card key={report.id || index}>
                      <BlockStack gap="100">
                        <InlineStack align="space-between" blockAlign="center">
                          <Text as="span" variant="bodyMd" fontWeight="semibold">
                            {report.name}
                          </Text>
                          <Badge>{getChartTypeLabel(report.chart_type)}</Badge>
                        </InlineStack>
                        <Text as="span" variant="bodySm" tone="subdued">
                          Dataset: {report.dataset_name}
                        </Text>
                        {report.description && (
                          <Text as="span" variant="bodySm" tone="subdued">
                            {report.description}
                          </Text>
                        )}
                      </BlockStack>
                    </Card>
                  ))}
                </BlockStack>
              )}
            </BlockStack>
          )}
        </BlockStack>
      </Modal.Section>
    </Modal>
  );
}
