/**
 * LayoutControls Component
 *
 * Control buttons for layout operations (Reset Layout, Auto Arrange).
 * Provides quick actions for managing widget positions in the grid.
 *
 * Phase 2.5 - Layout Customizer UI
 */

import { InlineStack, Button } from '@shopify/polaris';

interface LayoutControlsProps {
  onAutoArrange: () => void;
  onResetLayout: () => void;
  disabled?: boolean;
}

export function LayoutControls({
  onAutoArrange,
  onResetLayout,
  disabled = false,
}: LayoutControlsProps) {
  return (
    <InlineStack gap="200" align="start">
      <Button onClick={onResetLayout} disabled={disabled}>
        Reset Layout
      </Button>
      <Button onClick={onAutoArrange} disabled={disabled}>
        Auto Arrange
      </Button>
    </InlineStack>
  );
}
