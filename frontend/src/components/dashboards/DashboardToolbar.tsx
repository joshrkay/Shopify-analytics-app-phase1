/**
 * DashboardToolbar Component
 *
 * Horizontal toolbar displayed above the dashboard grid.
 * Provides:
 * - "Add Report" button to open the report configurator
 * - Dashboard status badge (draft/published/archived)
 * - Save indicator showing dirty/saving/saved state
 * - Manual save button
 *
 * Phase 3 - Dashboard Builder UI
 */

import {
  InlineStack,
  Button,
  Badge,
  Text,
  Spinner,
  Box,
} from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';
import type { DashboardStatus } from '../../types/customDashboards';

function getStatusBadge(status: DashboardStatus) {
  switch (status) {
    case 'draft':
      return <Badge tone="info">Draft</Badge>;
    case 'published':
      return <Badge tone="success">Published</Badge>;
    case 'archived':
      return <Badge>Archived</Badge>;
    default:
      return <Badge>{status}</Badge>;
  }
}

export function DashboardToolbar() {
  const {
    dashboard,
    isDirty,
    isSaving,
    openReportConfig,
    saveDashboard,
  } = useDashboardBuilder();

  if (!dashboard) return null;

  const canEdit = ['owner', 'admin', 'edit'].includes(dashboard.access_level);

  return (
    <Box paddingBlockEnd="400">
      <InlineStack align="space-between" blockAlign="center" gap="300">
        <InlineStack gap="300" blockAlign="center">
          {canEdit && (
            <Button
              variant="primary"
              onClick={() => openReportConfig(null)}
            >
              Add report
            </Button>
          )}
          {getStatusBadge(dashboard.status)}
        </InlineStack>

        <InlineStack gap="300" blockAlign="center">
          {isSaving && (
            <InlineStack gap="200" blockAlign="center">
              <Spinner size="small" />
              <Text as="span" variant="bodySm" tone="subdued">
                Saving...
              </Text>
            </InlineStack>
          )}
          {!isSaving && isDirty && (
            <Text as="span" variant="bodySm" tone="caution">
              Unsaved changes
            </Text>
          )}
          {!isSaving && !isDirty && (
            <Text as="span" variant="bodySm" tone="subdued">
              All changes saved
            </Text>
          )}
          {canEdit && (
            <Button
              onClick={() => saveDashboard()}
              disabled={!isDirty || isSaving}
              loading={isSaving}
            >
              Save
            </Button>
          )}
        </InlineStack>
      </InlineStack>
    </Box>
  );
}
