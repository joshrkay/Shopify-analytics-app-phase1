import { describe, it, expect, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Settings from '../pages/Settings';

vi.mock('../contexts/AgencyContext', () => ({
  useAgency: vi.fn(),
}));

import { useAgency } from '../contexts/AgencyContext';

const mockedUseAgency = vi.mocked(useAgency);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-search">{location.search}</div>;
}

function renderSettings(initialEntry = '/settings', role: 'viewer' | 'admin' | 'owner' = 'owner') {
  const roleMap = {
    viewer: ['viewer'],
    admin: ['admin'],
    owner: ['owner'],
  };

  mockedUseAgency.mockReturnValue({
    userRoles: roleMap[role],
  } as never);

  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/settings"
          element={(
            <>
              <Settings />
              <LocationProbe />
            </>
          )}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe('Settings page shell and tab navigation', () => {
  describe('Rendering', () => {
    it('Renders all 8 tab buttons in sidebar', async () => {
      renderSettings('/settings', 'owner');
      expect(await screen.findByRole('button', { name: 'Data Sources' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Sync Settings' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Team' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Billing' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'API Keys' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'AI Insights' })).toBeInTheDocument();
    });

    it('Sources tab is active by default', async () => {
      renderSettings('/settings', 'owner');
      const sources = await screen.findByRole('button', { name: 'Data Sources' });
      expect(sources.className).toContain('bg-blue-50');
    });

    it('Renders correct content panel for active tab', async () => {
      renderSettings('/settings?tab=billing', 'owner');
      expect(await screen.findByTestId('settings-panel-billing')).toBeInTheDocument();
    });

    it('Page title shows "Settings"', async () => {
      renderSettings('/settings', 'owner');
      expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    });
  });

  describe('Navigation', () => {
    it('Clicking tab switches active content', async () => {
      const user = userEvent.setup();
      renderSettings('/settings', 'owner');
      await act(async () => {
        await user.click(await screen.findByRole('button', { name: 'Billing' }));
      });
      expect(await screen.findByTestId('settings-panel-billing')).toBeInTheDocument();
    });

    it('URL updates when tab changes (?tab=billing)', async () => {
      const user = userEvent.setup();
      renderSettings('/settings', 'owner');
      await act(async () => {
        await user.click(await screen.findByRole('button', { name: 'Billing' }));
      });
      expect(screen.getByTestId('location-search')).toHaveTextContent('?tab=billing');
    });

    it('Tab from URL params is selected on mount', async () => {
      renderSettings('/settings?tab=team', 'owner');
      expect(await screen.findByTestId('settings-panel-team')).toBeInTheDocument();
    });

    it('Invalid tab param falls back to "sources"', async () => {
      renderSettings('/settings?tab=nope', 'owner');
      expect(await screen.findByTestId('settings-panel-sources')).toBeInTheDocument();
      await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent('?tab=sources'));
    });
  });

  describe('Permission Gating', () => {
    it('Viewer sees sources, notifications, account tabs only', async () => {
      renderSettings('/settings', 'viewer');
      expect(await screen.findByRole('button', { name: 'Data Sources' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Notifications' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Team' })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Billing' })).not.toBeInTheDocument();
    });

    it('Admin sees sources, sync, notifications, account, team, api, ai tabs', async () => {
      renderSettings('/settings', 'admin');
      expect(await screen.findByRole('button', { name: 'Data Sources' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Sync Settings' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Team' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'API Keys' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'AI Insights' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Billing' })).not.toBeInTheDocument();
    });

    it('Owner sees all 8 tabs', async () => {
      renderSettings('/settings', 'owner');
      expect(await screen.findAllByRole('button')).toHaveLength(8);
    });

    it('Hidden tab URL param redirects to first visible tab', async () => {
      renderSettings('/settings?tab=billing', 'viewer');
      expect(await screen.findByTestId('settings-panel-sources')).toBeInTheDocument();
      await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent('?tab=sources'));
    });
  });

  describe('Responsiveness', () => {
    it('Sidebar renders vertically on desktop', async () => {
      renderSettings('/settings', 'owner');
      const tabList = await screen.findByTestId('settings-tab-list');
      expect(tabList.className).toContain('md:flex-col');
    });

    it('Tab labels visible alongside icons', async () => {
      renderSettings('/settings', 'owner');
      const tab = await screen.findByRole('button', { name: 'Data Sources' });
      expect(tab).toHaveTextContent('Data Sources');
    });
  });
});
