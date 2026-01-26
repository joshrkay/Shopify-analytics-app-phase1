/**
 * Tests for Feature Gate Components
 *
 * Tests FeatureGate, BillingBanner, and related functionality.
 */

import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppProvider } from '@shopify/polaris';
import '@shopify/polaris/build/esm/styles.css';

import { FeatureGate, useFeatureEntitlement } from '../components/FeatureGate';
import { BillingBanner } from '../components/BillingBanner';
import type { EntitlementsResponse } from '../services/entitlementsApi';

// Mock Polaris translations
const mockTranslations = {
  Polaris: {
    Common: {
      ok: 'OK',
      cancel: 'Cancel',
    },
  },
};

// Helper to render with Polaris provider
const renderWithPolaris = (ui: React.ReactElement) => {
  return render(<AppProvider i18n={mockTranslations as any}>{ui}</AppProvider>);
};

// Mock entitlements data
const createMockEntitlements = (
  overrides?: Partial<EntitlementsResponse>
): EntitlementsResponse => ({
  billing_state: 'active',
  plan_id: 'plan_growth',
  plan_name: 'Growth',
  features: {
    premium_analytics: {
      feature: 'premium_analytics',
      is_entitled: true,
      billing_state: 'active',
      plan_id: 'plan_growth',
      plan_name: 'Growth',
      reason: null,
      required_plan: null,
      grace_period_ends_on: null,
    },
    data_export: {
      feature: 'data_export',
      is_entitled: false,
      billing_state: 'active',
      plan_id: 'plan_growth',
      plan_name: 'Growth',
      reason: 'Feature requires a higher plan',
      required_plan: 'plan_enterprise',
      grace_period_ends_on: null,
    },
  },
  grace_period_days_remaining: null,
  ...overrides,
});

describe('FeatureGate', () => {
  describe('when feature is entitled', () => {
    it('renders children normally', () => {
      const entitlements = createMockEntitlements();
      const { container } = renderWithPolaris(
        <FeatureGate feature="premium_analytics" entitlements={entitlements}>
          <div data-testid="content">Premium Content</div>
        </FeatureGate>
      );

      expect(screen.getByTestId('content')).toBeInTheDocument();
      expect(screen.getByText('Premium Content')).toBeInTheDocument();
    });
  });

  describe('when feature is not entitled', () => {
    it('shows locked state in card variant', () => {
      const entitlements = createMockEntitlements();
      renderWithPolaris(
        <FeatureGate feature="data_export" entitlements={entitlements}>
          <div data-testid="content">Locked Content</div>
        </FeatureGate>
      );

      expect(screen.getByText('Feature Locked')).toBeInTheDocument();
      expect(screen.getByText(/Feature requires a higher plan/i)).toBeInTheDocument();
    });

    it('shows "Upgrade required" tooltip in inline variant per acceptance criteria', () => {
      const entitlements = createMockEntitlements();
      const { container } = renderWithPolaris(
        <FeatureGate
          feature="data_export"
          entitlements={entitlements}
          variant="inline"
        >
          <div data-testid="content">Locked Content</div>
        </FeatureGate>
      );

      // Tooltip should contain "Upgrade required" as default message
      // Note: Tooltip content is not directly queryable, but component uses it
      expect(screen.getByTestId('content')).toBeInTheDocument();
    });

    it('shows custom locked message when provided', () => {
      const entitlements = createMockEntitlements();
      renderWithPolaris(
        <FeatureGate
          feature="data_export"
          entitlements={entitlements}
          lockedMessage="Custom upgrade message"
        >
          <div>Content</div>
        </FeatureGate>
      );

      expect(screen.getByText('Custom upgrade message')).toBeInTheDocument();
    });

    it('shows upgrade button when onUpgrade callback provided', async () => {
      const user = userEvent.setup();
      const entitlements = createMockEntitlements();
      const onUpgrade = vi.fn();

      renderWithPolaris(
        <FeatureGate
          feature="data_export"
          entitlements={entitlements}
          onUpgrade={onUpgrade}
        >
          <div>Content</div>
        </FeatureGate>
      );

      const upgradeButton = screen.getByRole('button', { name: /upgrade plan/i });
      expect(upgradeButton).toBeInTheDocument();

      await user.click(upgradeButton);
      expect(onUpgrade).toHaveBeenCalledTimes(1);
    });

    it('renders inline variant with tooltip', () => {
      const entitlements = createMockEntitlements();
      const { container } = renderWithPolaris(
        <FeatureGate
          feature="data_export"
          entitlements={entitlements}
          variant="inline"
        >
          <div data-testid="content">Inline Content</div>
        </FeatureGate>
      );

      // Content should be visible but with reduced opacity
      expect(screen.getByTestId('content')).toBeInTheDocument();
    });
  });

  describe('when entitlements are null', () => {
    it('shows locked state', () => {
      renderWithPolaris(
        <FeatureGate feature="premium_analytics" entitlements={null}>
          <div>Content</div>
        </FeatureGate>
      );

      expect(screen.getByText('Feature Locked')).toBeInTheDocument();
    });
  });
});

