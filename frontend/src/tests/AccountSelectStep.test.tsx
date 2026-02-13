/**
 * Tests for AccountSelectStep component
 *
 * Verifies account list rendering, checkbox selection, select/deselect all,
 * disabled state, and empty state.
 *
 * Phase 3 — Subphase 3.4: Connection Wizard Steps 1-3
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { AccountSelectStep } from '../components/sources/steps/AccountSelectStep';
import type { AccountOption } from '../types/sourceConnection';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

const mockAccounts: AccountOption[] = [
  {
    id: 'acc-1',
    accountId: 'act_111',
    accountName: 'Summer Campaign',
    platform: 'meta_ads',
    isEnabled: true,
  },
  {
    id: 'acc-2',
    accountId: 'act_222',
    accountName: 'Winter Sale',
    platform: 'meta_ads',
    isEnabled: false,
  },
];

const defaultProps = {
  accounts: mockAccounts,
  selectedAccountIds: ['acc-1'],
  loading: false,
  error: null,
  onToggleAccount: vi.fn(),
  onSelectAll: vi.fn(),
  onDeselectAll: vi.fn(),
  onConfirm: vi.fn(),
  onBack: vi.fn(),
};

describe('AccountSelectStep', () => {
  it('renders account list with names', () => {
    renderWithPolaris(<AccountSelectStep {...defaultProps} />);

    expect(screen.getByText('Summer Campaign')).toBeInTheDocument();
    expect(screen.getByText('Winter Sale')).toBeInTheDocument();
  });

  it('pre-selects accounts in selectedAccountIds', () => {
    renderWithPolaris(<AccountSelectStep {...defaultProps} />);

    const checkboxes = screen.getAllByRole('checkbox');
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();
  });

  it('calls onToggleAccount when checkbox is toggled', async () => {
    const user = userEvent.setup();
    const onToggleAccount = vi.fn();

    renderWithPolaris(
      <AccountSelectStep {...defaultProps} onToggleAccount={onToggleAccount} />,
    );

    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[1]);
    expect(onToggleAccount).toHaveBeenCalledWith('acc-2');
  });

  it('calls onSelectAll when "Select All" is clicked', async () => {
    const user = userEvent.setup();
    const onSelectAll = vi.fn();

    renderWithPolaris(
      <AccountSelectStep {...defaultProps} onSelectAll={onSelectAll} />,
    );

    await user.click(screen.getByRole('button', { name: /^select all$/i }));
    expect(onSelectAll).toHaveBeenCalled();
  });

  it('calls onDeselectAll when "Deselect All" is clicked', async () => {
    const user = userEvent.setup();
    const onDeselectAll = vi.fn();

    renderWithPolaris(
      <AccountSelectStep {...defaultProps} onDeselectAll={onDeselectAll} />,
    );

    await user.click(screen.getByRole('button', { name: /deselect all/i }));
    expect(onDeselectAll).toHaveBeenCalled();
  });

  it('disables Continue button when no accounts selected', () => {
    renderWithPolaris(
      <AccountSelectStep {...defaultProps} selectedAccountIds={[]} />,
    );

    const connectButton = screen.getByRole('button', { name: /connect/i });
    // Polaris Button sets aria-disabled or disabled attribute
    expect(
      connectButton.hasAttribute('disabled') || connectButton.getAttribute('aria-disabled') === 'true',
    ).toBe(true);
  });

  it('shows empty state when accounts is empty', () => {
    renderWithPolaris(
      <AccountSelectStep {...defaultProps} accounts={[]} />,
    );

    expect(screen.getByText(/no accounts found/i)).toBeInTheDocument();
  });

  it('loading state shows spinner when fetching accounts', () => {
    const { container } = renderWithPolaris(
      <AccountSelectStep {...defaultProps} loading={true} />,
    );

    expect(container.querySelector('[class*="Spinner"]')).toBeTruthy();
  });
});
