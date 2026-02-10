/**
 * AuditTimeline Component
 *
 * Timeline view of dashboard audit trail events. Displayed as a tab
 * inside the VersionHistory panel.
 *
 * Edge cases handled:
 * - High-frequency events: collapseEntries() merges same-actor/same-action
 *   events within 30 seconds into a single entry
 * - Deleted users: Shows truncated actor_id with tooltip fallback
 *
 * Phase 4C - Audit Trail UI
 */

import { useEffect } from 'react';
import {
  BlockStack,
  InlineStack,
  Text,
  Icon,
  Spinner,
  Banner,
  Button,
  Tooltip,
  Box,
} from '@shopify/polaris';
import {
  PlusCircleIcon,
  EditIcon,
  CheckCircleIcon,
  ArchiveIcon,
  RefreshIcon,
  DuplicateIcon,
  ShareIcon,
  DeleteIcon,
  DragHandleIcon,
} from '@shopify/polaris-icons';
import type { AuditEntry } from '../../types/customDashboards';
import { useAuditEntries } from '../../hooks/useAuditEntries';
import { formatRelativeTime } from '../../utils/dateUtils';
import type { IconSource } from '@shopify/polaris-icons';

interface AuditTimelineProps {
  dashboardId: string;
}

// ============================================================================
// Collapsed entry type
// ============================================================================

interface CollapsedAuditEntry extends AuditEntry {
  count: number;
  collapsed_ids: string[];
}

// ============================================================================
// Action configuration
// ============================================================================

interface ActionConfig {
  icon: IconSource;
  label: string;
  tone?: 'success' | 'warning' | 'critical';
}

const ACTION_CONFIG: Record<string, ActionConfig> = {
  created:           { icon: PlusCircleIcon,   label: 'Created dashboard' },
  updated:           { icon: EditIcon,          label: 'Updated dashboard' },
  published:         { icon: CheckCircleIcon,   label: 'Published dashboard', tone: 'success' },
  archived:          { icon: ArchiveIcon,       label: 'Archived dashboard',  tone: 'warning' },
  restored:          { icon: RefreshIcon,       label: 'Restored version' },
  duplicated:        { icon: DuplicateIcon,     label: 'Duplicated dashboard' },
  shared:            { icon: ShareIcon,         label: 'Shared with user' },
  unshared:          { icon: DeleteIcon,        label: 'Revoked share',       tone: 'critical' },
  share_updated:     { icon: EditIcon,          label: 'Updated share' },
  report_added:      { icon: PlusCircleIcon,    label: 'Added chart' },
  report_updated:    { icon: EditIcon,          label: 'Updated chart' },
  report_removed:    { icon: DeleteIcon,        label: 'Removed chart',       tone: 'critical' },
  reports_reordered: { icon: DragHandleIcon,    label: 'Reordered charts' },
};

const DEFAULT_CONFIG: ActionConfig = { icon: EditIcon, label: 'Unknown action' };

// ============================================================================
// Collapse consecutive same-actor/same-action events within 30 seconds
// ============================================================================

function collapseEntries(entries: AuditEntry[]): CollapsedAuditEntry[] {
  const result: CollapsedAuditEntry[] = [];

  for (const entry of entries) {
    const prev = result[result.length - 1];
    if (
      prev &&
      prev.action === entry.action &&
      prev.actor_id === entry.actor_id &&
      Math.abs(
        new Date(prev.created_at).getTime() - new Date(entry.created_at).getTime()
      ) < 30_000
    ) {
      prev.count += 1;
      prev.collapsed_ids.push(entry.id);
    } else {
      result.push({
        ...entry,
        count: 1,
        collapsed_ids: [entry.id],
      });
    }
  }

  return result;
}

// ============================================================================
// Detail summary extraction
// ============================================================================

function getDetailSummary(entry: CollapsedAuditEntry): string | null {
  const details = entry.details_json;
  if (!details) return null;

  switch (entry.action) {
    case 'shared':
      return `Shared with ${details.target || 'user'} (${details.permission || 'view'})`;
    case 'unshared':
      return `Removed ${details.target || 'user'}`;
    case 'share_updated':
      return `Permission changed to ${details.permission || 'unknown'}`;
    case 'restored':
      return `Restored to version ${details.restored_version || '?'}`;
    case 'updated':
      if (Array.isArray(details.changes)) {
        return `Changed ${details.changes.join(', ')}`;
      }
      return null;
    case 'duplicated':
      return `From "${details.source_name || 'dashboard'}"`;
    case 'report_added':
    case 'report_updated':
    case 'report_removed':
      return details.report_name ? `"${details.report_name}"` : null;
    default:
      return null;
  }
}

// ============================================================================
// Actor display
// ============================================================================

function ActorDisplay({ actorId }: { actorId: string }) {
  const short = actorId.length > 12 ? `${actorId.substring(0, 8)}...` : actorId;

  return (
    <Tooltip content={actorId}>
      <Text as="span" variant="bodySm" tone="subdued">
        {short}
      </Text>
    </Tooltip>
  );
}

// ============================================================================
// Main component
// ============================================================================

export function AuditTimeline({ dashboardId }: AuditTimelineProps) {
  const {
    entries,
    total,
    loading,
    loadingMore,
    error,
    fetchEntries,
    loadMore,
    clearError,
  } = useAuditEntries(dashboardId);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const collapsed = collapseEntries(entries);
  const hasMore = entries.length < total;

  if (loading) {
    return (
      <Box paddingBlock="800">
        <InlineStack align="center">
          <Spinner size="large" />
        </InlineStack>
      </Box>
    );
  }

  if (error) {
    return (
      <Banner
        tone="critical"
        onDismiss={clearError}
        action={{ content: 'Retry', onAction: fetchEntries }}
      >
        {error}
      </Banner>
    );
  }

  if (collapsed.length === 0) {
    return (
      <Box paddingBlock="400">
        <Text as="p" tone="subdued" alignment="center">
          No audit events recorded yet.
        </Text>
      </Box>
    );
  }

  return (
    <BlockStack gap="400">
      {collapsed.map((entry) => {
        const config = ACTION_CONFIG[entry.action] || DEFAULT_CONFIG;
        const summary = getDetailSummary(entry);

        return (
          <Box
            key={entry.id}
            paddingInlineStart="400"
            borderInlineStartWidth="025"
            borderColor="border"
          >
            <BlockStack gap="100">
              <InlineStack gap="200" blockAlign="center">
                <Box>
                  <Icon source={config.icon} tone={config.tone || 'base'} />
                </Box>
                <Text as="span" variant="bodyMd" fontWeight="semibold">
                  {config.label}
                  {entry.count > 1 && ` (${entry.count} changes)`}
                </Text>
              </InlineStack>

              {summary && (
                <Box paddingInlineStart="600">
                  <Text as="span" variant="bodySm">
                    {summary}
                  </Text>
                </Box>
              )}

              <Box paddingInlineStart="600">
                <InlineStack gap="200">
                  <Text as="span" variant="bodySm" tone="subdued">
                    {formatRelativeTime(entry.created_at, { verbose: true })}
                  </Text>
                  <Text as="span" variant="bodySm" tone="subdued">
                    by
                  </Text>
                  <ActorDisplay actorId={entry.actor_id} />
                </InlineStack>
              </Box>
            </BlockStack>
          </Box>
        );
      })}

      {hasMore && (
        <InlineStack align="center">
          <Button
            variant="plain"
            onClick={loadMore}
            loading={loadingMore}
          >
            Load more events
          </Button>
        </InlineStack>
      )}
    </BlockStack>
  );
}
