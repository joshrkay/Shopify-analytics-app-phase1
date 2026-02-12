/**
 * Layout Controls Component
 *
 * Provides Auto Arrange and Reset Layout buttons for the wizard grid.
 * - Auto Arrange: Smart 2-column layout when widgets fit
 * - Reset Layout: Restore to initial vertical stack
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import { useCallback } from 'react';
import { InlineStack, Button } from '@shopify/polaris';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';
import { MIN_GRID_DIMENSIONS, GRID_COLS } from '../../../types/customDashboards';

export function LayoutControls() {
  const { wizardState, moveWizardWidget } = useDashboardBuilder();

  // Auto-arrange: Smart 2-column layout for smaller widgets, single column for larger
  const handleAutoArrange = useCallback(() => {
    let currentY = 0;
    let currentX = 0;

    wizardState.selectedWidgets.forEach((widget) => {
      const minDims = MIN_GRID_DIMENSIONS[widget.chart_type];
      const defaultW = minDims.w * 2; // Use 2x minimum width
      const defaultH = minDims.h * 2; // Use 2x minimum height

      // Try to fit two widgets per row if they're small enough
      if (currentX + defaultW > GRID_COLS) {
        currentX = 0;
        currentY += defaultH;
      }

      moveWizardWidget(widget.id, {
        x: currentX,
        y: currentY,
        w: defaultW,
        h: defaultH,
      });

      currentX += defaultW;
    });
  }, [wizardState.selectedWidgets, moveWizardWidget]);

  // Reset layout: Restore to initial vertical stack (as widgets were added)
  const handleResetLayout = useCallback(() => {
    let currentY = 0;

    wizardState.selectedWidgets.forEach((widget) => {
      const minDims = MIN_GRID_DIMENSIONS[widget.chart_type];
      const width = minDims.w * 2;
      const height = minDims.h * 2;

      moveWizardWidget(widget.id, {
        x: 0,
        y: currentY,
        w: width,
        h: height,
      });

      currentY += height;
    });
  }, [wizardState.selectedWidgets, moveWizardWidget]);

  if (wizardState.selectedWidgets.length === 0) {
    return null;
  }

  return (
    <InlineStack gap="200">
      <Button onClick={handleAutoArrange}>Auto Arrange</Button>
      <Button onClick={handleResetLayout}>Reset Layout</Button>
    </InlineStack>
  );
}
