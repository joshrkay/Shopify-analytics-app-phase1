/**
 * Preview Controls Component
 *
 * Control bar for the preview step with:
 * - Date range selector
 * - Live data toggle
 * - Refresh preview button
 *
 * Phase 2.6 - Preview Step Live Data Integration
 */

import { InlineStack, Select, Button, Checkbox, Box, Tooltip, Icon, Text } from '@shopify/polaris';
import { RefreshIcon, QuestionCircleIcon } from '@shopify/polaris-icons';

interface PreviewControlsProps {
  dateRange: string;
  onDateRangeChange: (range: string) => void;
  useLiveData: boolean;
  onUseLiveDataChange: (enabled: boolean) => void;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export function PreviewControls({
  dateRange,
  onDateRangeChange,
  useLiveData,
  onUseLiveDataChange,
  onRefresh,
  isRefreshing = false,
}: PreviewControlsProps) {

  const dateRangeOptions = [
    { label: 'Last 7 days', value: '7' },
    { label: 'Last 30 days', value: '30' },
    { label: 'Last 90 days', value: '90' },
  ];

  return (
    <Box padding="400" background="bg-surface-secondary" borderRadius="200">
      <InlineStack gap="400" align="space-between" blockAlign="center" wrap>
        {/* Left side: Date range */}
        <div style={{ minWidth: '180px' }}>
          <Select
            label="Date range"
            labelInline
            options={dateRangeOptions}
            value={dateRange}
            onChange={onDateRangeChange}
          />
        </div>

        {/* Center: Live Data Toggle */}
        <InlineStack gap="200" blockAlign="center">
          <Text as="span" variant="bodyMd">
            Use Live Data
          </Text>
          <Checkbox
            label=""
            checked={useLiveData}
            onChange={onUseLiveDataChange}
          />
          <Tooltip content="Show actual data from your connected sources instead of sample data">
            <Icon source={QuestionCircleIcon} tone="subdued" />
          </Tooltip>
        </InlineStack>

        {/* Right side: Refresh Button (only when live data enabled) */}
        {useLiveData && onRefresh && (
          <Button
            onClick={onRefresh}
            icon={RefreshIcon}
            disabled={isRefreshing}
            loading={isRefreshing}
          >
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
          </Button>
        )}
      </InlineStack>
    </Box>
  );
}
