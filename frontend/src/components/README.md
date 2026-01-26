# Feature Entitlement Components

React components for enforcing feature entitlements in the UI based on server-provided billing state.

## Components

### FeatureGate

Wraps content that requires a specific feature entitlement. Shows locked state when feature is not entitled.

```tsx
import { FeatureGate } from '../components';
import { fetchEntitlements } from '../services/entitlementsApi';

function MyComponent() {
  const [entitlements, setEntitlements] = useState(null);

  useEffect(() => {
    fetchEntitlements().then(setEntitlements);
  }, []);

  return (
    <FeatureGate
      feature="premium_analytics"
      entitlements={entitlements}
      onUpgrade={() => navigate('/paywall')}
    >
      <PremiumAnalyticsDashboard />
    </FeatureGate>
  );
}
```

**Props:**
- `feature` (string): Feature key to check
- `entitlements` (EntitlementsResponse | null): Current entitlements
- `children` (ReactNode): Content to show when entitled
- `lockedMessage` (string, optional): Custom message when locked
- `onUpgrade` (() => void, optional): Callback for upgrade button
- `variant` ('card' | 'inline', optional): Display variant

### BillingBanner

Displays banners for different billing states (past_due, grace_period, expired, canceled).

```tsx
import { BillingBanner } from '../components';

function MyPage() {
  const [entitlements, setEntitlements] = useState(null);

  return (
    <Page>
      <BillingBanner
        entitlements={entitlements}
        onUpgrade={() => navigate('/paywall')}
        onUpdatePayment={() => navigate('/billing')}
      />
      {/* Page content */}
    </Page>
  );
}
```

**Props:**
- `entitlements` (EntitlementsResponse | null): Current entitlements
- `onUpgrade` (() => void, optional): Callback for upgrade button
- `onUpdatePayment` (() => void, optional): Callback for payment update button

### Paywall

Full-screen paywall page shown when subscription is expired or canceled.

Route: `/paywall`

## Usage Example

```tsx
import { useState, useEffect } from 'react';
import { Page, Layout } from '@shopify/polaris';
import { FeatureGate, BillingBanner } from '../components';
import { fetchEntitlements } from '../services/entitlementsApi';
import type { EntitlementsResponse } from '../services/entitlementsApi';

function AnalyticsPage() {
  const [entitlements, setEntitlements] = useState<EntitlementsResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchEntitlements()
      .then(setEntitlements)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Redirect to paywall if expired
  if (entitlements?.billing_state === 'expired') {
    navigate('/paywall');
    return null;
  }

  return (
    <Page title="Analytics">
      <Layout>
        <Layout.Section>
          <BillingBanner
            entitlements={entitlements}
            onUpgrade={() => navigate('/paywall')}
          />
        </Layout.Section>
        <Layout.Section>
          <FeatureGate
            feature="premium_analytics"
            entitlements={entitlements}
            onUpgrade={() => navigate('/paywall')}
          >
            <PremiumDashboard />
          </FeatureGate>
        </Layout.Section>
      </Layout>
    </Page>
  );
}
```

## API

The components use the `/api/billing/entitlements` endpoint which returns:

```typescript
{
  billing_state: 'active' | 'past_due' | 'grace_period' | 'canceled' | 'expired' | 'none';
  plan_id: string | null;
  plan_name: string | null;
  features: {
    [featureKey: string]: {
      feature: string;
      is_entitled: boolean;
      billing_state: string;
      plan_id: string | null;
      plan_name: string | null;
      reason: string | null;
      required_plan: string | null;
      grace_period_ends_on: string | null;
    };
  };
  grace_period_days_remaining: number | null;
}
```
