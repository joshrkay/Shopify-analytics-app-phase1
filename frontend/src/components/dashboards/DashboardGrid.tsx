/**
 * DashboardGrid Component
 *
 * Renders the dashboard reports in a drag-and-drop grid layout
 * using react-grid-layout. Features:
 * - 12-column responsive grid with vertical compaction
 * - Drag and resize with minimum dimensions per chart type
 * - Optimistic layout updates via moveReport
 * - Batched persistence via commitLayout on drag/resize stop
 * - Empty state when no reports exist
 *
 * Phase 3 - Dashboard Builder UI
 */

import { useCallback, useMemo } from 'react';
import ReactGridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { BlockStack, Text, Button, EmptyState, Box } from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';
import { ReportCard } from './ReportCard';
import { MIN_GRID_DIMENSIONS, GRID_COLS } from '../../types/customDashboards';
import type { Report } from '../../types/customDashboards';

const ROW_HEIGHT = 80;
const GRID_WIDTH = 1200;

export function DashboardGrid() {
  const {
    dashboard,
    moveReport,
    commitLayout,
    openReportConfig,
  } = useDashboardBuilder();

  const reports = dashboard?.reports ?? [];
  const canEdit = dashboard
    ? ['owner', 'admin', 'edit'].includes(dashboard.access_level)
    : false;

  // Build the layout array from report positions
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
        };
      }),
    [reports],
  );

  // Update positions optimistically during drag/resize
  const handleLayoutChange = useCallback(
    (newLayout: ReactGridLayout.Layout[]) => {
      newLayout.forEach((item) => {
        const existing = reports.find((r) => r.id === item.i);
        if (!existing) return;

        const pos = existing.position_json;
        if (
          pos.x !== item.x ||
          pos.y !== item.y ||
          pos.w !== item.w ||
          pos.h !== item.h
        ) {
          moveReport(item.i, {
            x: item.x,
            y: item.y,
            w: item.w,
            h: item.h,
          });
        }
      });
    },
    [reports, moveReport],
  );

  // Persist layout changes when drag or resize finishes
  const handleDragStop = useCallback(() => {
    commitLayout();
  }, [commitLayout]);

  const handleResizeStop = useCallback(() => {
    commitLayout();
  }, [commitLayout]);

  // Empty state
  if (reports.length === 0) {
    return (
      <Box paddingBlockStart="800">
        <EmptyState
          heading="No reports yet"
          image=""
        >
          <BlockStack gap="300" inlineAlign="center">
            <Text as="p" variant="bodyMd" tone="subdued">
              Add your first report to start building this dashboard.
            </Text>
            {canEdit && (
              <Button variant="primary" onClick={() => openReportConfig(null)}>
                Add report
              </Button>
            )}
          </BlockStack>
        </EmptyState>
      </Box>
    );
  }

  return (
    <ReactGridLayout
      className="dashboard-grid-layout"
      layout={layout}
      cols={GRID_COLS}
      rowHeight={ROW_HEIGHT}
      width={GRID_WIDTH}
      compactType="vertical"
      isDraggable={canEdit}
      isResizable={canEdit}
      onLayoutChange={handleLayoutChange}
      onDragStop={handleDragStop}
      onResizeStop={handleResizeStop}
      draggableHandle=".report-card-drag-handle"
    >
      {reports.map((report: Report) => (
        <div key={report.id}>
          <ReportCard report={report} />
        </div>
      ))}
    </ReactGridLayout>
  );
}
