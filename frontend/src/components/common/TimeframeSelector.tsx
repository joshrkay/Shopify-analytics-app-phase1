/**
 * TimeframeSelector Component
 *
 * Reusable date range selector for dashboard pages.
 * Provides preset ranges (7d, 30d, 90d) and displays the selected range label.
 *
 * Phase 1 — Dashboard Home
 */

import { Select } from '@shopify/polaris';

export type TimeframeOption = '7d' | '30d' | '90d';

interface TimeframeSelectorProps {
  value: TimeframeOption;
  onChange: (value: TimeframeOption) => void;
  label?: string;
}

const TIMEFRAME_OPTIONS = [
  { label: 'Last 7 days', value: '7d' as const },
  { label: 'Last 30 days', value: '30d' as const },
  { label: 'Last 90 days', value: '90d' as const },
];

export function getTimeframeDays(timeframe: TimeframeOption): number {
  const map: Record<TimeframeOption, number> = {
    '7d': 7,
    '30d': 30,
    '90d': 90,
  };
  return map[timeframe];
}

export function getTimeframeLabel(timeframe: TimeframeOption): string {
  const option = TIMEFRAME_OPTIONS.find((o) => o.value === timeframe);
  return option?.label ?? timeframe;
}

export function TimeframeSelector({ value, onChange, label = 'Timeframe' }: TimeframeSelectorProps) {
  return (
    <Select
      label={label}
      labelHidden
      options={TIMEFRAME_OPTIONS}
      value={value}
      onChange={(val) => onChange(val as TimeframeOption)}
    />
  );
}
