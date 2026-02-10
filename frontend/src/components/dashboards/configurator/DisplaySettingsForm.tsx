/**
 * DisplaySettingsForm Component
 *
 * Form fields for configuring chart display options including:
 * - Show legend toggle
 * - Legend position selection
 * - Axis labels for X and Y axes
 * - Color scheme selection
 *
 * Phase 3 - Dashboard Builder UI
 */

import { BlockStack, Checkbox, Select, TextField, Text } from '@shopify/polaris';
import type { DisplayConfig } from '../../../types/customDashboards';

const LEGEND_POSITION_OPTIONS = [
  { label: 'Top', value: 'top' },
  { label: 'Bottom', value: 'bottom' },
  { label: 'Left', value: 'left' },
  { label: 'Right', value: 'right' },
];

const COLOR_SCHEME_OPTIONS = [
  { label: 'Default', value: 'default' },
  { label: 'Cool', value: 'cool' },
  { label: 'Warm', value: 'warm' },
];

interface DisplaySettingsFormProps {
  display: DisplayConfig;
  onChange: (display: DisplayConfig) => void;
}

export function DisplaySettingsForm({
  display,
  onChange,
}: DisplaySettingsFormProps) {
  const handleShowLegendChange = (checked: boolean) => {
    onChange({ ...display, show_legend: checked });
  };

  const handleLegendPositionChange = (value: string) => {
    onChange({ ...display, legend_position: value });
  };

  const handleAxisLabelXChange = (value: string) => {
    onChange({ ...display, axis_label_x: value || undefined });
  };

  const handleAxisLabelYChange = (value: string) => {
    onChange({ ...display, axis_label_y: value || undefined });
  };

  const handleColorSchemeChange = (value: string) => {
    onChange({ ...display, color_scheme: value });
  };

  return (
    <BlockStack gap="300">
      <Text as="p" variant="bodyMd" fontWeight="semibold">
        Display settings
      </Text>

      <Checkbox
        label="Show legend"
        checked={display.show_legend}
        onChange={handleShowLegendChange}
      />

      {display.show_legend && (
        <Select
          label="Legend position"
          options={LEGEND_POSITION_OPTIONS}
          value={display.legend_position ?? 'top'}
          onChange={handleLegendPositionChange}
        />
      )}

      <TextField
        label="X-axis label"
        value={display.axis_label_x ?? ''}
        onChange={handleAxisLabelXChange}
        placeholder="e.g., Date"
        autoComplete="off"
      />

      <TextField
        label="Y-axis label"
        value={display.axis_label_y ?? ''}
        onChange={handleAxisLabelYChange}
        placeholder="e.g., Revenue ($)"
        autoComplete="off"
      />

      <Select
        label="Color scheme"
        options={COLOR_SCHEME_OPTIONS}
        value={display.color_scheme ?? 'default'}
        onChange={handleColorSchemeChange}
      />
    </BlockStack>
  );
}
