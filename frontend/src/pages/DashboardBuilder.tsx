/**
 * DashboardBuilder Page
 *
 * Main page for building and editing custom dashboards.
 * Wraps content in a DashboardBuilderProvider and renders:
 * - Toolbar with save/publish controls
 * - Drag-and-drop grid of report cards
 * - Report configurator modal
 * - Dashboard settings modal
 * - Version history panel (Phase 4A)
 *
 * Phase 3 - Dashboard Builder UI
 * Phase 4A - Version History Integration
 */

import { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Page, SkeletonPage, Banner, Layout } from '@shopify/polaris';
import { DashboardBuilderProvider, useDashboardBuilder } from '../contexts/DashboardBuilderContext';
import { DashboardToolbar } from '../components/dashboards/DashboardToolbar';
import { DashboardGrid } from '../components/dashboards/DashboardGrid';
import { ReportConfiguratorModal } from '../components/dashboards/ReportConfiguratorModal';
import { DashboardSettingsModal } from '../components/dashboards/DashboardSettingsModal';
import { VersionHistory } from '../components/dashboards/VersionHistory';
import type { Dashboard } from '../types/customDashboards';

function BuilderContent() {
  const { dashboard, isSaving, saveError, publishDashboard, clearError, refreshDashboard } = useDashboardBuilder();
  const navigate = useNavigate();
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const handleRestore = useCallback((restored: Dashboard) => {
    // Refresh the builder context to pick up restored state
    if (refreshDashboard) {
      refreshDashboard();
    }
    setShowHistory(false);
  }, [refreshDashboard]);

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
        { content: 'History', onAction: () => setShowHistory(true) },
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
      <VersionHistory
        dashboardId={dashboard.id}
        currentVersionNumber={dashboard.version_number}
        open={showHistory}
        onClose={() => setShowHistory(false)}
        onRestore={handleRestore}
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