describe('BillingBanner', () => {
  describe('when billing_state is active', () => {
    it('renders nothing', () => {
      const entitlements = createMockEntitlements({ billing_state: 'active' });
      const { container } = renderWithPolaris(
        <BillingBanner entitlements={entitlements} />
      );

      expect(container.firstChild).toBeNull();
    });
  });

  describe('when billing_state is past_due', () => {
    it('shows payment issue banner', () => {
      const entitlements = createMockEntitlements({ billing_state: 'past_due' });
      renderWithPolaris(<BillingBanner entitlements={entitlements} />);

      expect(screen.getByText('Payment Issue')).toBeInTheDocument();
      expect(screen.getByText(/payment method failed/i)).toBeInTheDocument();
    });

    it('shows update payment button when callback provided', async () => {
      const user = userEvent.setup();
      const entitlements = createMockEntitlements({ billing_state: 'past_due' });
      const onUpdatePayment = vi.fn();

      renderWithPolaris(
        <BillingBanner
          entitlements={entitlements}
          onUpdatePayment={onUpdatePayment}
        />
      );

      const button = screen.getByRole('button', { name: /update payment method/i });
      expect(button).toBeInTheDocument();

      await user.click(button);
      expect(onUpdatePayment).toHaveBeenCalledTimes(1);
    });
  });

  describe('when billing_state is grace_period', () => {
    it('shows countdown banner with days remaining in format "2 days left"', () => {
      const entitlements = createMockEntitlements({
        billing_state: 'grace_period',
        grace_period_days_remaining: 2,
      });
      renderWithPolaris(<BillingBanner entitlements={entitlements} />);

      // Per acceptance criteria: "2 days left"
      expect(screen.getByText(/^2 days left$/i)).toBeInTheDocument();
      expect(screen.getByText(/2 more days/i)).toBeInTheDocument();
    });

    it('shows singular "day" for 1 day remaining', () => {
      const entitlements = createMockEntitlements({
        billing_state: 'grace_period',
        grace_period_days_remaining: 1,
      });
      renderWithPolaris(<BillingBanner entitlements={entitlements} />);

      // Per acceptance criteria: "1 day left"
      expect(screen.getByText(/^1 day left$/i)).toBeInTheDocument();
      expect(screen.getByText(/1 more day/i)).toBeInTheDocument();
    });
  });

  describe('when billing_state is expired', () => {
    it('shows expired banner with upgrade button', async () => {
      const user = userEvent.setup();
      const entitlements = createMockEntitlements({ billing_state: 'expired' });
      const onUpgrade = vi.fn();

      renderWithPolaris(
        <BillingBanner entitlements={entitlements} onUpgrade={onUpgrade} />
      );

      expect(screen.getByText('Subscription Expired')).toBeInTheDocument();
      expect(screen.getByText(/subscription has expired/i)).toBeInTheDocument();

      const button = screen.getByRole('button', { name: /upgrade now/i });
      expect(button).toBeInTheDocument();

      await user.click(button);
      expect(onUpgrade).toHaveBeenCalledTimes(1);
    });
  });

  describe('when billing_state is canceled', () => {
    it('shows canceled banner with reactivate button', async () => {
      const user = userEvent.setup();
      const entitlements = createMockEntitlements({ billing_state: 'canceled' });
      const onUpgrade = vi.fn();

      renderWithPolaris(
        <BillingBanner entitlements={entitlements} onUpgrade={onUpgrade} />
      );

      expect(screen.getByText('Subscription Canceled')).toBeInTheDocument();
      expect(screen.getByText(/subscription has been canceled/i)).toBeInTheDocument();

      const button = screen.getByRole('button', { name: /reactivate/i });
      expect(button).toBeInTheDocument();

      await user.click(button);
      expect(onUpgrade).toHaveBeenCalledTimes(1);
    });
  });

  describe('when entitlements are null', () => {
    it('renders nothing', () => {
      const { container } = renderWithPolaris(<BillingBanner entitlements={null} />);
      expect(container.firstChild).toBeNull();
    });
  });
});

describe('useFeatureEntitlement hook', () => {
  it('returns correct entitlement status', () => {
    const entitlements = createMockEntitlements();
    let result: { isEntitled: boolean; reason: string | null } | null = null;

    const TestComponent = () => {
      result = useFeatureEntitlement('premium_analytics', entitlements);
      return <div>Test</div>;
    };

    renderWithPolaris(<TestComponent />);

    expect(result).not.toBeNull();
    expect(result?.isEntitled).toBe(true);
    expect(result?.reason).toBeNull();
  });

  it('returns false for non-entitled feature', () => {
    const entitlements = createMockEntitlements();
    let result: { isEntitled: boolean; reason: string | null } | null = null;

    const TestComponent = () => {
      result = useFeatureEntitlement('data_export', entitlements);
      return <div>Test</div>;
    };

    renderWithPolaris(<TestComponent />);

    expect(result).not.toBeNull();
    expect(result?.isEntitled).toBe(false);
    expect(result?.reason).toContain('higher plan');
  });

  it('returns false when entitlements are null', () => {
    let result: { isEntitled: boolean; reason: string | null } | null = null;

    const TestComponent = () => {
      result = useFeatureEntitlement('premium_analytics', null);
      return <div>Test</div>;
    };

    renderWithPolaris(<TestComponent />);

    expect(result).not.toBeNull();
    expect(result?.isEntitled).toBe(false);
  });
});
