/**
 * Preview Grid Component
 *
 * Read-only grid layout for the preview step showing widgets with sample or live data.
 * Matches the layout from the customize step but without drag/resize capability.
 *
 * Phase 2.6 - Preview Step Live Data Integration
 */

import { useMemo } from 'react';
import ReactGridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { EmptyState, Box } from '@shopify/polaris';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';
import { MIN_GRID_DIMENSIONS } from '../../../types/customDashboards';
import { PreviewReportCard } from './PreviewReportCard';
import type { Layout } from 'react-grid-layout';

// Grid constants (matching DashboardGrid.tsx and WizardGrid.tsx)
const GRID_COLS = 12;
const ROW_HEIGHT = 80;
const GRID_WIDTH = 1200;

interface PreviewGridProps {
  useLiveData?: boolean; // NEW: Enable live data fetching
  dateRange?: string; // NEW: Date range for queries
  refetchKey?: number; // NEW: Key that changes to trigger refetch
}

export function PreviewGrid({ useLiveData = false, dateRange = '30', refetchKey = 0 }: PreviewGridProps) {
  const { wizardState } = useDashboardBuilder();

  // Build layout (read-only in preview)
  const layout: Layout[] = useMemo(
    () =>
      wizardState.selectedWidgets.map((widget) => ({
        i: widget.id,
        x: widget.position_json.x,
        y: widget.position_json.y,
        w: widget.position_json.w,
        h: widget.position_json.h,
        minW: MIN_GRID_DIMENSIONS[widget.chart_type].w,
        minH: MIN_GRID_DIMENSIONS[widget.chart_type].h,
        static: true, // Make items static (non-draggable/non-resizable)
      })),
    [wizardState.selectedWidgets]
  );

  // Empty state
  if (wizardState.selectedWidgets.length === 0) {
    return (
      <Box paddingBlockStart="800">
        <EmptyState
          heading="No widgets selected"
          image=""
        >
          <p>Go back to select some widgets for your dashboard.</p>
        </EmptyState>
      </Box>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      <ReactGridLayout
        className="preview-grid-layout"
        layout={layout}
        cols={GRID_COLS}
        rowHeight={ROW_HEIGHT}
        width={GRID_WIDTH}
        compactType="vertical"
        isDraggable={false}  // Read-only
        isResizable={false}  // Read-only
        margin={[16, 16]}
      >
        {wizardState.selectedWidgets.map((widget) => (
          <div key={widget.id}>
            <PreviewReportCard
              report={widget}
              useLiveData={useLiveData}
              dateRange={dateRange}
              refetchKey={refetchKey}
            />
          </div>
        ))}
      </ReactGridLayout>
    </div>
  );
}
