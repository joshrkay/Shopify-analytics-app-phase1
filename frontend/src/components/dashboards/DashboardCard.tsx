/**
 * DashboardCard Component
 *
 * Card component for displaying a dashboard in list/grid views.
 * Shows name, description, status badge, shared badge, chart count,
 * and action buttons based on the user's access level.
 *
 * Phase 4D - Integration & Navigation Polish
 */

import {
  Card,
  BlockStack,
  InlineStack,
  Text,
  Badge,
  Button,
  ButtonGroup,
  Tooltip,
} from '@shopify/polaris';
import type { Dashboard, AccessLevel } from '../../types/customDashboards';
import { SharedBadge } from './SharedBadge';
import { formatRelativeTime } from '../../utils/dateUtils';

interface DashboardCardProps {
  dashboard: Dashboard;
  onEdit?: (dashboardId: string) => void;
  onView?: (dashboardId: string) => void;
  onDuplicate?: (dashboard: Dashboard) => void;
  onDelete?: (dashboard: Dashboard) => void;
  onShare?: (dashboardId: string) => void;
  showActions?: boolean;
  compact?: boolean;
}

const STATUS_BADGE_TONE: Record<string, 'success' | 'info' | 'warning' | undefined> = {
  published: 'success',
  draft: 'info',
  archived: 'warning',
};

function canEdit(accessLevel: AccessLevel): boolean {
  return accessLevel === 'owner' || accessLevel === 'admin' || accessLevel === 'edit';
}

function canManage(accessLevel: AccessLevel): boolean {
  return accessLevel === 'owner' || accessLevel === 'admin';
}

export function DashboardCard({
  dashboard,
  onEdit,
  onView,
  onDuplicate,
  onDelete,
  onShare,
  showActions = true,
  compact = false,
}: DashboardCardProps) {
  const accessLevel = (dashboard.access_level || 'owner') as AccessLevel;
  const chartCount = dashboard.reports?.length ?? 0;

  if (compact) {
    return (
      <Card>
        <InlineStack align="space-between" blockAlign="center">
          <InlineStack gap="200" blockAlign="center">
            <Text as="span" variant="bodyMd" fontWeight="semibold">
              {dashboard.name}
            </Text>
            <Badge tone={STATUS_BADGE_TONE[dashboard.status]}>
              {dashboard.status}
            </Badge>
            <SharedBadge accessLevel={accessLevel} />
          </InlineStack>
          {onView && (
            <Button
              variant="plain"
              size="slim"
              onClick={() => onView(dashboard.id)}
            >
              View
            </Button>
          )}
        </InlineStack>
      </Card>
    );
  }

  return (
    <Card>
      <BlockStack gap="300">
        {/* Header: Name + Status */}
        <InlineStack align="space-between" blockAlign="center">
          <Text as="h3" variant="headingSm">
            {dashboard.name}
          </Text>
          <InlineStack gap="200">
            <Badge tone={STATUS_BADGE_TONE[dashboard.status]}>
              {dashboard.status}
            </Badge>
            <SharedBadge accessLevel={accessLevel} />
          </InlineStack>
        </InlineStack>

        {/* Description */}
        {dashboard.description && (
          <Text as="p" variant="bodySm" tone="subdued">
            {dashboard.description}
          </Text>
        )}

        {/* Metadata line */}
        <Text as="p" variant="bodySm" tone="subdued">
          {chartCount} chart{chartCount !== 1 ? 's' : ''}
          {' · '}
          Updated {formatRelativeTime(dashboard.updated_at, { verbose: true })}
        </Text>

        {/* Actions */}
        {showActions && (
          <InlineStack gap="200">
            <ButtonGroup>
              {onView && (
                <Button
                  size="slim"
                  onClick={() => onView(dashboard.id)}
                >
                  View
                </Button>
              )}
              {onEdit && canEdit(accessLevel) && (
                <Button
                  size="slim"
                  onClick={() => onEdit(dashboard.id)}
                >
                  Edit
                </Button>
              )}
              {onShare && canManage(accessLevel) && (
                <Button
                  size="slim"
                  onClick={() => onShare(dashboard.id)}
                >
                  Share
                </Button>
              )}
              {onDuplicate && accessLevel === 'owner' && (
                <Button
                  size="slim"
                  onClick={() => onDuplicate(dashboard)}
                >
                  Duplicate
                </Button>
              )}
              {onDelete && accessLevel === 'owner' && (
                <Tooltip content="Delete this dashboard">
                  <Button
                    size="slim"
                    tone="critical"
                    onClick={() => onDelete(dashboard)}
                  >
                    Delete
                  </Button>
                </Tooltip>
              )}
            </ButtonGroup>
          </InlineStack>
        )}
      </BlockStack>
    </Card>
  );
}
