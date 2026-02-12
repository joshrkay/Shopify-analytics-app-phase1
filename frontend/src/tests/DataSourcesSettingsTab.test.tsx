import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DataSourcesSettingsTab } from '../components/settings/DataSourcesSettingsTab';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../hooks/useDataSources', () => ({
  useDataSources: vi.fn(),
}));

import { useDataSources } from '../hooks/useDataSources';

const mockedUseDataSources = vi.mocked(useDataSources);

const sources = [
  { id: 's1', displayName: 'Main Shopify', platform: 'shopify', authType: 'oauth', status: 'active', isEnabled: true, lastSyncAt: '2026-02-01T12:00:00Z', lastSyncStatus: 'success' },
  { id: 's2', displayName: 'Google Ads Prod', platform: 'google_ads', authType: 'oauth', status: 'pending', isEnabled: true, lastSyncAt: null, lastSyncStatus: null },
] as const;

describe('DataSourcesSettingsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedUseDataSources.mockReturnValue({
      sources: [...sources],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
  });

  it('Renders connected source cards from hook data', () => {
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    expect(screen.getAllByTestId('connected-source-card')).toHaveLength(2);
    expect(screen.getByText('Main Shopify')).toBeInTheDocument();
  });

  it('Shows "Add New Data Source" CTA card', () => {
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    expect(screen.getByTestId('add-source-cta')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Browse Integrations/i })).toHaveAttribute('href', '/sources');
  });

  it('Manage button navigates to source detail', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    await act(async () => {
      await user.click(screen.getAllByRole('button', { name: 'Manage' })[0]);
    });
    expect(mockNavigate).toHaveBeenCalledWith('/sources?source=s2');
  });

  it('Disconnect shows confirmation dialog', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><DataSourcesSettingsTab onDisconnect={vi.fn()} /></MemoryRouter>);
    await act(async () => {
      await user.click(screen.getAllByRole('button', { name: 'Disconnect' })[0]);
    });
    expect(screen.getByTestId('disconnect-confirmation')).toBeInTheDocument();
  });

  it('Disconnect confirmation calls disconnect mutation', async () => {
    const user = userEvent.setup();
    const onDisconnect = vi.fn();
    render(<MemoryRouter><DataSourcesSettingsTab onDisconnect={onDisconnect} /></MemoryRouter>);
    await act(async () => {
      await user.click(screen.getAllByRole('button', { name: 'Disconnect' })[0]);
    });
    await act(async () => {
      await user.click(await screen.findByRole('button', { name: 'Confirm Disconnect' }));
    });
    expect(onDisconnect).toHaveBeenCalledWith('s2');
  });

  it('Test button triggers connection test', async () => {
    const user = userEvent.setup();
    const onTest = vi.fn();
    render(<MemoryRouter><DataSourcesSettingsTab onTest={onTest} /></MemoryRouter>);
    await act(async () => {
      await user.click(screen.getAllByRole('button', { name: 'Test' })[1]);
    });
    expect(onTest).toHaveBeenCalledWith('s1');
  });

  it('Empty state when no sources connected', () => {
    mockedUseDataSources.mockReturnValue({ sources: [], isLoading: false, error: null, refetch: vi.fn() });
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    expect(screen.getByTestId('sources-empty-state')).toBeInTheDocument();
  });

  it('Source cards show correct status indicators', () => {
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    expect(screen.getByText('pending')).toBeInTheDocument();
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('Disable test/disconnect actions when endpoints are unavailable', () => {
    render(<MemoryRouter><DataSourcesSettingsTab /></MemoryRouter>);
    const disconnectButtons = screen.getAllByRole('button', { name: 'Disconnect' });
    const testButtons = screen.getAllByRole('button', { name: 'Test' });
    expect(disconnectButtons[0]).toBeDisabled();
    expect(testButtons[0]).toBeDisabled();
  });
});
