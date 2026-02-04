/**
 * ChangelogBadge Component
 *
 * Displays a badge showing the count of unread changelog entries.
 * Auto-refreshes at a configurable interval.
 *
 * Story 9.7 - In-App Changelog & Release Notes
 */

import { useCallback } from 'react';
import { getUnreadCountNumber } from '../../services/changelogApi';
import type { FeatureArea } from '../../types/changelog';
import { NotificationBadge } from '../common/NotificationBadge';

interface ChangelogBadgeProps {
  onClick?: () => void;
  refreshInterval?: number;
  showLabel?: boolean;
  label?: string;
  featureArea?: FeatureArea;
}

export function ChangelogBadge({
  onClick,
  refreshInterval = 60000,
  showLabel = false,
  label = "What's New",
  featureArea,
}: ChangelogBadgeProps) {
  const fetchCount = useCallback(
    () => getUnreadCountNumber(featureArea),
    [featureArea]
  );

  return (
    <NotificationBadge
      fetchCount={fetchCount}
      onClick={onClick}
      refreshInterval={refreshInterval}
      showLabel={showLabel}
      label={label}
      singularNoun="new update"
      pluralNoun="new updates"
    />
  );
}

export default ChangelogBadge;
