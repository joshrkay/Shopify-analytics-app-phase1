// Settings domain type definitions for Phase 4

// ─── Team Domain ──────────────────────────────────────────────────────────────
export const TEAM_MEMBER_ROLES = ['owner', 'admin', 'editor', 'viewer'] as const;
export type TeamMemberRole = (typeof TEAM_MEMBER_ROLES)[number];

export const TEAM_INVITE_ROLES = ['admin', 'editor', 'viewer'] as const;
export type TeamInviteRole = (typeof TEAM_INVITE_ROLES)[number];

export const TEAM_MEMBER_STATUSES = ['active', 'pending', 'deactivated'] as const;
export type TeamMemberStatus = (typeof TEAM_MEMBER_STATUSES)[number];

export interface TeamMember {
  id: string;
  userId: string;
  name: string;
  email: string;
  role: TeamMemberRole;
  status: TeamMemberStatus;
  avatarUrl?: string;
  joinedDate: string;
  lastActiveDate?: string;
}

export interface TeamInvite {
  email: string;
  role: TeamInviteRole;
  message?: string;
}

export interface RoleDefinition {
  id: string;
  name: string;
  permissions: string[];
  isDefault?: boolean;
}

// ─── Billing Domain ───────────────────────────────────────────────────────────
export const BILLING_INTERVALS = ['month', 'year'] as const;
export type BillingInterval = (typeof BILLING_INTERVALS)[number];

export interface PlanLimits {
  dataSources: number; // -1 = unlimited
  teamMembers: number;
  dashboards: number;
  dataRetention: string;
  aiRequests: number;
}

export interface BillingPlan {
  id: string;
  name: string;
  price: number;
  interval: BillingInterval;
  features: string[];
  limits: PlanLimits;
  popular?: boolean;
}

export const SUBSCRIPTION_STATUSES = ['active', 'trialing', 'past_due', 'canceled', 'paused'] as const;
export type SubscriptionStatus = (typeof SUBSCRIPTION_STATUSES)[number];

export interface Subscription {
  id: string;
  planId: string;
  status: SubscriptionStatus;
  currentPeriodEnd: string;
  cancelAtPeriodEnd: boolean;
}

export const INVOICE_STATUSES = ['paid', 'pending', 'failed', 'refunded'] as const;
export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

export interface Invoice {
  id: string;
  date: string;
  amount: string;
  status: InvoiceStatus;
  downloadUrl?: string;
}

export const PAYMENT_METHOD_TYPES = ['card', 'bank'] as const;
export type PaymentMethodType = (typeof PAYMENT_METHOD_TYPES)[number];

export interface PaymentMethod {
  id: string;
  type: PaymentMethodType;
  last4: string;
  brand?: string;
  expiryMonth: number;
  expiryYear: number;
}

export interface UsageMetrics {
  dataSourcesUsed: number;
  teamMembersUsed: number;
  dashboardsUsed: number;
  storageUsedGb: number;
  storageLimitGb: number;
  aiRequestsUsed: number;
  aiRequestsLimit: number;
}

// ─── Notification Domain ──────────────────────────────────────────────────────
export interface DeliveryMethods {
  inApp: boolean;
  email: boolean;
  sms: boolean;
  slack: boolean;
}

export interface SyncNotificationMatrix {
  syncCompleted: DeliveryMethods;
  syncFailed: DeliveryMethods;
  sourceAdded: DeliveryMethods;
  connectionLost: DeliveryMethods;
}

export interface PerformanceAlert {
  id: string;
  metric: string;
  label: string;
  threshold: string;
  channels: DeliveryMethods;
  enabled: boolean;
}

export const REPORT_FREQUENCIES = ['daily', 'weekly', 'monthly'] as const;
export type ReportFrequency = (typeof REPORT_FREQUENCIES)[number];

export interface ReportSchedule {
  id: string;
  name: string;
  frequency: ReportFrequency;
  time: string;
  enabled: boolean;
}

export const DAYS_OF_WEEK = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;
export type DayOfWeek = (typeof DAYS_OF_WEEK)[number];

export interface QuietHoursConfig {
  enabled: boolean;
  startTime: string;
  endTime: string;
  days: DayOfWeek[];
  allowCritical: boolean;
}

export interface NotificationPreferences {
  deliveryMethods: DeliveryMethods;
  syncNotifications: SyncNotificationMatrix;
  performanceAlerts: PerformanceAlert[];
  reportSchedules: ReportSchedule[];
  quietHours: QuietHoursConfig;
}

