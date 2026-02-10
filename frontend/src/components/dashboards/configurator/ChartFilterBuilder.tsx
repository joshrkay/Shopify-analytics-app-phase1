/**
 * ChartFilterBuilder Component
 *
 * Dynamic list of filter rows for chart-level filtering.
 * Each row allows selection of a column, operator, and value.
 * Rows can be added or removed. Used within the ReportConfiguratorModal.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { BlockStack, InlineStack, Select, TextField, Button, Text } from '@shopify/polaris';
import type { ChartFilter, FilterOperator, ColumnMetadata } from '../../../types/customDashboards';

const OPERATOR_OPTIONS: { label: string; value: FilterOperator }[] = [
  { label: '= (equals)', value: '=' },
  { label: '!= (not equals)', value: '!=' },
  { label: '> (greater than)', value: '>' },
  { label: '< (less than)', value: '<' },
  { label: '>= (greater or equal)', value: '>=' },
  { label: '<= (less or equal)', value: '<=' },
  { label: 'IN', value: 'IN' },
  { label: 'NOT IN', value: 'NOT IN' },
  { label: 'LIKE', value: 'LIKE' },
];

interface ChartFilterBuilderProps {
  filters: ChartFilter[];
  columns: ColumnMetadata[];
  onChange: (filters: ChartFilter[]) => void;
}

export function ChartFilterBuilder({
  filters,
  columns,
  onChange,
}: ChartFilterBuilderProps) {
  const columnOptions = [
    { label: 'Select column', value: '' },
    ...columns.map((col) => ({
      label: col.column_name,
      value: col.column_name,
    })),
  ];

  const handleColumnChange = (index: number, column: string) => {
    const updated = [...filters];
    updated[index] = { ...updated[index], column };
    onChange(updated);
  };

  const handleOperatorChange = (index: number, operator: string) => {
    const updated = [...filters];
    updated[index] = { ...updated[index], operator: operator as FilterOperator };
    onChange(updated);
  };

  const handleValueChange = (index: number, value: string) => {
    const updated = [...filters];
    updated[index] = { ...updated[index], value };
    onChange(updated);
  };

  const handleRemove = (index: number) => {
    const updated = filters.filter((_, i) => i !== index);
    onChange(updated);
  };

  const handleAdd = () => {
    onChange([
      ...filters,
      { column: '', operator: '=' as FilterOperator, value: '' },
    ]);
  };

  return (
    <BlockStack gap="300">
      <Text as="p" variant="bodyMd" fontWeight="semibold">
        Filters
      </Text>

      {filters.map((filter, index) => (
        <InlineStack key={index} gap="200" align="start" blockAlign="end" wrap>
          <div style={{ minWidth: '180px', flex: 1 }}>
            <Select
              label="Column"
              labelHidden={index > 0}
              options={columnOptions}
              value={filter.column}
              onChange={(val) => handleColumnChange(index, val)}
            />
          </div>
          <div style={{ minWidth: '150px' }}>
            <Select
              label="Operator"
              labelHidden={index > 0}
              options={OPERATOR_OPTIONS}
              value={filter.operator}
              onChange={(val) => handleOperatorChange(index, val)}
            />
          </div>
          <div style={{ minWidth: '150px', flex: 1 }}>
            <TextField
              label="Value"
              labelHidden={index > 0}
              value={String(filter.value ?? '')}
              onChange={(val) => handleValueChange(index, val)}
              placeholder="Filter value"
              autoComplete="off"
            />
          </div>
          <Button
            variant="plain"
            tone="critical"
            onClick={() => handleRemove(index)}
            accessibilityLabel={`Remove filter ${index + 1}`}
          >
            Remove
          </Button>
        </InlineStack>
      ))}

      <div>
        <Button onClick={handleAdd}>Add filter</Button>
      </div>
    </BlockStack>
  );
}
