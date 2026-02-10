/**
 * Analytics Page
 *
 * Main page for embedded Superset analytics dashboard.
 * Displays within Shopify Admin iframe.
 */

import React, { useState, useEffect } from 'react';
import {
  Page,
  Layout,
  Card,
  Select,
  BlockStack,
  InlineStack,
  Text,
  Button,
  Banner,
  SkeletonPage,
  SkeletonBodyText,
} from '@shopify/polaris';
import ShopifyEmbeddedSuperset from '../components/ShopifyEmbeddedSuperset';
import { getEmbedConfig, checkEmbedHealth } from '../services/embedApi';
import type { EmbedConfig, EmbedHealthResponse } from '../services/embedApi';
import { IncidentBanner } from '../components/health/IncidentBanner';
import { DataFreshnessBadge } from '../components/health/DataFreshnessBadge';
import { DashboardFreshnessIndicator } from '../components/health/DashboardFreshnessIndicator';
import { FeatureUpdateBanner } from '../components/changelog/FeatureUpdateBanner';
import { useNavigate } from 'react-router-dom';
import { ErrorBoundary } from '../components/ErrorBoundary';
import {
  PageErrorFallback,
  ComponentErrorFallback,
} from '../components/ErrorFallback';
import { listDashboards } from '../services/customDashboardsApi';
import type { Dashboard } from '../types/customDashboards';

