/**
 * MetricVersionBanner Component (Story 2.3)
 *
 * Displays contextual banners on dashboards when metric version
 * changes are relevant to the user:
 *
 * - "info" tone: A newer version is available but dashboard is pinned
 * - "warning" tone: Bound version is deprecated with a sunset countdown
 * - "critical" tone: Metric version is sunset (dashboard will fail)
 *
 * Acceptance criteria:
 * - Banner appears on affected dashboards only
 * - Banner includes date + version change summary
 */

import {
  Banner,
  Text,
  BlockStack,
  InlineStack,
  Badge,
} from '@shopify/polaris';
import type { MetricBannerData } from '../types/metricBindings';

interface MetricVersionBannerProps {
  /** Banner data from the metric status checker API */
  banners: MetricBannerData[];
}

/**
 * Renders metric version banners for a dashboard.
 * Only shows banners where show=true.
 */
export function MetricVersionBanner({ banners }: MetricVersionBannerProps) {
  const visibleBanners = banners.filter((b) => b.show);

  if (visibleBanners.length === 0) {
    return null;
  }

  return (
    <BlockStack gap="300">
      {visibleBanners.map((banner) => (
        <MetricBanner key={`${banner.dashboard_id}-${banner.metric_name}`} banner={banner} />
      ))}
    </BlockStack>
  );
}

function MetricBanner({ banner }: { banner: MetricBannerData }) {
  const title = getBannerTitle(banner);

  return (
    <Banner title={title} tone={banner.tone}>
      <BlockStack gap="200">
        <Text as="p">{banner.message}</Text>
        <InlineStack gap="300" align="start">
          <Badge tone={banner.tone === 'critical' ? 'critical' : undefined}>
            {`${banner.metric_name} ${banner.current_version}`}
          </Badge>
          {banner.change_date && (
            <Text as="span" tone="subdued">
              Change date: {formatDate(banner.change_date)}
            </Text>
          )}
          {banner.new_version_available && (
            <Badge tone="info">
              {`${banner.new_version_available} available`}
            </Badge>
          )}
          {banner.days_until_sunset != null && banner.days_until_sunset > 0 && (
            <Text as="span" tone="caution">
              {banner.days_until_sunset} {banner.days_until_sunset === 1 ? 'day' : 'days'} until retirement
            </Text>
          )}
        </InlineStack>
      </BlockStack>
    </Banner>
  );
}

function getBannerTitle(banner: MetricBannerData): string {
  switch (banner.tone) {
    case 'critical':
      return 'Metric Version Retired';
    case 'warning':
      return 'Metric Version Deprecated';
    case 'info':
      return 'Newer Metric Version Available';
    default:
      return 'Metric Version Notice';
  }
}

function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
}
