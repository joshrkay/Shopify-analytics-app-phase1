/**
 * DatasetPicker Component
 *
 * Renders a Polaris Select dropdown for choosing a dataset.
 * Used within the ReportConfiguratorModal to select which
 * dataset a report should query against.
 *
 * Phase 3 - Dashboard Builder UI
 */

import { Select } from '@shopify/polaris';
import type { Dataset } from '../../../types/customDashboards';

interface DatasetPickerProps {
  datasets: Dataset[];
  value: string;
  onChange: (datasetName: string) => void;
}

export function DatasetPicker({
  datasets,
  value,
  onChange,
}: DatasetPickerProps) {
  const options = [
    { label: 'Select a dataset', value: '' },
    ...datasets.map((ds) => ({
      label: ds.dataset_name,
      value: ds.dataset_name,
    })),
  ];

  return (
    <Select
      label="Dataset"
      options={options}
      value={value}
      onChange={onChange}
    />
  );
}
