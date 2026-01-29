/**
 * IncidentBanner Component
 *
 * Displays calm, scoped incident communication.
 * Shows at top of app when active incidents exist.
 *
 * Features:
 * - Severity-based tone (info/warning/critical)
 * - Scope messaging (which connector/data affected)
 * - ETA when available
 * - Status page link
 * - Dismissible (acknowledges incident)
 *
 * Story 9.6 - Incident Communication
 */

import { Banner, Text, Link, BlockStack } from '@shopify/polaris';
import { useActiveIncidents } from '../../contexts/DataHealthContext';

interface IncidentBannerProps {
  /**
   * Callback when status page link is clicked.
   */
  onViewStatus?: () => void;
}

export function IncidentBanner({ onViewStatus }: IncidentBannerProps) {
  const { incidents, shouldShowBanner, mostSevereIncident, acknowledgeIncident } =
    useActiveIncidents();

  if (!shouldShowBanner || !mostSevereIncident) {
    return null;
  }

  // Get banner tone based on severity
  const getTone = (): 'info' | 'warning' | 'critical' => {
    switch (mostSevereIncident.severity) {
      case 'critical':
        return 'critical';
      case 'high':
        return 'warning';
      default:
        return 'info';
    }
  };

  // Build title from scope
  const getTitle = (): string => {
    if (mostSevereIncident.severity === 'critical') {
      return `${mostSevereIncident.scope} - Critical Issue`;
    }
    return `${mostSevereIncident.scope} may be delayed`;
  };

  const handleDismiss = async () => {
    try {
      await acknowledgeIncident(mostSevereIncident.id);
    } catch (err) {
      console.error('Failed to acknowledge incident:', err);
    }
  };

  const tone = getTone();
  const title = getTitle();

  return (
    <Banner
      title={title}
      tone={tone}
      onDismiss={handleDismiss}
    >
      <BlockStack gap="200">
        <Text as="p">{mostSevereIncident.message}</Text>
        {mostSevereIncident.eta && (
          <Text as="p" tone="subdued">
            {mostSevereIncident.eta}
          </Text>
        )}
        {mostSevereIncident.status_page_url && (
          <Link
            url={mostSevereIncident.status_page_url}
            external
            onClick={onViewStatus}
          >
            View status page
          </Link>
        )}
        {incidents.length > 1 && (
          <Text as="p" tone="subdued">
            {incidents.length - 1} other incident{incidents.length > 2 ? 's' : ''} active
          </Text>
        )}
      </BlockStack>
    </Banner>
  );
}

export default IncidentBanner;