const Analytics: React.FC = () => {
  const navigate = useNavigate();
  const [config, setConfig] = useState<EmbedConfig | null>(null);
  const [health, setHealth] = useState<EmbedHealthResponse | null>(null);
  const [selectedDashboard, setSelectedDashboard] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [customDashboards, setCustomDashboards] = useState<Dashboard[]>([]);
  const [hasMoreCustom, setHasMoreCustom] = useState(false);

  // Load embed configuration on mount
  useEffect(() => {
    const loadConfig = async () => {
      try {
        // Check health first
        const healthResponse = await checkEmbedHealth();
        setHealth(healthResponse);

        if (healthResponse.status !== 'healthy') {
          setError(healthResponse.message || 'Analytics service is not available');
          setLoading(false);
          return;
        }

        // Load full config
        const configResponse = await getEmbedConfig();
        setConfig(configResponse);

        // Set default dashboard
        if (configResponse.allowed_dashboards.length > 0) {
          setSelectedDashboard(configResponse.allowed_dashboards[0]);
        }
      } catch (err) {
        console.error('Failed to load analytics config:', err);
        setError('Failed to load analytics configuration');
      } finally {
        setLoading(false);
      }
    };

    loadConfig();
  }, []);

  // Fetch custom published dashboards for the dropdown
  useEffect(() => {
    let cancelled = false;
    listDashboards({ status: 'published', limit: 5 })
      .then((response) => {
        if (!cancelled) {
          setCustomDashboards(response.dashboards);
          setHasMoreCustom(response.has_more);
        }
      })
      .catch((err) => {
        console.error('Failed to fetch custom dashboards:', err);
      });
    return () => { cancelled = true; };
  }, []);

  // Handle dashboard selection
  const handleDashboardChange = (value: string) => {
    // Navigate to custom dashboard view
    if (value.startsWith('custom:')) {
      const id = value.replace('custom:', '');
      navigate(`/dashboards/${id}`);
      return;
    }
    // Navigate to all custom dashboards
    if (value === '__view_all__') {
      navigate('/dashboards');
      return;
    }
    setSelectedDashboard(value);
  };

  const handleDashboardLoad = () => {
    // no-op: load tracking handled by ShopifyEmbeddedSuperset
  };

  // Handle dashboard error
  const handleDashboardError = (err: Error) => {
    console.error('Dashboard error:', err);
  };

  // Loading state
  if (loading) {
    return (
      <SkeletonPage primaryAction>
        <Layout>
          <Layout.Section>
            <Card>
              <SkeletonBodyText lines={20} />
            </Card>
          </Layout.Section>
        </Layout>
      </SkeletonPage>
    );
  }

  // Error state
  if (error || health?.status !== 'healthy') {
    return (
      <Page title="Analytics">
        <Layout>
          <Layout.Section>
            <Banner
              title="Analytics Unavailable"
              tone="warning"
            >
              <p>{error || health?.message || 'Analytics service is currently unavailable'}</p>
            </Banner>
          </Layout.Section>
        </Layout>
      </Page>
    );
  }

  // Build dashboard options for select (system + custom)
  const systemOptions = config?.allowed_dashboards.map((id) => ({
    label: formatDashboardName(id),
    value: id,
  })) || [];

  const customOptions = customDashboards.map((d) => ({
    label: d.name,
    value: `custom:${d.id}`,
  }));

  const dashboardOptions = [
    ...systemOptions,
    ...(customOptions.length > 0
      ? [
          { label: '\u2500\u2500 Custom Dashboards \u2500\u2500', value: '__separator__', disabled: true },
          ...customOptions,
          ...(hasMoreCustom
            ? [{ label: 'View all dashboards...', value: '__view_all__' }]
            : []),
        ]
      : []),
  ];

  return (
    <ErrorBoundary
      fallbackRender={({ error, errorInfo, resetErrorBoundary }) => (
        <PageErrorFallback
          error={error}
          errorInfo={errorInfo}
          resetErrorBoundary={resetErrorBoundary}
          pageName="Analytics"
        />
      )}
    >
      <>
        {/* Incident banner at top of page */}
        <IncidentBanner />

        {/* Feature update banner for dashboard area */}
        <FeatureUpdateBanner
          featureArea="dashboard"
          maxItems={3}
          onViewAll={() => navigate('/whats-new')}
        />

        <Page
          title="Analytics"
          subtitle="View your store performance and insights"
          titleMetadata={<DataFreshnessBadge />}
        >
          <Layout>
            {/* Data freshness indicator */}
            <Layout.Section>
              <DashboardFreshnessIndicator variant="compact" />
            </Layout.Section>

            {/* Dashboard selector */}
            {dashboardOptions.length > 1 && (
              <Layout.Section>
                <Card>
                  <BlockStack gap="400">
                    <Text as="h2" variant="headingMd">
                      Select Dashboard
                    </Text>
                    <Select
                      label="Dashboard"
                      labelHidden
                      options={dashboardOptions}
                      value={selectedDashboard}
                      onChange={handleDashboardChange}
                    />
                  </BlockStack>
                </Card>
              </Layout.Section>
            )}

            {/* Embedded dashboard with component-level error boundary */}
            <Layout.Section>
              {selectedDashboard && (
                <ErrorBoundary
                  fallbackRender={({ error, resetErrorBoundary }) => (
                    <ComponentErrorFallback
                      error={error}
                      resetErrorBoundary={resetErrorBoundary}
                      componentName="Analytics Dashboard"
                    />
                  )}
                >
                  <ShopifyEmbeddedSuperset
                    dashboardId={selectedDashboard}
                    height="calc(100vh - 200px)"
                    onLoad={handleDashboardLoad}
                    onError={handleDashboardError}
                    showLoadingSkeleton
                  />
                </ErrorBoundary>
              )}
            </Layout.Section>

            {/* CTA: Create Custom Dashboard */}
            <Layout.Section>
              <Card>
                <BlockStack gap="300">
                  <Text as="h2" variant="headingMd">
                    Want more? Build your own dashboard
                  </Text>
                  <Text as="p" tone="subdued">
                    Create custom dashboards with the metrics that matter most to your business.
                  </Text>
                  <InlineStack>
                    <Button
                      variant="primary"
                      onClick={() => navigate('/dashboards')}
                    >
                      Create Custom Dashboard
                    </Button>
                  </InlineStack>
                </BlockStack>
              </Card>
            </Layout.Section>
          </Layout>
        </Page>
      </>
    </ErrorBoundary>
  );
};

/**
 * Format dashboard ID to display name.
 */
function formatDashboardName(id: string): string {
  // Convert kebab-case or snake_case to Title Case
  return id
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export default Analytics;
