/**
 * InsightBadge Component
 *
 * Contextual badge showing unread insights count.
 * Can be placed on dashboards or navigation items.
 *
 * Story 9.3 - Insight & Recommendation UX
 */

import { getUnreadInsightsCount } from '../../services/insightsApi';
import { NotificationBadge } from '../common/NotificationBadge';

interface InsightBadgeProps {
  /**
   * Optional click handler when badge is clicked.
   */
  onClick?: () => void;
  /**
   * Refresh interval in milliseconds. Set to 0 to disable auto-refresh.
   * Default: 60000 (1 minute)
   */
  refreshInterval?: number;
  /**
   * Show text label alongside count.
   */
  showLabel?: boolean;
  /**
   * Custom label text.
   */
  label?: string;
}

export function InsightBadge({
  onClick,
  refreshInterval = 60000,
  showLabel = false,
  label = 'Insights',
}: InsightBadgeProps) {
  return (
    <NotificationBadge
      fetchCount={getUnreadInsightsCount}
      onClick={onClick}
      refreshInterval={refreshInterval}
      showLabel={showLabel}
      label={label}
      singularNoun="unread insight"
      pluralNoun="unread insights"
    />
  );
}

export default InsightBadge;
