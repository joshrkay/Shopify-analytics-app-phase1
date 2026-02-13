import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { LayoutWidgetPlaceholder } from '../components/builder/LayoutWidgetPlaceholder';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

const widget = {
  id: 'w-1',
  name: 'Revenue Widget',
  chart_type: 'bar',
  position_json: { x: 0, y: 0, w: 6, h: 3 },
} as any;

describe('LayoutWidgetPlaceholder', () => {
  it('renders widget title and size label', () => {
    renderWithPolaris(
      <LayoutWidgetPlaceholder widget={widget} onSettings={vi.fn()} onMaximize={vi.fn()} onDelete={vi.fn()} />,
    );

    expect(screen.getByText('Revenue Widget')).toBeInTheDocument();
    expect(screen.getByText('Medium')).toBeInTheDocument();
  });

  it('reveals action buttons on hover and fires callbacks', async () => {
    const user = userEvent.setup();
    const onSettings = vi.fn();
    const onMaximize = vi.fn();
    const onDelete = vi.fn();

    const { container } = renderWithPolaris(
      <LayoutWidgetPlaceholder widget={widget} onSettings={onSettings} onMaximize={onMaximize} onDelete={onDelete} />,
    );

    const placeholder = container.querySelector('.widget-placeholder');
    expect(placeholder).toBeTruthy();
    fireEvent.mouseEnter(placeholder!);

    await user.click(screen.getByRole('button', { name: 'Settings' }));
    await user.click(screen.getByRole('button', { name: 'Maximize' }));
    await user.click(screen.getByRole('button', { name: 'Delete' }));

    expect(onSettings).toHaveBeenCalledTimes(1);
    expect(onMaximize).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
