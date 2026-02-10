/**
 * DashboardView Page
 *
 * Read-only view for published dashboards. Features:
 * - Fetches dashboard by ID from URL params
 * - Renders reports in a static (non-draggable) grid
 * - Edit button for users with edit/owner/admin access
 * - Share button for owner/admin users
 * - Loading skeleton and error states
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Page,
  SkeletonPage,
  Banner,
  Layout,
  Badge,
  BlockStack,
  Text,
  Button,
  Box,
  EmptyState,
} from '@shopify/polaris';
import ReactGridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { getDashboard } from '../services/customDashboardsApi';
import { ViewReportCard } from '../components/dashboards/ViewReportCard';
import { ShareModal } from '../components/dashboards/ShareModal';
import type { Dashboard, Report } from '../types/customDashboards';
import { MIN_GRID_DIMENSIONS, GRID_COLS } from '../types/customDashboards';

const ROW_HEIGHT = 80;
const GRID_WIDTH = 1200;

export function DashboardView() {
  const { dashboardId } = useParams<{ dashboardId: string }>();
  const navigate = useNavigate();

  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showShareModal, setShowShareModal] = useState(false);

  // Fetch dashboard on mount
  useEffect(() => {
    if (!dashboardId) return;

    let cancelled = false;

    async function fetchDashboard() {
      setLoading(true);
      setError(null);

      try {
        const data = await getDashboard(dashboardId!);
        if (!cancelled) {
          setDashboard(data);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Failed to fetch dashboard:', err);
          setError(
            err instanceof Error ? err.message : 'Failed to load dashboard',
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchDashboard();

    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  // Derive permissions
  const canEdit = dashboard
    ? ['owner', 'admin', 'edit'].includes(dashboard.access_level)
    : false;
  const canShare = dashboard
    ? ['owner', 'admin'].includes(dashboard.access_level)
    : false;

  // Build grid layout
  const reports = dashboard?.reports ?? [];
  const layout = useMemo(
    () =>
      reports.map((report: Report) => {
        const minDims = MIN_GRID_DIMENSIONS[report.chart_type] ?? { w: 3, h: 2 };
        return {
          i: report.id,
          x: report.position_json.x,
          y: report.position_json.y,
          w: report.position_json.w,
          h: report.position_json.h,
          minW: minDims.w,
          minH: minDims.h,
          static: true,
        };
      }),
    [reports],
  );

  // Loading state
  if (loading) {
    return <SkeletonPage primaryAction />;
  }

  // Error state
  if (error || !dashboard) {
    return (
      <Page title="Dashboard">
        <Banner tone="critical">
          {error || 'Dashboard not found'}
        </Banner>
      </Page>
    );
  }

  // Build secondary actions
  const secondaryActions = [];
  if (canEdit) {
    secondaryActions.push({
      content: 'Edit',
      onAction: () => navigate(`/dashboards/${dashboard.id}/edit`),
    });
  }
  if (canShare) {
    secondaryActions.push({
      content: 'Share',
      onAction: () => setShowShareModal(true),
    });
  }

  // Status badge
  const statusBadge =
    dashboard.status === 'published' ? (
      <Badge tone="success">Published</Badge>
    ) : dashboard.status === 'draft' ? (
      <Badge tone="info">Draft</Badge>
    ) : (
      <Badge>Archived</Badge>
    );

  return (
    <Page
      title={dashboard.name}
      subtitle={dashboard.description || undefined}
      titleMetadata={statusBadge}
      secondaryActions={secondaryActions}
      breadcrumbs={[{ content: 'Dashboards', url: '/dashboards' }]}
    >
      <Layout>
        <Layout.Section>
          {reports.length === 0 ? (
            <Box paddingBlockStart="800">
              <EmptyState
                heading="This dashboard has no reports"
                image=""
              >
                <BlockStack gap="300" inlineAlign="center">
                  <Text as="p" variant="bodyMd" tone="subdued">
                    {canEdit
                      ? 'Switch to edit mode to add reports.'
                      : 'No reports have been added to this dashboard yet.'}
                  </Text>
                  {canEdit && (
                    <Button
                      variant="primary"
                      onClick={() => navigate(`/dashboards/${dashboard.id}/edit`)}
                    >
                      Edit dashboard
                    </Button>
                  )}
                </BlockStack>
              </EmptyState>
            </Box>
          ) : (
            <ReactGridLayout
              className="dashboard-grid-layout"
              layout={layout}
              cols={GRID_COLS}
              rowHeight={ROW_HEIGHT}
              width={GRID_WIDTH}
              compactType="vertical"
              isDraggable={false}
              isResizable={false}
            >
              {reports.map((report: Report) => (
                <div key={report.id}>
                  <ViewReportCard report={report} />
                </div>
              ))}
            </ReactGridLayout>
          )}
        </Layout.Section>
      </Layout>

      {canShare && dashboardId && (
        <ShareModal
          dashboardId={dashboardId}
          open={showShareModal}
          onClose={() => setShowShareModal(false)}
        />
      )}
    </Page>
  );
}
