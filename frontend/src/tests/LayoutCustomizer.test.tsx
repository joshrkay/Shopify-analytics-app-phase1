import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { LayoutCustomizer } from '../components/builder/LayoutCustomizer';

const mockTranslations = {
  Polaris: { Common: { ok: 'OK', cancel: 'Cancel' } },
};

const mockUseDashboardBuilder = vi.fn();

vi.mock('../contexts/DashboardBuilderContext', () => ({
  useDashboardBuilder: () => mockUseDashboardBuilder(),
}));

const renderWithPolaris = (ui: React.ReactElement) =>
  render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);

const widget = {
  id: 'w-1',
  name: 'Revenue Widget',
  chart_type: 'bar',
  position_json: { x: 0, y: 0, w: 6, h: 3 },
  config_json: { metrics: [], dimensions: [], filters: [], display: {} },
} as any;

describe('LayoutCustomizer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows empty state and returns to selection', async () => {
    const user = userEvent.setup();
    const setBuilderStep = vi.fn();

    mockUseDashboardBuilder.mockReturnValue({
      wizardState: { selectedWidgets: [] },
      setBuilderStep,
      canProceedToPreview: false,
      updateWizardWidget: vi.fn(),
      openWizardWidgetConfig: vi.fn(),
      removeWizardWidget: vi.fn(),
      bulkUpdateWizardWidgets: vi.fn(),
    });

    renderWithPolaris(<LayoutCustomizer />);

    expect(screen.getByText('No widgets added yet')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '← Back to Widget Selection' }));
    expect(setBuilderStep).toHaveBeenCalledWith('select');
  });

  it('renders widgets and supports preview navigation', async () => {
    const user = userEvent.setup();
    const setBuilderStep = vi.fn();

    mockUseDashboardBuilder.mockReturnValue({
      wizardState: { selectedWidgets: [widget] },
      setBuilderStep,
      canProceedToPreview: true,
      updateWizardWidget: vi.fn(),
      openWizardWidgetConfig: vi.fn(),
      removeWizardWidget: vi.fn(),
      bulkUpdateWizardWidgets: vi.fn(),
    });

    renderWithPolaris(<LayoutCustomizer />);

    expect(screen.getByText('Revenue Widget')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Preview Dashboard/i }));
    expect(setBuilderStep).toHaveBeenCalledWith('preview');
  });

  it('dispatches layout control updates', async () => {
    const user = userEvent.setup();
    const bulkUpdateWizardWidgets = vi.fn();
    const updateWizardWidget = vi.fn();
    const openWizardWidgetConfig = vi.fn();
    const removeWizardWidget = vi.fn();

    mockUseDashboardBuilder.mockReturnValue({
      wizardState: { selectedWidgets: [widget] },
      setBuilderStep: vi.fn(),
      canProceedToPreview: true,
      updateWizardWidget,
      openWizardWidgetConfig,
      removeWizardWidget,
      bulkUpdateWizardWidgets,
    });

    const { container } = renderWithPolaris(<LayoutCustomizer />);

    await user.click(screen.getByRole('button', { name: 'Auto Arrange' }));
    await user.click(screen.getByRole('button', { name: 'Reset Layout' }));

    const placeholder = container.querySelector('.widget-placeholder');
    fireEvent.mouseEnter(placeholder!);
    await user.click(await screen.findByRole('button', { name: 'Settings' }));
    await user.click(screen.getByRole('button', { name: 'Maximize' }));
    await user.click(screen.getByRole('button', { name: 'Delete' }));

    expect(bulkUpdateWizardWidgets).toHaveBeenCalledTimes(2);
    expect(openWizardWidgetConfig).toHaveBeenCalledWith('w-1');
    expect(updateWizardWidget).toHaveBeenCalled();
    expect(removeWizardWidget).toHaveBeenCalledWith('w-1');
  });
});
