import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { SelectedWidgetsList } from '../components/dashboards/wizard/SelectedWidgetsList';
import type { Report } from '../types/customDashboards';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

const reports: Report[] = [
  {
    id: 'r-1',
    name: 'Revenue KPI',
    chartType: 'kpi',
    config: {
      metrics: [],
      dimensions: [],
      filters: [],
      display: {},
    },
    position: { x: 0, y: 0, w: 3, h: 2 },
    version: 1,
    createdAt: '2025-01-01T00:00:00Z',
    updatedAt: '2025-01-01T00:00:00Z',
  } as any,
];

describe('SelectedWidgetsList', () => {
  it('renders nothing when empty', () => {
    renderWithPolaris(
      <SelectedWidgetsList selectedWidgets={[]} onRemoveWidget={vi.fn()} onContinueToLayout={vi.fn()} />,
    );

    expect(screen.queryByText('Selected widgets')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Continue to Layout →' })).not.toBeInTheDocument();
  });

  it('renders selected widget and remove callback', async () => {
    const user = userEvent.setup();
    const onRemoveWidget = vi.fn();

    renderWithPolaris(
      <SelectedWidgetsList selectedWidgets={reports} onRemoveWidget={onRemoveWidget} />,
    );

    expect(screen.getByText('Revenue KPI')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove Revenue KPI' }));
    expect(onRemoveWidget).toHaveBeenCalledWith('r-1');
  });


  it('falls back to untitled widget label when name is missing', () => {
    renderWithPolaris(
      <SelectedWidgetsList
        selectedWidgets={[{ id: 'r-2', name: '   ' } as any]}
        onRemoveWidget={vi.fn()}
      />,
    );

    expect(screen.getByText('Untitled widget')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove Untitled widget' })).toBeInTheDocument();
  });

  it('shows continue button and callback', async () => {
    const user = userEvent.setup();
    const onContinueToLayout = vi.fn();

    renderWithPolaris(
      <SelectedWidgetsList selectedWidgets={reports} onContinueToLayout={onContinueToLayout} />,
    );

    await user.click(screen.getByRole('button', { name: 'Continue to Layout →' }));
    expect(onContinueToLayout).toHaveBeenCalledTimes(1);
  });
});
