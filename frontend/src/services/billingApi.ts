import { API_BASE_URL, createHeadersAsync, handleResponse } from './apiUtils';
import type { BillingInterval, Invoice, PaymentMethod, Subscription, UsageMetrics } from '../types/settingsTypes';

function toTimestamp(dateValue: string): number {
  const timestamp = new Date(dateValue).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}


export async function getSubscription(): Promise<Subscription> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/subscription`, { method: 'GET', headers });
  return handleResponse<Subscription>(response);
}

export async function getInvoices(): Promise<Invoice[]> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/invoices`, { method: 'GET', headers });
  const invoices = await handleResponse<Invoice[]>(response);
  return invoices.slice().sort((a, b) => toTimestamp(b.date) - toTimestamp(a.date));
}

export async function getPaymentMethod(): Promise<PaymentMethod> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/payment-method`, { method: 'GET', headers });
  return handleResponse<PaymentMethod>(response);
}

export async function getUsageMetrics(): Promise<UsageMetrics> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/usage`, { method: 'GET', headers });
  return handleResponse<UsageMetrics>(response);
}

export async function changePlan(planId: string, interval: BillingInterval): Promise<Subscription> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/subscription`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ planId, interval }),
  });
  return handleResponse<Subscription>(response);
}

export async function cancelSubscription(): Promise<{ success: boolean }> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/subscription`, { method: 'DELETE', headers });
  return handleResponse<{ success: boolean }>(response);
}

export async function updatePaymentMethod(token: string): Promise<PaymentMethod> {
  const headers = await createHeadersAsync();
  const response = await fetch(`${API_BASE_URL}/api/billing/payment-method`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ token }),
  });
  return handleResponse<PaymentMethod>(response);
}
