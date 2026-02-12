import {
  cancelSubscription,
  changePlan,
  getInvoices,
  getPaymentMethod,
  getSubscription,
  getUsageMetrics,
} from '../services/billingApi';
import type { BillingInterval } from '../types/settingsTypes';
import { useMutationLite, useQueryClientLite, useQueryLite } from './queryClientLite';

const BILLING_QUERY_KEYS = {
  subscription: ['settings', 'billing', 'subscription'] as const,
  invoices: ['settings', 'billing', 'invoices'] as const,
  paymentMethod: ['settings', 'billing', 'payment-method'] as const,
  usage: ['settings', 'billing', 'usage'] as const,
  entitlements: ['entitlements'] as const,
};

export function useBilling() {
  const subscriptionQuery = useQueryLite({ queryKey: BILLING_QUERY_KEYS.subscription, queryFn: getSubscription });
  const invoicesQuery = useQueryLite({ queryKey: BILLING_QUERY_KEYS.invoices, queryFn: getInvoices });
  const paymentMethodQuery = useQueryLite({ queryKey: BILLING_QUERY_KEYS.paymentMethod, queryFn: getPaymentMethod });
  const usageQuery = useQueryLite({ queryKey: BILLING_QUERY_KEYS.usage, queryFn: getUsageMetrics });

  const isLoading = subscriptionQuery.isLoading
    || invoicesQuery.isLoading
    || paymentMethodQuery.isLoading
    || usageQuery.isLoading;

  const errorSource = subscriptionQuery.error ?? invoicesQuery.error ?? paymentMethodQuery.error ?? usageQuery.error;

  return {
    subscription: subscriptionQuery.data ?? null,
    invoices: invoicesQuery.data ?? [],
    paymentMethod: paymentMethodQuery.data ?? null,
    usage: usageQuery.data ?? null,
    isLoading,
    error: errorSource instanceof Error ? errorSource.message : null,
    refetch: async () => {
      await Promise.all([
        subscriptionQuery.refetch(),
        invoicesQuery.refetch(),
        paymentMethodQuery.refetch(),
        usageQuery.refetch(),
      ]);
    },
  };
}

export function useChangePlan() {
  const queryClient = useQueryClientLite();

  return useMutationLite({
    mutationFn: ({ planId, interval }: { planId: string; interval: BillingInterval }) => changePlan(planId, interval),
    onSuccess: () => {
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.subscription);
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.invoices);
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.usage);
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.entitlements);
    },
  });
}

export function useCancelSubscription() {
  const queryClient = useQueryClientLite();

  const mutation = useMutationLite({
    mutationFn: (confirmed: boolean) => {
      if (!confirmed) {
        return Promise.reject(new Error('Cancellation must be confirmed before executing.'));
      }
      return cancelSubscription();
    },
    onSuccess: () => {
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.subscription);
      queryClient.invalidateQueries(BILLING_QUERY_KEYS.entitlements);
    },
  });

  return mutation;
}

export { BILLING_QUERY_KEYS };
