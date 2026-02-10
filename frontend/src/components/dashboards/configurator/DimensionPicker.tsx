/**
 * DimensionPicker Component
 *
 * Multi-select for choosing dimension columns. Uses Polaris ChoiceList
 * to display checkboxes. Limited to a maximum of 5 selected dimensions.
 * Used within the ReportConfiguratorModal.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { ChoiceList, BlockStack, Text, Banner } from '@shopify/polaris';
import type { ColumnMetadata } from '../../../types/customDashboards';

const MAX_DIMENSIONS = 5;

interface DimensionPickerProps {
  dimensions: string[];
  columns: ColumnMetadata[];
  onChange: (dimensions: string[]) => void;
}

export function DimensionPicker({
  dimensions,
  columns,
  onChange,
}: DimensionPickerProps) {
  const choices = columns.map((col) => ({
    label: col.column_name,
    value: col.column_name,
    disabled:
      dimensions.length >= MAX_DIMENSIONS && !dimensions.includes(col.column_name),
  }));

  const handleChange = (selected: string[]) => {
    if (selected.length <= MAX_DIMENSIONS) {
      onChange(selected);
    }
  };

  return (
    <BlockStack gap="200">
      {dimensions.length >= MAX_DIMENSIONS && (
        <Banner tone="warning">
          Maximum of {MAX_DIMENSIONS} dimensions allowed.
        </Banner>
      )}
      <ChoiceList
        title="Dimensions"
        allowMultiple
        choices={choices}
        selected={dimensions}
        onChange={handleChange}
      />
      <Text as="p" variant="bodySm" tone="subdued">
        {dimensions.length} of {MAX_DIMENSIONS} selected
      </Text>
    </BlockStack>
  );
}
