/**
 * Layout Helpers for Dashboard Builder
 *
 * Utility functions for managing widget layout in the dashboard builder wizard.
 * Handles size mapping, layout algorithms, and grid position calculations.
 *
 * Phase 2.5 - Layout Customizer UI
 */

import type {
  GridPosition,
  Report,
  WidgetSize,
} from '../types/customDashboards';
import {
  MIN_GRID_DIMENSIONS,
  GRID_COLS,
  SIZE_TO_COLUMNS,
} from '../types/customDashboards';

// =============================================================================
// Size Utilities
// =============================================================================

/**
 * Get the display size label from a GridPosition
 * Maps column width to size: 3→small, 6→medium, 9→large, 12→full
 */
export function getWidgetSize(position: GridPosition): WidgetSize {
  const cols = position.w;

  // Map to nearest size
  if (cols <= 3) return 'small';
  if (cols <= 6) return 'medium';
  if (cols <= 9) return 'large';
  return 'full';
}

/**
 * Cycle to next size: small → medium → large → full → small
 */
export function cycleSize(currentSize: WidgetSize): WidgetSize {
  const cycle: WidgetSize[] = ['small', 'medium', 'large', 'full'];
  const currentIndex = cycle.indexOf(currentSize);
  return cycle[(currentIndex + 1) % cycle.length];
}

/**
 * Update widget to new size, preserving x/y position
 * Respects MIN_GRID_DIMENSIONS for height based on chart type
 *
 * @param widget - The widget to resize
 * @param newSize - The target size (small/medium/large/full)
 * @returns Updated widget with new position_json
 */
export function resizeWidget(widget: Report, newSize: WidgetSize): Report {
  const w = SIZE_TO_COLUMNS[newSize];
  const minDims = MIN_GRID_DIMENSIONS[widget.chart_type];

  return {
    ...widget,
    position_json: {
      ...widget.position_json,
      w,
      h: minDims.h, // Use minimum height for chart type
    },
  };
}

// =============================================================================
// Layout Algorithms
// =============================================================================

/**
 * Auto-arrange widgets in a left-to-right, top-to-bottom flow
 * Respects 12-column grid and widget sizes
 *
 * Algorithm:
 * - Track current position (x, y) and current row height
 * - For each widget: if it doesn't fit in current row, move to next row
 * - Place widget at current position, advance x, update row height
 *
 * @param widgets - Array of widgets to arrange
 * @returns New array with updated position_json for each widget
 */
export function autoArrangeWidgets(widgets: Report[]): Report[] {
  let currentX = 0;
  let currentY = 0;
  let rowMaxHeight = 0;

  return widgets.map((widget) => {
    const w = widget.position_json.w;
    const h = widget.position_json.h;

    // If widget doesn't fit in current row, move to next row
    if (currentX + w > GRID_COLS) {
      currentX = 0;
      currentY += rowMaxHeight;
      rowMaxHeight = 0;
    }

    const position: GridPosition = {
      x: currentX,
      y: currentY,
      w,
      h,
    };

    // Update tracking for next widget
    currentX += w;
    rowMaxHeight = Math.max(rowMaxHeight, h);

    return {
      ...widget,
      position_json: position,
    };
  });
}

/**
 * Reset layout to default vertical stack at x=0
 * Preserves widget widths and heights, just resets positions
 *
 * @param widgets - Array of widgets to reset
 * @returns New array with widgets stacked vertically
 */
export function resetLayoutToDefault(widgets: Report[]): Report[] {
  let currentY = 0;

  return widgets.map((widget) => {
    const position: GridPosition = {
      x: 0,
      y: currentY,
      w: widget.position_json.w, // Keep current width
      h: widget.position_json.h, // Keep current height
    };

    currentY += widget.position_json.h;

    return {
      ...widget,
      position_json: position,
    };
  });
}
