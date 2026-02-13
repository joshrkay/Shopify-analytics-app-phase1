/**
 * SharedBadge Component
 *
 * Displays a badge indicating the dashboard's sharing status.
 * Shows different variants based on the user's access level.
 *
 * Phase 4B - Sharing UI
 */

import { Badge, Tooltip } from '@shopify/polaris';
import type { AccessLevel } from '../../types/customDashboards';

interface SharedBadgeProps {
  accessLevel: AccessLevel;
  shareCount?: number;
}

export function SharedBadge({ accessLevel, shareCount }: SharedBadgeProps) {
  if (accessLevel === 'owner') {
    if (!shareCount || shareCount === 0) return null;
    return <Badge tone="info">{`Shared (${shareCount})`}</Badge>;
  }

  if (accessLevel === 'admin') {
    return (
      <Tooltip content="You have admin access to this dashboard">
        <Badge tone="info">Shared (Admin)</Badge>
      </Tooltip>
    );
  }

  if (accessLevel === 'edit') {
    return (
      <Tooltip content="You have edit access to this dashboard">
        <Badge>Shared (Edit)</Badge>
      </Tooltip>
    );
  }

  if (accessLevel === 'view') {
    return (
      <Tooltip content="You have view-only access to this dashboard">
        <Badge>Shared (View)</Badge>
      </Tooltip>
    );
  }

  return null;
}
