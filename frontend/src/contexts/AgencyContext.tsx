/**
 * Agency Context Provider
 *
 * Manages agency user state across the application:
 * - Current active store
 * - List of assigned stores
 * - Store switching functionality
 * - User role and permissions
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import type {
  AssignedStore,
  UserContext,
  UserRole,
  BillingTier,
} from '../types/agency';
import { hasMultiTenantAccess } from '../types/agency';
import {
  fetchAssignedStores,
  fetchUserContext,
} from '../services/agencyApi';
import { refreshTenantToken } from '../utils/auth';

interface AgencyState {
  // User information
  userId: string | null;
  userRoles: UserRole[];
  billingTier: BillingTier;
  isAgencyUser: boolean;

  // Tenant information
  activeTenantId: string | null;
  allowedTenants: string[];
  assignedStores: AssignedStore[];
  accessExpiringAt: string | null;

  // UI state
  loading: boolean;
  error: string | null;
}

interface AgencyContextValue extends AgencyState {
  // Actions
  switchStore: (tenantId: string) => Promise<void>;
  refreshStores: () => Promise<void>;
  getActiveStore: () => AssignedStore | null;
  canAccessStore: (tenantId: string) => boolean;
}

const initialState: AgencyState = {
  userId: null,
  userRoles: [],
  billingTier: 'free' as BillingTier,
  isAgencyUser: false,
  activeTenantId: null,
  allowedTenants: [],
  assignedStores: [],
  accessExpiringAt: null,
  loading: true,
  error: null,
};

const AgencyContext = createContext<AgencyContextValue | null>(null);

interface AgencyProviderProps {
  children: ReactNode;
  /** Initial user context if available (e.g., from JWT decode) */
  initialUserContext?: Partial<UserContext>;
}

export function AgencyProvider({
  children,
  initialUserContext,
}: AgencyProviderProps) {
  const [state, setState] = useState<AgencyState>(() => ({
    ...initialState,
    userId: initialUserContext?.user_id || null,
    userRoles: initialUserContext?.roles || [],
    billingTier: initialUserContext?.billing_tier || ('free' as BillingTier),
    isAgencyUser: initialUserContext?.roles
      ? hasMultiTenantAccess(initialUserContext.roles)
      : false,
    activeTenantId: initialUserContext?.tenant_id || null,
    allowedTenants: initialUserContext?.allowed_tenants || [],
  }));

  // Initialize user context and fetch stores
  const initialize = useCallback(async () => {
    try {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      // Fetch user context from API
      const userContext = await fetchUserContext();

      const isAgency = hasMultiTenantAccess(userContext.roles);

      // If agency user, fetch assigned stores
      let stores: AssignedStore[] = [];
      if (isAgency) {
        const storesResponse = await fetchAssignedStores();
        stores = storesResponse.stores;
      }

      setState({
        userId: userContext.user_id,
        userRoles: userContext.roles,
        billingTier: userContext.billing_tier,
        isAgencyUser: isAgency,
        activeTenantId: userContext.tenant_id,
        allowedTenants: userContext.allowed_tenants,
        assignedStores: stores,
        loading: false,
        error: null,
      });
    } catch (err) {
      console.error('Failed to initialize agency context:', err);
      setState((prev) => ({
        ...prev,
        loading: false,
        error:
          err instanceof Error
            ? err.message
            : 'Failed to initialize user context',
      }));
    }
  }, []);

  useEffect(() => {
    initialize();
  }, [initialize]);

  // Switch active store
  const switchStore = useCallback(
    async (tenantId: string) => {
      if (!state.isAgencyUser) {
        throw new Error('Store switching is only available for agency users');
      }

      if (!state.allowedTenants.includes(tenantId)) {
        throw new Error('Access to this store is not authorized');
      }

      try {
        setState((prev) => ({ ...prev, loading: true, error: null }));

        const response = await refreshTenantToken(tenantId, state.allowedTenants);

        setState((prev) => ({
          ...prev,
          activeTenantId: response.active_tenant_id,
          accessExpiringAt: response.access_expiring_at,
          loading: false,
        }));
      } catch (err) {
        console.error('Failed to switch store:', err);
        setState((prev) => ({
          ...prev,
          loading: false,
          error:
            err instanceof Error ? err.message : 'Failed to switch store',
        }));
        throw err;
      }
    },
    [state.isAgencyUser, state.allowedTenants]
  );

  // Refresh stores list
  const refreshStores = useCallback(async () => {
    if (!state.isAgencyUser) {
      return;
    }

    try {
      setState((prev) => ({ ...prev, loading: true, error: null }));

      const storesResponse = await fetchAssignedStores();

      setState((prev) => ({
        ...prev,
        assignedStores: storesResponse.stores,
        allowedTenants: storesResponse.stores.map((s) => s.tenant_id),
        loading: false,
      }));
    } catch (err) {
      console.error('Failed to refresh stores:', err);
      setState((prev) => ({
        ...prev,
        loading: false,
        error:
          err instanceof Error ? err.message : 'Failed to refresh stores',
      }));
    }
  }, [state.isAgencyUser]);

  // Get active store details
  const getActiveStore = useCallback((): AssignedStore | null => {
    if (!state.activeTenantId) return null;
    return (
      state.assignedStores.find(
        (s) => s.tenant_id === state.activeTenantId
      ) || null
    );
  }, [state.activeTenantId, state.assignedStores]);

  // Check if user can access a store
  const canAccessStore = useCallback(
    (tenantId: string): boolean => {
      return state.allowedTenants.includes(tenantId);
    },
    [state.allowedTenants]
  );

  const value: AgencyContextValue = {
    ...state,
    switchStore,
    refreshStores,
    getActiveStore,
    canAccessStore,
  };

  return (
    <AgencyContext.Provider value={value}>{children}</AgencyContext.Provider>
  );
}

/**
 * Hook to access agency context.
 *
 * Must be used within an AgencyProvider.
 */
export function useAgency(): AgencyContextValue {
  const context = useContext(AgencyContext);
  if (!context) {
    throw new Error('useAgency must be used within an AgencyProvider');
  }
  return context;
}

/**
 * Hook to get only the active store information.
 */
export function useActiveStore(): {
  store: AssignedStore | null;
  tenantId: string | null;
  loading: boolean;
} {
  const { getActiveStore, activeTenantId, loading } = useAgency();
  return {
    store: getActiveStore(),
    tenantId: activeTenantId,
    loading,
  };
}

/**
 * Hook to check if current user is an agency user.
 */
export function useIsAgencyUser(): boolean {
  const { isAgencyUser } = useAgency();
  return isAgencyUser;
}

export default AgencyContext;
