import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { LayoutControls } from '../components/builder/LayoutControls';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

describe('LayoutControls', () => {
  it('fires reset and auto arrange callbacks', async () => {
    const user = userEvent.setup();
    const onAutoArrange = vi.fn();
    const onResetLayout = vi.fn();

    renderWithPolaris(
      <LayoutControls onAutoArrange={onAutoArrange} onResetLayout={onResetLayout} />,
    );

    await user.click(screen.getByRole('button', { name: 'Auto Arrange' }));
    await user.click(screen.getByRole('button', { name: 'Reset Layout' }));

    expect(onAutoArrange).toHaveBeenCalledTimes(1);
    expect(onResetLayout).toHaveBeenCalledTimes(1);
  });

  it('disables actions when disabled', () => {
    renderWithPolaris(
      <LayoutControls onAutoArrange={vi.fn()} onResetLayout={vi.fn()} disabled />,
    );

    expect(screen.getByRole('button', { name: 'Auto Arrange' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('button', { name: 'Reset Layout' })).toHaveAttribute('aria-disabled', 'true');
  });
});
