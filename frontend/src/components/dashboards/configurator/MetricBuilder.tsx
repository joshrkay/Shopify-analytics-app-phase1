/**
 * MetricBuilder Component
 *
 * Renders a dynamic list of metric configuration rows. Each row allows
 * the user to select a column, aggregation function, and optional label.
 * Rows can be added or removed. Used within the ReportConfiguratorModal.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { BlockStack, InlineStack, Select, TextField, Button, Text } from '@shopify/polaris';
import type { MetricConfig, Aggregation, ColumnMetadata } from '../../../types/customDashboards';

const AGGREGATION_OPTIONS: { label: string; value: Aggregation }[] = [
  { label: 'SUM', value: 'SUM' },
  { label: 'AVG', value: 'AVG' },
  { label: 'COUNT', value: 'COUNT' },
  { label: 'MIN', value: 'MIN' },
  { label: 'MAX', value: 'MAX' },
];

interface MetricBuilderProps {
  metrics: MetricConfig[];
  columns: ColumnMetadata[];
  onChange: (metrics: MetricConfig[]) => void;
}

export function MetricBuilder({
  metrics,
  columns,
  onChange,
}: MetricBuilderProps) {
  const columnOptions = [
    { label: 'Select column', value: '' },
    ...columns.map((col) => ({
      label: col.column_name,
      value: col.column_name,
    })),
  ];

  const handleColumnChange = (index: number, column: string) => {
    const updated = [...metrics];
    updated[index] = { ...updated[index], column };
    onChange(updated);
  };

  const handleAggregationChange = (index: number, aggregation: string) => {
    const updated = [...metrics];
    updated[index] = { ...updated[index], aggregation: aggregation as Aggregation };
    onChange(updated);
  };

  const handleLabelChange = (index: number, label: string) => {
    const updated = [...metrics];
    updated[index] = { ...updated[index], label: label || undefined };
    onChange(updated);
  };

  const handleRemove = (index: number) => {
    const updated = metrics.filter((_, i) => i !== index);
    onChange(updated);
  };

  const handleAdd = () => {
    onChange([
      ...metrics,
      { column: '', aggregation: 'SUM' as Aggregation },
    ]);
  };

  return (
    <BlockStack gap="300">
      <Text as="p" variant="bodyMd" fontWeight="semibold">
        Metrics
      </Text>

      {metrics.map((metric, index) => (
        <InlineStack key={index} gap="200" align="start" blockAlign="end" wrap>
          <div style={{ minWidth: '180px', flex: 1 }}>
            <Select
              label="Column"
              labelHidden={index > 0}
              options={columnOptions}
              value={metric.column}
              onChange={(val) => handleColumnChange(index, val)}
            />
          </div>
          <div style={{ minWidth: '120px' }}>
            <Select
              label="Aggregation"
              labelHidden={index > 0}
              options={AGGREGATION_OPTIONS}
              value={metric.aggregation}
              onChange={(val) => handleAggregationChange(index, val)}
            />
          </div>
          <div style={{ minWidth: '150px', flex: 1 }}>
            <TextField
              label="Label"
              labelHidden={index > 0}
              value={metric.label ?? ''}
              onChange={(val) => handleLabelChange(index, val)}
              placeholder="Optional label"
              autoComplete="off"
            />
          </div>
          <Button
            variant="plain"
            tone="critical"
            onClick={() => handleRemove(index)}
            accessibilityLabel={`Remove metric ${index + 1}`}
          >
            Remove
          </Button>
        </InlineStack>
      ))}

      <div>
        <Button onClick={handleAdd}>Add metric</Button>
      </div>
    </BlockStack>
  );
}
