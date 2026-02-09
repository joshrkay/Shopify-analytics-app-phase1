/**
 * Agency Store Selector Component
 *
 * Allows agency users to switch between assigned client stores.
 * Updates JWT context when store is switched for proper tenant isolation.
 *
 * Features:
 * - Dropdown selector for assigned stores
 * - Visual indicator of active store
 * - Loading states during store switch
 * - Error handling with retry option
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Select,
  Banner,
  Spinner,
  Text,
  InlineStack,
  Box,
  Badge,
} from '@shopify/polaris';
import type { AssignedStore, AssignedStoresResponse } from '../types/agency';
import { fetchAssignedStores } from '../services/agencyApi';
import { refreshTenantToken } from '../utils/auth';

interface AgencyStoreSelectorProps {
  /** Current user ID */
  userId: string;
  /** Callback when store is changed */
  onStoreChange: (tenantId: string, store: AssignedStore) => void;
  /** Whether to show the selector (only for agency users) */
  isAgencyUser: boolean;
  /** Initial active tenant ID */
  initialTenantId?: string;
}

interface StoreSelectorState {
  stores: AssignedStore[];
  selectedTenantId: string | null;
  loading: boolean;
  switching: boolean;
  error: string | null;
  maxStoresAllowed: number;
  accessExpiringAt: string | null;
}

export function AgencyStoreSelector({
  userId: _userId,
  onStoreChange,
  isAgencyUser,
  initialTenantId,
}: AgencyStoreSelectorProps) {
  const [state, setState] = useState<StoreSelectorState>({
    stores: [],
    selectedTenantId: initialTenantId || null,
    loading: true,
    switching: false,
    error: null,
    maxStoresAllowed: 0,
    accessExpiringAt: null,
  });

  // Fetch assigned stores on mount
  const fetchStores = useCallback(async () => {
    if (!isAgencyUser) {
      setState((prev) => ({ ...prev, loading: false }));
      return;
    }

    try {
      setState((prev) => ({ ...prev, loading: true, error: null }));
      const response: AssignedStoresResponse = await fetchAssignedStores();

      setState((prev) => ({
        ...prev,
        stores: response.stores,
        selectedTenantId: response.active_tenant_id || prev.selectedTenantId,
        maxStoresAllowed: response.max_stores_allowed,
        loading: false,
      }));

      // Notify parent of initial store if available
      if (response.stores.length > 0) {
        const activeStore =
          response.stores.find(
            (s) => s.tenant_id === response.active_tenant_id
          ) || response.stores[0];
        onStoreChange(activeStore.tenant_id, activeStore);
      }
    } catch (err) {
      console.error('Failed to fetch assigned stores:', err);
      setState((prev) => ({
        ...prev,
        loading: false,
        error:
          err instanceof Error ? err.message : 'Failed to load assigned stores',
      }));
    }
  }, [isAgencyUser, onStoreChange]);

  useEffect(() => {
    fetchStores();
  }, [fetchStores]);

  // Handle store selection change
  const handleStoreChange = useCallback(
    async (tenantId: string) => {
      if (!tenantId || tenantId === state.selectedTenantId) {
        return;
      }

      try {
        setState((prev) => ({ ...prev, switching: true, error: null }));

        const response = await refreshTenantToken(
          tenantId,
          state.stores.map((s) => s.tenant_id),
        );

        setState((prev) => ({
          ...prev,
          selectedTenantId: response.active_tenant_id,
          accessExpiringAt: response.access_expiring_at,
          switching: false,
        }));

        // Notify parent of store change
        const store = state.stores.find(
          (s) => s.tenant_id === response.active_tenant_id,
        );
        if (store) {
          onStoreChange(response.active_tenant_id, store);
        }
      } catch (err) {
        console.error('Failed to switch store:', err);
        setState((prev) => ({
          ...prev,
          switching: false,
          error:
            err instanceof Error
              ? err.message
              : 'Failed to switch store. Please try again.',
        }));
      }
    },
    [state.selectedTenantId, onStoreChange]
  );

  // Don't render anything for non-agency users
  if (!isAgencyUser) {
    return null;
  }

  // Loading state
  if (state.loading) {
    return (
      <Box padding="400">
        <InlineStack gap="200" align="center">
          <Spinner size="small" />
          <Text as="span" variant="bodySm">
            Loading stores...
          </Text>
        </InlineStack>
      </Box>
    );
  }

  // Error state with retry option
  if (state.error) {
    return (
      <Box padding="400">
        <Banner
          title="Error loading stores"
          tone="critical"
          action={{ content: 'Retry', onAction: fetchStores }}
        >
          <p>{state.error}</p>
        </Banner>
      </Box>
    );
  }

  // No stores assigned
  if (state.stores.length === 0) {
    return (
      <Box padding="400">
        <Banner title="No stores assigned" tone="warning">
          <p>
            You don't have any client stores assigned yet. Contact your
            administrator to get access to stores.
          </p>
        </Banner>
      </Box>
    );
  }

  // Build select options
  const storeOptions = state.stores.map((store) => ({
    label: `${store.store_name} (${store.shop_domain})`,
    value: store.tenant_id,
    disabled: store.status !== 'active',
  }));

  // Get current store info
  const currentStore = state.stores.find(
    (s) => s.tenant_id === state.selectedTenantId
  );

  return (
    <Box padding="400">
      {state.accessExpiringAt && (
        <Box paddingBlockEnd="300">
          <Banner title="Access expiring soon" tone="warning">
            <p>
              Your access to this store expires at{' '}
              {new Date(state.accessExpiringAt).toLocaleString()}.
              Contact your administrator to maintain access.
            </p>
          </Banner>
        </Box>
      )}
      <InlineStack gap="400" align="center" blockAlign="center">
        <Text as="span" variant="bodyMd" fontWeight="semibold">
          Client Store:
        </Text>

        <div style={{ minWidth: '250px' }}>
          <Select
            label="Select client store"
            labelHidden
            options={storeOptions}
            value={state.selectedTenantId || ''}
            onChange={handleStoreChange}
            disabled={state.switching}
          />
        </div>

        {state.switching && <Spinner size="small" />}

        {currentStore && (
          <Badge
            tone={currentStore.status === 'active' ? 'success' : 'warning'}
          >
            {currentStore.status}
          </Badge>
        )}

        <Text as="span" variant="bodySm" tone="subdued">
          {state.stores.length} of {state.maxStoresAllowed} stores
        </Text>
      </InlineStack>
    </Box>
  );
}

export default AgencyStoreSelector;
