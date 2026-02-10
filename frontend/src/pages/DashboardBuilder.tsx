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

import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate, useBlocker } from 'react-router-dom';
import { Page, SkeletonPage, Banner, Layout, Modal, Text } from '@shopify/polaris';
import { DashboardBuilderProvider, useDashboardBuilder } from '../contexts/DashboardBuilderContext';
import { DashboardToolbar } from '../components/dashboards/DashboardToolbar';
import { DashboardGrid } from '../components/dashboards/DashboardGrid';
import { ReportConfiguratorModal } from '../components/dashboards/ReportConfiguratorModal';
import { DashboardSettingsModal } from '../components/dashboards/DashboardSettingsModal';
import { VersionHistory } from '../components/dashboards/VersionHistory';
import type { Dashboard } from '../types/customDashboards';

function BuilderContent() {
  const {
    dashboard,
    loadError,
    isDirty,
    isSaving,
    saveError,
    saveErrorStatus,
    autoSaveMessage,
    publishDashboard,
    clearError,
    refreshDashboard,
  } = useDashboardBuilder();
  const navigate = useNavigate();
  const [showSettings, setShowSettings] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  // Block navigation when there are unsaved changes
  const blocker = useBlocker(isDirty);

  // Also guard browser close / refresh
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const handleRestore = useCallback((restored: Dashboard) => {
    // Refresh the builder context to pick up restored state
    if (refreshDashboard) {
      refreshDashboard();
    }
    setShowHistory(false);
  }, [refreshDashboard]);

  // Error state: show error page instead of skeleton forever
  if (!dashboard && loadError) {
    return (
      <Page
        title="Dashboard"
        breadcrumbs={[{ content: 'Dashboards', url: '/dashboards' }]}
      >
        <Banner tone="critical" title="Failed to load dashboard">
          {loadError}
        </Banner>
      </Page>
    );
  }

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
        <Banner
          tone="critical"
          onDismiss={clearError}
          action={
            saveErrorStatus === 409
              ? { content: 'Reload dashboard', onAction: refreshDashboard }
              : undefined
          }
        >
          {saveError}
        </Banner>
      )}
      {autoSaveMessage && !saveError && (
        <Banner tone="warning">
          {autoSaveMessage}
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

      {/* Unsaved changes confirmation modal */}
      <Modal
        open={blocker.state === 'blocked'}
        onClose={() => blocker.reset?.()}
        title="You have unsaved changes"
        primaryAction={{
          content: 'Leave anyway',
          destructive: true,
          onAction: () => blocker.proceed?.(),
        }}
        secondaryActions={[
          {
            content: 'Stay on page',
            onAction: () => blocker.reset?.(),
          },
        ]}
      >
        <Modal.Section>
          <Text as="p" variant="bodyMd">
            Your unsaved changes will be lost if you leave this page.
          </Text>
        </Modal.Section>
      </Modal>
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