// ─── AI / LLM Domain ──────────────────────────────────────────────────────────
export const AI_PROVIDERS = ['openai', 'anthropic', 'google'] as const;
export type AIProvider = (typeof AI_PROVIDERS)[number];

export interface AIProviderConfig {
  id: AIProvider;
  name: string;
  description: string;
  docsUrl: string;
  keyFormat: string;
  logo: string;
}

export const AI_CONNECTION_STATUSES = ['connected', 'disconnected', 'error'] as const;
export type AIConnectionStatus = (typeof AI_CONNECTION_STATUSES)[number];

export interface AIFeatureFlags {
  insights: boolean;
  recommendations: boolean;
  predictions: boolean;
  anomalyDetection: boolean;
}

export const DEFAULT_AI_FEATURE_FLAGS: AIFeatureFlags = {
  insights: true,
  recommendations: true,
  predictions: false,
  anomalyDetection: false,
};

export interface AIConfiguration {
  provider: AIProvider;
  hasApiKey: boolean; // never expose raw key to frontend
  connectionStatus: AIConnectionStatus;
  enabledFeatures: AIFeatureFlags;
}

export interface AIUsageStats {
  requestsThisMonth: number;
  requestsLimit: number;
  insightsGenerated: number;
  recommendationsGenerated: number;
  predictionsGenerated: number;
}

// ─── Sync Config Domain ───────────────────────────────────────────────────────
export const SYNC_FREQUENCIES = ['1h', '6h', 'daily', 'manual'] as const;
export type SyncFrequency = (typeof SYNC_FREQUENCIES)[number];

export const SYNC_WINDOWS = ['24_7', 'business_hours', 'custom'] as const;
export type SyncWindow = (typeof SYNC_WINDOWS)[number];

export interface SyncScheduleConfig {
  defaultFrequency: SyncFrequency;
  syncWindow: SyncWindow;
  customSchedule?: { start: string; end: string };
  pauseDuringMaintenance: boolean;
}

export const DATE_FORMATS = ['MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD'] as const;
export type DateFormat = (typeof DATE_FORMATS)[number];

export const NUMBER_FORMATS = ['comma_dot', 'dot_comma'] as const;
export type NumberFormat = (typeof NUMBER_FORMATS)[number];

export interface DataProcessingConfig {
  currency: string;
  timezone: string;
  dateFormat: DateFormat;
  numberFormat: NumberFormat;
}

export const RETENTION_POLICIES = ['all', 'auto_delete'] as const;
export type RetentionPolicy = (typeof RETENTION_POLICIES)[number];

export const BACKUP_FREQUENCIES = ['daily', 'weekly', 'monthly'] as const;
export type BackupFrequency = (typeof BACKUP_FREQUENCIES)[number];

export interface StorageConfig {
  usedGb: number;
  limitGb: number;
  retentionPolicy: RetentionPolicy;
  retentionDays?: number;
  backupFrequency: BackupFrequency;
  lastBackup: string;
}

export const ERROR_FAILURE_STRATEGIES = ['retry', 'notify_wait', 'skip'] as const;
export type ErrorFailureStrategy = (typeof ERROR_FAILURE_STRATEGIES)[number];

export const RETRY_DELAYS = ['15m', '30m', '1h'] as const;
export type RetryDelay = (typeof RETRY_DELAYS)[number];

export interface ErrorHandlingConfig {
  onFailure: ErrorFailureStrategy;
  retryDelay: RetryDelay;
  logErrors: boolean;
  emailOnCritical: boolean;
  showDashboardNotifications: boolean;
}

export interface SyncConfiguration {
  schedule: SyncScheduleConfig;
  dataProcessing: DataProcessingConfig;
  storage: StorageConfig;
  errorHandling: ErrorHandlingConfig;
}

// ─── Account Domain ───────────────────────────────────────────────────────────
export interface AccountProfile {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
  timezone: string;
}

// ─── API Keys Domain ──────────────────────────────────────────────────────────
export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  lastUsed?: string;
  createdAt: string;
  expiresAt?: string;
  scopes: string[];
}

// ─── Settings Tab Navigation ──────────────────────────────────────────────────
export const SETTINGS_TABS = ['sources', 'sync', 'notifications', 'account', 'team', 'billing', 'api', 'ai'] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
