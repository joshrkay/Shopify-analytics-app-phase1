/**
 * DashboardList Page
 *
 * Lists all custom dashboards for the current tenant.
 * Supports status filtering (All / Draft / Published / Archived),
 * pagination, and CRUD actions via modals.
 *
 * Feature-gated: checks entitlements before allowing create actions.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Page,
  Layout,
  Card,
  IndexTable,
  Badge,
  Button,
  Text,
  BlockStack,
  InlineStack,
  EmptyState,
  Spinner,
  Banner,
  Tabs,
  Pagination,
} from '@shopify/polaris';
import { useNavigate } from 'react-router-dom';
import type {
  Dashboard,
  DashboardStatus,
  DashboardFilters,
} from '../types/customDashboards';
import {
  listDashboards,
  getDashboardCount,
} from '../services/customDashboardsApi';
import type { DashboardCountResponse } from '../types/customDashboards';
import { fetchEntitlements, isFeatureEntitled } from '../services/entitlementsApi';
import type { EntitlementsResponse } from '../services/entitlementsApi';
import { CreateDashboardModal } from '../components/dashboards/CreateDashboardModal';
import { DuplicateDashboardModal } from '../components/dashboards/DuplicateDashboardModal';
import { DeleteDashboardModal } from '../components/dashboards/DeleteDashboardModal';

const PAGE_SIZE = 10;

type StatusTab = 'all' | 'draft' | 'published' | 'archived';

const STATUS_BADGE_TONE: Record<DashboardStatus, 'info' | 'success' | undefined> = {
  draft: 'info',
  published: 'success',
  archived: undefined,
};

const STATUS_BADGE_PROGRESS: Record<DashboardStatus, 'incomplete' | 'complete' | 'partiallyComplete'> = {
  draft: 'incomplete',
  published: 'complete',
  archived: 'partiallyComplete',
};

function formatDate(dateString: string): string {
  try {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateString;
  }
}

function getStatusLabel(status: DashboardStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function DashboardList() {
  const navigate = useNavigate();

  // Data state
  const [dashboards, setDashboards] = useState<Dashboard[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  // Filter & pagination state
  const [selectedTab, setSelectedTab] = useState<StatusTab>('all');
  const [page, setPage] = useState(1);

  // Entitlements state
  const [entitlements, setEntitlements] = useState<EntitlementsResponse | null>(null);

  // Dashboard count/limit state
  const [dashboardCount, setDashboardCount] = useState<DashboardCountResponse | null>(null);

  // Modal states
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [duplicateModalOpen, setDuplicateModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [selectedDashboard, setSelectedDashboard] = useState<Dashboard | null>(null);

  // Build filters from current state
  const buildFilters = useCallback((): DashboardFilters => {
    const filters: DashboardFilters = {
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    };

    if (selectedTab !== 'all') {
      filters.status = selectedTab as DashboardStatus;
    }

    return filters;
  }, [selectedTab, page]);

  // Fetch dashboards
  const fetchDashboards = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const filters = buildFilters();
      const response = await listDashboards(filters);
      setDashboards(response.dashboards);
      setTotal(response.total);
      setHasMore(response.has_more);
    } catch (err) {
      console.error('Failed to fetch dashboards:', err);
      setError('Failed to load dashboards. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [buildFilters]);

  // Fetch entitlements and dashboard count on mount
  useEffect(() => {
    async function loadEntitlements() {
      try {
        const data = await fetchEntitlements();
        setEntitlements(data);
      } catch (err) {
        console.error('Failed to fetch entitlements:', err);
      }
    }
    async function loadDashboardCount() {
      try {
        const data = await getDashboardCount();
        setDashboardCount(data);
      } catch (err) {
        console.error('Failed to fetch dashboard count:', err);
      }
    }
    loadEntitlements();
    loadDashboardCount();
  }, []);

  // Fetch dashboards on mount and when filters change
  useEffect(() => {
    fetchDashboards();
  }, [fetchDashboards]);

  // Check if user can create dashboards (entitlement + count limit)
  const hasEntitlement = isFeatureEntitled(entitlements, 'custom_reports');
  const canCreate = hasEntitlement && (dashboardCount?.can_create ?? true);
  const atLimit = hasEntitlement && dashboardCount !== null && !dashboardCount.can_create;

  // Tab change handler
  const handleTabChange = useCallback((selectedTabIndex: number) => {
    const tabMap: StatusTab[] = ['all', 'draft', 'published', 'archived'];
    setSelectedTab(tabMap[selectedTabIndex] ?? 'all');
    setPage(1);
  }, []);

  // Pagination handlers
  const handleNextPage = useCallback(() => {
    if (hasMore) {
      setPage(prev => prev + 1);
    }
  }, [hasMore]);

  const handlePreviousPage = useCallback(() => {
    if (page > 1) {
      setPage(prev => prev - 1);
    }
  }, [page]);

  // Row action handlers
  const handleEdit = useCallback(
    (dashboardId: string) => {
      navigate(`/dashboards/${dashboardId}/edit`);
    },
    [navigate],
  );

  const handleView = useCallback(
    (dashboardId: string) => {
      navigate(`/dashboards/${dashboardId}`);
    },
    [navigate],
  );

  const handleDuplicateClick = useCallback((dashboard: Dashboard) => {
    setSelectedDashboard(dashboard);
    setDuplicateModalOpen(true);
  }, []);

  const handleDeleteClick = useCallback((dashboard: Dashboard) => {
    setSelectedDashboard(dashboard);
    setDeleteModalOpen(true);
  }, []);

  const handleCreateClick = useCallback(() => {
    setCreateModalOpen(true);
  }, []);

  // Refresh dashboard count (after create/duplicate/delete)
  const refreshCount = useCallback(async () => {
    try {
      const data = await getDashboardCount();
      setDashboardCount(data);
    } catch {
      // Non-critical
    }
  }, []);

  // Success callbacks for modals
  const handleDuplicateSuccess = useCallback(() => {
    fetchDashboards();
    refreshCount();
  }, [fetchDashboards, refreshCount]);

  const handleDeleteSuccess = useCallback(() => {
    fetchDashboards();
    refreshCount();
  }, [fetchDashboards, refreshCount]);

  // Retry handler for error state
  const handleRetry = useCallback(() => {
    fetchDashboards();
  }, [fetchDashboards]);

  // Tab definitions
  const tabs = [
    {
      id: 'all',
      content: 'All',
      accessibilityLabel: 'All dashboards',
      panelID: 'all-dashboards-panel',
    },
    {
      id: 'draft',
      content: 'Draft',
      accessibilityLabel: 'Draft dashboards',
      panelID: 'draft-dashboards-panel',
    },
    {
      id: 'published',
      content: 'Published',
      accessibilityLabel: 'Published dashboards',
      panelID: 'published-dashboards-panel',
    },
    {
      id: 'archived',
      content: 'Archived',
      accessibilityLabel: 'Archived dashboards',
      panelID: 'archived-dashboards-panel',
    },
  ];

  const selectedTabIndex = tabs.findIndex(t => t.id === selectedTab);

  // IndexTable resource name
  const resourceName = {
    singular: 'dashboard',
    plural: 'dashboards',
  };

  // IndexTable headings
  const headings: [{ title: string }, ...{ title: string }[]] = [
    { title: 'Name' },
    { title: 'Status' },
    { title: 'Reports' },
    { title: 'Last updated' },
    { title: 'Actions' },
  ];

  // Render table rows
  const rowMarkup = dashboards.map((dashboard, index) => (
    <IndexTable.Row
      id={dashboard.id}
      key={dashboard.id}
      position={index}
    >
      <IndexTable.Cell>
        <Text as="span" variant="bodyMd" fontWeight="semibold">
          {dashboard.name}
        </Text>
      </IndexTable.Cell>

      <IndexTable.Cell>
        <Badge
          tone={STATUS_BADGE_TONE[dashboard.status]}
          progress={STATUS_BADGE_PROGRESS[dashboard.status]}
        >
          {getStatusLabel(dashboard.status)}
        </Badge>
      </IndexTable.Cell>

      <IndexTable.Cell>
        <Text as="span" variant="bodyMd">
          {dashboard.reports.length}
        </Text>
      </IndexTable.Cell>

      <IndexTable.Cell>
        <Text as="span" variant="bodyMd">
          {formatDate(dashboard.updated_at)}
        </Text>
      </IndexTable.Cell>

      <IndexTable.Cell>
        <InlineStack gap="200">
          <Button
            size="slim"
            onClick={() => handleEdit(dashboard.id)}
          >
            Edit
          </Button>
          <Button
            size="slim"
            onClick={() => handleView(dashboard.id)}
          >
            View
          </Button>
          <Button
            size="slim"
            onClick={() => handleDuplicateClick(dashboard)}
            disabled={!canCreate}
          >
            Duplicate
          </Button>
          <Button
            size="slim"
            tone="critical"
            onClick={() => handleDeleteClick(dashboard)}
          >
            Delete
          </Button>
        </InlineStack>
      </IndexTable.Cell>
    </IndexTable.Row>
  ));

  // Render content based on state
  const renderContent = () => {
    // Loading state
    if (isLoading) {
      return (
        <Card>
          <BlockStack gap="400" inlineAlign="center">
            <Spinner size="large" accessibilityLabel="Loading dashboards" />
            <Text as="p" variant="bodyMd" tone="subdued">
              Loading dashboards...
            </Text>
          </BlockStack>
        </Card>
      );
    }

    // Error state
    if (error) {
      return (
        <Card>
          <Banner
            tone="critical"
            title="Error loading dashboards"
            action={{ content: 'Retry', onAction: handleRetry }}
            onDismiss={() => setError(null)}
          >
            {error}
          </Banner>
        </Card>
      );
    }

    // Empty state
    if (dashboards.length === 0) {
      return (
        <Card>
          <EmptyState
            heading="Create your first dashboard"
            action={
              canCreate
                ? {
                    content: 'Create dashboard',
                    onAction: handleCreateClick,
                  }
                : undefined
            }
            secondaryAction={{
              content: 'Browse templates',
              onAction: () => navigate('/dashboards/templates'),
            }}
            image=""
          >
            <Text as="p" variant="bodyMd" tone="subdued">
              {selectedTab === 'all'
                ? 'Dashboards let you organize and visualize your data with custom reports and charts. Get started by creating a blank dashboard or browsing templates.'
                : `No ${selectedTab} dashboards found. Try changing the filter or create a new dashboard.`}
            </Text>
          </EmptyState>
        </Card>
      );
    }

    // Table with data
    return (
      <Card padding="0">
        <IndexTable
          resourceName={resourceName}
          itemCount={dashboards.length}
          headings={headings}
          selectable={false}
        >
          {rowMarkup}
        </IndexTable>
      </Card>
    );
  };

  return (
    <Page
      title="Dashboards"
      subtitle="Create and manage custom dashboards"
      primaryAction={
        canCreate
          ? {
              content: 'Create dashboard',
              onAction: handleCreateClick,
            }
          : undefined
      }
    >
      <Layout>
        <Layout.Section>
          <BlockStack gap="400">
            {/* Limit banner */}
            {atLimit && (
              <Banner tone="warning" title="Dashboard limit reached">
                You&apos;ve reached the maximum of {dashboardCount?.max_count} dashboards
                for your current plan. Delete an existing dashboard or upgrade
                your plan to create more.
              </Banner>
            )}
            {/* Status filter tabs */}
            <Card padding="0">
              <Tabs
                tabs={tabs}
                selected={selectedTabIndex}
                onSelect={handleTabChange}
              >
                <div style={{ padding: '16px' }}>
                  {renderContent()}
                </div>
              </Tabs>
            </Card>

            {/* Pagination */}
            {!isLoading && !error && total > PAGE_SIZE && (
              <InlineStack align="center" gap="400">
                <Pagination
                  hasPrevious={page > 1}
                  hasNext={hasMore}
                  onPrevious={handlePreviousPage}
                  onNext={handleNextPage}
                />
                <Text as="p" variant="bodySm" tone="subdued">
                  Showing {dashboards.length} of {total} dashboards
                </Text>
              </InlineStack>
            )}
          </BlockStack>
        </Layout.Section>
      </Layout>

      {/* Create Dashboard Modal */}
      <CreateDashboardModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        atLimit={atLimit}
        maxCount={dashboardCount?.max_count ?? null}
        onSuccess={refreshCount}
      />

      {/* Duplicate Dashboard Modal */}
      <DuplicateDashboardModal
        open={duplicateModalOpen}
        onClose={() => setDuplicateModalOpen(false)}
        dashboard={selectedDashboard}
        onSuccess={handleDuplicateSuccess}
      />

      {/* Delete Dashboard Modal */}
      <DeleteDashboardModal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        dashboard={selectedDashboard}
        onSuccess={handleDeleteSuccess}
      />
    </Page>
  );
}

export default DashboardList;
