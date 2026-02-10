/**
 * FilterBar Component
 *
 * Renders dashboard-level filters from filters_json.
 * When filters change, calls onFilterChange with the updated active filters
 * so the parent can trigger per-chart re-fetches.
 *
 * Supports date_range, select, and multi_select filter types.
 * Hidden during printing via dashboard-filter-bar CSS class.
 *
 * Phase 3D - Dashboard View Page
 */

import { useState, useCallback } from 'react';
import {
  Card,
  InlineStack,
  Select,
  TextField,
  Tag,
  BlockStack,
  Text,
  Button,
} from '@shopify/polaris';
import type { DashboardFilter } from '../../types/customDashboards';

export interface ActiveFilter {
  column: string;
  value: unknown;
  dataset_names: string[];
}

interface FilterBarProps {
  filters: DashboardFilter[];
  onFilterChange: (activeFilters: ActiveFilter[]) => void;
}

export function FilterBar({ filters, onFilterChange }: FilterBarProps) {
  const [filterValues, setFilterValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const f of filters) {
      initial[f.column] = f.default_value ?? '';
    }
    return initial;
  });

  const handleChange = useCallback(
    (column: string, _datasetNames: string[], value: unknown) => {
      const updated = { ...filterValues, [column]: value };
      setFilterValues(updated);

      const activeFilters: ActiveFilter[] = filters
        .filter((f) => updated[f.column] !== '' && updated[f.column] != null)
        .map((f) => ({
          column: f.column,
          value: updated[f.column],
          dataset_names: f.dataset_names,
        }));
      onFilterChange(activeFilters);
    },
    [filterValues, filters, onFilterChange],
  );

  const handleClear = useCallback(() => {
    const cleared: Record<string, unknown> = {};
    for (const f of filters) {
      cleared[f.column] = '';
    }
    setFilterValues(cleared);
    onFilterChange([]);
  }, [filters, onFilterChange]);

  if (filters.length === 0) return null;

  return (
    <div className="dashboard-filter-bar">
      <Card padding="300">
        <BlockStack gap="200">
          <InlineStack align="space-between" blockAlign="center">
            <Text as="h3" variant="headingSm">
              Filters
            </Text>
            <Button variant="plain" onClick={handleClear}>
              Clear all
            </Button>
          </InlineStack>
          <InlineStack gap="300" wrap>
            {filters.map((filter) => (
              <div key={filter.column} style={{ minWidth: '180px' }}>
                {filter.filter_type === 'date_range' && (
                  <TextField
                    label={filter.column}
                    type="date"
                    value={String(filterValues[filter.column] ?? '')}
                    onChange={(val) =>
                      handleChange(filter.column, filter.dataset_names, val)
                    }
                    autoComplete="off"
                  />
                )}
                {filter.filter_type === 'select' && (
                  <Select
                    label={filter.column}
                    options={[
                      { label: 'All', value: '' },
                      ...(Array.isArray(filter.default_value)
                        ? (filter.default_value as string[]).map((v) => ({
                            label: String(v),
                            value: String(v),
                          }))
                        : []),
                    ]}
                    value={String(filterValues[filter.column] ?? '')}
                    onChange={(val) =>
                      handleChange(filter.column, filter.dataset_names, val)
                    }
                  />
                )}
                {filter.filter_type === 'multi_select' && (
                  <BlockStack gap="100">
                    <Text as="span" variant="bodySm">
                      {filter.column}
                    </Text>
                    <InlineStack gap="100">
                      {Array.isArray(filterValues[filter.column])
                        ? (filterValues[filter.column] as string[]).map((v) => (
                            <Tag
                              key={v}
                              onRemove={() => {
                                const current = filterValues[filter.column] as string[];
                                handleChange(
                                  filter.column,
                                  filter.dataset_names,
                                  current.filter((item) => item !== v),
                                );
                              }}
                            >
                              {v}
                            </Tag>
                          ))
                        : null}
                    </InlineStack>
                  </BlockStack>
                )}
              </div>
            ))}
          </InlineStack>
        </BlockStack>
      </Card>
    </div>
  );
}
