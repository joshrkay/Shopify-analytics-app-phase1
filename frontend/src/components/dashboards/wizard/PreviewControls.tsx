/**
 * Preview Controls Component
 *
 * Control bar for the preview step with:
 * - Date range selector
 * - Filter placeholder (future feature)
 * - Save as template checkbox
 *
 * Phase 3 - Dashboard Builder Wizard Enhancements
 */

import { InlineStack, Select, Button, Checkbox, Box } from '@shopify/polaris';
import { useDashboardBuilder } from '../../../contexts/DashboardBuilderContext';

export function PreviewControls() {
  const {
    wizardState,
    setPreviewDateRange,
    setSaveAsTemplate,
  } = useDashboardBuilder();

  const dateRangeOptions = [
    { label: 'Last 7 days', value: '7' },
    { label: 'Last 30 days', value: '30' },
    { label: 'Last 90 days', value: '90' },
    { label: 'Custom range', value: 'custom' },
  ];

  return (
    <Box padding="400" background="bg-surface-secondary" borderRadius="200">
      <InlineStack gap="400" align="space-between" blockAlign="center" wrap>
        {/* Left side: Date range and filters */}
        <InlineStack gap="300" wrap>
          <div style={{ minWidth: '180px' }}>
            <Select
              label="Date range"
              labelInline
              options={dateRangeOptions}
              value={wizardState.previewDateRange || '30'}
              onChange={setPreviewDateRange}
            />
          </div>

          {/* Placeholder for filters */}
          <Button variant="plain" disabled>
            Add filter (coming soon)
          </Button>
        </InlineStack>

        {/* Right side: Save as template */}
        <Checkbox
          label="Save as template"
          checked={wizardState.saveAsTemplate || false}
          onChange={setSaveAsTemplate}
        />
      </InlineStack>
    </Box>
  );
}
