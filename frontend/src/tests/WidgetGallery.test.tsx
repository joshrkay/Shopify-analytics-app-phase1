import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { WidgetGallery } from '../components/dashboards/wizard/WidgetGallery';
import type { WidgetCatalogItem } from '../types/customDashboards';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

const items: WidgetCatalogItem[] = [
  {
    id: 'widget-1',
    templateId: 'tpl-1',
    name: 'Revenue Trend',
    title: 'Revenue Trend',
    description: 'Revenue over time',
    category: 'line',
    chart_type: 'line',
    default_config: { metrics: [], dimensions: [], filters: [], display: {} as any },
    required_dataset: 'sales_daily',
    defaultSize: 'medium',
  } as any,
];

describe('WidgetGallery', () => {
  it('renders loading state', () => {
    renderWithPolaris(
      <WidgetGallery items={[]} selectedIds={new Set()} onAddWidget={vi.fn()} loading />,
    );

    expect(screen.getByText('Loading widgets...')).toBeInTheDocument();
  });

  it('renders error and allows retry', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    renderWithPolaris(
      <WidgetGallery
        items={[]}
        selectedIds={new Set()}
        onAddWidget={vi.fn()}
        error="Failed to load widget catalog"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText('Failed to load widget catalog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });


  it('renders error without retry button when retry handler is not provided', () => {
    renderWithPolaris(
      <WidgetGallery
        items={[]}
        selectedIds={new Set()}
        onAddWidget={vi.fn()}
        error="Failed to load widget catalog"
      />,
    );

    expect(screen.getByText('Failed to load widget catalog')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('renders cards and add action', async () => {
    const user = userEvent.setup();
    const onAddWidget = vi.fn();

    renderWithPolaris(
      <WidgetGallery items={items} selectedIds={new Set()} onAddWidget={onAddWidget} />,
    );

    expect(screen.getByText('Revenue Trend')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add Widget' }));
    expect(onAddWidget).toHaveBeenCalledWith(items[0]);
  });
});
