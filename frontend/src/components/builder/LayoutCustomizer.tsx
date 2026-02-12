/**
 * LayoutCustomizer Component
 *
 * Main Step 2 component for the dashboard builder wizard.
 * Allows users to customize widget layout with visual grid editor,
 * size controls, and layout operations.
 *
 * Phase 2.5 - Layout Customizer UI
 */

import { useCallback } from 'react';
import {
  BlockStack,
  InlineStack,
  Banner,
  Button,
  EmptyState,
  Box,
  Text,
} from '@shopify/polaris';
import { useDashboardBuilder } from '../../contexts/DashboardBuilderContext';
import { LayoutWidgetPlaceholder } from './LayoutWidgetPlaceholder';
import { LayoutControls } from './LayoutControls';
import {
  autoArrangeWidgets,
  resetLayoutToDefault,
  getWidgetSize,
  cycleSize,
  resizeWidget,
} from '../../utils/layoutHelpers';
import './LayoutCustomizer.css';

export function LayoutCustomizer() {
  const {
    wizardState,
    setBuilderStep,
    canProceedToPreview,
    updateWizardWidget,
    openWizardWidgetConfig,
    removeWizardWidget,
    bulkUpdateWizardWidgets,
  } = useDashboardBuilder();

  const widgets = wizardState.selectedWidgets;

  // Handle auto-arrange: reflow widgets in left-to-right, top-to-bottom order
  const handleAutoArrange = useCallback(() => {
    const arranged = autoArrangeWidgets(widgets);
    bulkUpdateWizardWidgets(arranged);
  }, [widgets, bulkUpdateWizardWidgets]);

  // Handle reset: stack widgets vertically at x=0
  const handleResetLayout = useCallback(() => {
    const reset = resetLayoutToDefault(widgets);
    bulkUpdateWizardWidgets(reset);
  }, [widgets, bulkUpdateWizardWidgets]);

  // Handle maximize: cycle widget size (small → medium → large → full → small)
  const handleMaximize = useCallback(
    (widgetId: string) => {
      const widget = widgets.find((w) => w.id === widgetId);
      if (!widget) return;

      const currentSize = getWidgetSize(widget.position_json);
      const nextSize = cycleSize(currentSize);
      const resized = resizeWidget(widget, nextSize);

      updateWizardWidget(widgetId, {
        position_json: resized.position_json,
      });
    },
    [widgets, updateWizardWidget],
  );

  // Handle settings: open configurator modal for widget
  const handleSettings = useCallback(
    (widgetId: string) => {
      openWizardWidgetConfig(widgetId);
    },
    [openWizardWidgetConfig],
  );

  // Handle delete: remove widget from wizard state
  const handleDelete = useCallback(
    (widgetId: string) => {
      removeWizardWidget(widgetId);
    },
    [removeWizardWidget],
  );

  // Empty state when no widgets selected
  if (widgets.length === 0) {
    return (
      <Box paddingBlockStart="800">
        <EmptyState heading="No widgets added yet" image="">
          <BlockStack gap="300" inlineAlign="center">
            <Text as="p" variant="bodyMd" tone="subdued">
              Go back to add widgets from the gallery before customizing your
              layout.
            </Text>
            <Button onClick={() => setBuilderStep('select')}>
              ← Back to Widget Selection
            </Button>
          </BlockStack>
        </EmptyState>
      </Box>
    );
  }

  return (
    <BlockStack gap="400">
      {/* Info banner */}
      <Banner tone="info">
        <Text as="p" variant="bodyMd">
          Customize your dashboard layout by adjusting widget sizes and
          positions. Click <strong>Settings</strong> to configure each widget,{' '}
          <strong>Maximize</strong> to cycle through sizes, or{' '}
          <strong>Delete</strong> to remove widgets.
        </Text>
      </Banner>

      {/* Layout controls */}
      <LayoutControls
        onAutoArrange={handleAutoArrange}
        onResetLayout={handleResetLayout}
        disabled={widgets.length === 0}
      />

      {/* Grid with widget placeholders */}
      <div className="layout-grid">
        {widgets.map((widget) => (
          <LayoutWidgetPlaceholder
            key={widget.id}
            widget={widget}
            onSettings={() => handleSettings(widget.id)}
            onMaximize={() => handleMaximize(widget.id)}
            onDelete={() => handleDelete(widget.id)}
          />
        ))}
      </div>

      {/* Footer navigation */}
      <Box paddingBlockStart="400">
        <InlineStack align="space-between">
          <Button
            onClick={() => setBuilderStep('select')}
            accessibilityLabel="Go back to widget selection"
          >
            ← Back to Selection
          </Button>

          <Button
            variant="primary"
            onClick={() => setBuilderStep('preview')}
            disabled={!canProceedToPreview}
            accessibilityLabel="Preview dashboard"
          >
            Preview Dashboard →
          </Button>
        </InlineStack>
      </Box>
    </BlockStack>
  );
}
