/**
 * Tests for TimeframeSelector
 *
 * Phase 1 — Dashboard Home
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import {
  TimeframeSelector,
  getTimeframeDays,
  getTimeframeLabel,
} from '../components/common/TimeframeSelector';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const mockTranslations = {
  Polaris: {
    Common: { ok: 'OK', cancel: 'Cancel' },
  },
};

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <AppProvider i18n={mockTranslations as any}>
      {ui}
    </AppProvider>,
  );
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TimeframeSelector', () => {
  it('renders a select element with default value', () => {
    const onChange = vi.fn();
    renderWithProviders(<TimeframeSelector value="30d" onChange={onChange} />);

    const select = document.querySelector('select') as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe('30d');
  });

  it('shows all 3 timeframe options', () => {
    const onChange = vi.fn();
    renderWithProviders(<TimeframeSelector value="30d" onChange={onChange} />);

    const select = document.querySelector('select') as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(['7d', '30d', '90d']);
  });

  it('calls onChange with selected value', () => {
    const onChange = vi.fn();
    renderWithProviders(<TimeframeSelector value="30d" onChange={onChange} />);

    const select = document.querySelector('select') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '7d' } });

    expect(onChange).toHaveBeenCalledWith('7d');
  });

  it('renders with custom label (hidden by default)', () => {
    const onChange = vi.fn();
    renderWithProviders(<TimeframeSelector value="30d" onChange={onChange} label="Period" />);

    // Label is visually hidden but present for accessibility
    expect(screen.getByLabelText('Period')).toBeInTheDocument();
  });
});

describe('getTimeframeDays', () => {
  it('returns correct days for each option', () => {
    expect(getTimeframeDays('7d')).toBe(7);
    expect(getTimeframeDays('30d')).toBe(30);
    expect(getTimeframeDays('90d')).toBe(90);
  });
});

describe('getTimeframeLabel', () => {
  it('returns correct labels for each option', () => {
    expect(getTimeframeLabel('7d')).toBe('Last 7 days');
    expect(getTimeframeLabel('30d')).toBe('Last 30 days');
    expect(getTimeframeLabel('90d')).toBe('Last 90 days');
  });
});
