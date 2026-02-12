/**
 * Wizard Grid Component
 *
 * Interactive grid layout for the customize step using react-grid-layout.
 * Allows users to drag and resize widgets before saving the dashboard.
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import { useMemo, useCallback } from 'react';
import ReactGridLayout from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { EmptyState, Box } from '@shopify/polaris';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';
import { MIN_GRID_DIMENSIONS } from '../../../types/customDashboards';
import { WizardReportPreviewCard } from './WizardReportPreviewCard';
import type { Layout } from 'react-grid-layout';

// Grid constants (matching DashboardGrid.tsx)
const GRID_COLS = 12;
const ROW_HEIGHT = 80;
const GRID_WIDTH = 1200;

export function WizardGrid() {
  const { wizardState, moveWizardWidget, removeWizardWidget } = useDashboardBuilder();

  // Build layout array from selectedWidgets
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
      })),
    [wizardState.selectedWidgets]
  );

  // Handle layout changes (optimistic, no persistence until save)
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      newLayout.forEach((item) => {
        const existing = wizardState.selectedWidgets.find((w) => w.id === item.i);
        if (!existing) return;

        const pos = existing.position_json;
        if (
          pos.x !== item.x ||
          pos.y !== item.y ||
          pos.w !== item.w ||
          pos.h !== item.h
        ) {
          moveWizardWidget(item.i, {
            x: item.x,
            y: item.y,
            w: item.w,
            h: item.h,
          });
        }
      });
    },
    [wizardState.selectedWidgets, moveWizardWidget]
  );

  // Empty state
  if (wizardState.selectedWidgets.length === 0) {
    return (
      <Box paddingBlockStart="800">
        <EmptyState
          heading="No widgets selected"
          image=""
        >
          <p>Go back to the previous step to select some widgets for your dashboard.</p>
        </EmptyState>
      </Box>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      <ReactGridLayout
        className="wizard-grid-layout"
        layout={layout}
        cols={GRID_COLS}
        rowHeight={ROW_HEIGHT}
        width={GRID_WIDTH}
        compactType="vertical"
        isDraggable={true}
        isResizable={true}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".wizard-report-drag-handle"
        margin={[16, 16]}
      >
        {wizardState.selectedWidgets.map((widget) => (
          <div key={widget.id}>
            <WizardReportPreviewCard widget={widget} onRemove={removeWizardWidget} />
          </div>
        ))}
      </ReactGridLayout>
    </div>
  );
}
