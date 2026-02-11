/**
 * Tests for ProfileMenu
 *
 * Phase 1 — Header & ProfileSwitcher
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import { MemoryRouter } from 'react-router-dom';
import '@shopify/polaris/build/esm/styles.css';

import { ProfileMenu } from '../components/layout/ProfileMenu';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

const mockSignOut = vi.fn().mockResolvedValue(undefined);

vi.mock('@clerk/clerk-react', () => ({
  useUser: () => ({
    user: {
      fullName: 'Jane Doe',
      firstName: 'Jane',
      primaryEmailAddress: { emailAddress: 'jane@example.com' },
    },
  }),
  useClerk: () => ({ signOut: mockSignOut }),
}));

vi.mock('../contexts/AgencyContext', () => ({
  useAgency: () => ({
    getActiveStore: () => ({ store_name: 'Test Store' }),
    isAgencyUser: true,
  }),
}));

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
      <MemoryRouter>
        {ui}
      </MemoryRouter>
    </AppProvider>,
  );
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProfileMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders user display name in activator', () => {
    renderWithProviders(<ProfileMenu />);

    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
  });

  it('renders avatar with initial letter', () => {
    renderWithProviders(<ProfileMenu />);

    expect(screen.getByText('J')).toBeInTheDocument();
  });

  it('activator has correct aria-label', () => {
    renderWithProviders(<ProfileMenu />);

    expect(screen.getByLabelText('Profile menu for Jane Doe')).toBeInTheDocument();
  });

  it('click opens popover with email', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileMenu />);

    // Click the activator button
    await user.click(screen.getByLabelText('Profile menu for Jane Doe'));

    // Email should be visible in the popover
    expect(screen.getByText('jane@example.com')).toBeInTheDocument();
  });

  it('shows workspace name in popover', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileMenu />);

    await user.click(screen.getByLabelText('Profile menu for Jane Doe'));

    expect(screen.getByText('Test Store')).toBeInTheDocument();
  });

  it('shows Settings and Sign out actions', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileMenu />);

    await user.click(screen.getByLabelText('Profile menu for Jane Doe'));

    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('Sign out')).toBeInTheDocument();
  });

  it('Settings action navigates to /settings', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileMenu />);

    await user.click(screen.getByLabelText('Profile menu for Jane Doe'));
    await user.click(screen.getByText('Settings'));

    expect(mockNavigate).toHaveBeenCalledWith('/settings');
  });

  it('Sign out action calls Clerk signOut', async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfileMenu />);

    await user.click(screen.getByLabelText('Profile menu for Jane Doe'));
    await user.click(screen.getByText('Sign out'));

    expect(mockSignOut).toHaveBeenCalled();
  });
});
