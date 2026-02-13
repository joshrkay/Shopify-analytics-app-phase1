import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { CategorySidebar } from '../components/dashboards/wizard/CategorySidebar';
import type { Report } from '../types/customDashboards';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

const widgetCounts = {
  all: 6,
  line: 1,
  bar: 1,
  area: 1,
  pie: 1,
  kpi: 1,
  table: 1,
};

const selectedWidgets: Report[] = [
  {
    id: 'r-1',
    name: 'Revenue Trend',
  } as any,
];

describe('CategorySidebar', () => {
  it('renders all category buttons', () => {
    renderWithPolaris(
      <CategorySidebar
        widgetCounts={widgetCounts as any}
        onSelectCategory={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: /All \(6\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Line Chart \(1\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Bar Chart \(1\)/ })).toBeInTheDocument();
  });

  it('calls onSelectCategory when category is clicked', async () => {
    const user = userEvent.setup();
    const onSelectCategory = vi.fn();

    renderWithPolaris(
      <CategorySidebar
        widgetCounts={widgetCounts as any}
        onSelectCategory={onSelectCategory}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Line Chart \(1\)/ }));
    expect(onSelectCategory).toHaveBeenCalledWith('line');
  });

  it('renders selected widgets section and continue action', async () => {
    const user = userEvent.setup();
    const onContinueToLayout = vi.fn();

    renderWithPolaris(
      <CategorySidebar
        widgetCounts={widgetCounts as any}
        onSelectCategory={vi.fn()}
        selectedWidgets={selectedWidgets}
        onContinueToLayout={onContinueToLayout}
      />,
    );

    expect(screen.getByText('Selected widgets')).toBeInTheDocument();
    expect(screen.getByText('Revenue Trend')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue to Layout →' }));
    expect(onContinueToLayout).toHaveBeenCalledTimes(1);
  });
});
