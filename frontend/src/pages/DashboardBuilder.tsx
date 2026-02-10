/**
 * DashboardBuilder Page
 *
 * Main page for building and editing custom dashboards.
 * Wraps content in a DashboardBuilderProvider and renders:
 * - Toolbar with save/publish controls
 * - Drag-and-drop grid of report cards
 * - Report configurator modal
 * - Dashboard settings modal
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Page, SkeletonPage, Banner, Layout } from '@shopify/polaris';
import { DashboardBuilderProvider, useDashboardBuilder } from '../contexts/DashboardBuilderContext';
import { DashboardToolbar } from '../components/dashboards/DashboardToolbar';
import { DashboardGrid } from '../components/dashboards/DashboardGrid';
import { ReportConfiguratorModal } from '../components/dashboards/ReportConfiguratorModal';
import { DashboardSettingsModal } from '../components/dashboards/DashboardSettingsModal';

function BuilderContent() {
  const { dashboard, isSaving, saveError, publishDashboard, clearError } = useDashboardBuilder();
  const navigate = useNavigate();
  const [showSettings, setShowSettings] = useState(false);

  if (!dashboard) return <SkeletonPage primaryAction />;

  return (
    <Page
      title={dashboard.name}
      subtitle={dashboard.description || undefined}
      primaryAction={{
        content: 'Publish',
        onAction: () => publishDashboard(),
        loading: isSaving,
        disabled: dashboard.status === 'published',
      }}
      secondaryActions={[
        { content: 'Settings', onAction: () => setShowSettings(true) },
      ]}
      breadcrumbs={[{ content: 'Dashboards', url: '/dashboards' }]}
    >
      {saveError && (
        <Banner tone="critical" onDismiss={clearError}>
          {saveError}
        </Banner>
      )}
      <Layout>
        <Layout.Section>
          <DashboardToolbar />
          <DashboardGrid />
        </Layout.Section>
      </Layout>
      <ReportConfiguratorModal />
      <DashboardSettingsModal
        open={showSettings}
        onClose={() => setShowSettings(false)}
      />
    </Page>
  );
}

export function DashboardBuilder() {
  const { dashboardId } = useParams<{ dashboardId: string }>();

  if (!dashboardId) {
    return <Banner tone="critical">No dashboard ID provided</Banner>;
  }

  return (
    <DashboardBuilderProvider dashboardId={dashboardId}>
      <BuilderContent />
    </DashboardBuilderProvider>
  );
}
