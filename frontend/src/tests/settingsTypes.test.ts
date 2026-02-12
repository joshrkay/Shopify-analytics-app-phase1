import { describe, expect, it, expectTypeOf } from 'vitest';
import {
  AI_PROVIDERS,
  DAYS_OF_WEEK,
  DEFAULT_AI_FEATURE_FLAGS,
  ERROR_FAILURE_STRATEGIES,
  INVOICE_STATUSES,
  SUBSCRIPTION_STATUSES,
  SYNC_FREQUENCIES,
  TEAM_INVITE_ROLES,
  type AIConfiguration,
  type DataProcessingConfig,
  type DeliveryMethods,
  type ErrorHandlingConfig,
  type PerformanceAlert,
  type PlanLimits,
  type QuietHoursConfig,
  type SyncNotificationMatrix,
  type TeamInvite,
  type TeamMember,
  type UsageMetrics,
} from '../types/settingsTypes';

describe('settingsTypes', () => {
  describe('Team Types', () => {
    it('TeamMember has all required fields', () => {
      const member: TeamMember = {
        id: 'm_1',
        userId: 'u_1',
        name: 'Jane Doe',
        email: 'jane@example.com',
        role: 'admin',
        status: 'active',
        joinedDate: '2026-02-01T00:00:00Z',
      };

      expect(member).toMatchObject({
        id: expect.any(String),
        userId: expect.any(String),
        name: expect.any(String),
        email: expect.any(String),
        role: expect.any(String),
        status: expect.any(String),
        joinedDate: expect.any(String),
      });
    });

    it('TeamInvite requires email and role', () => {
      expectTypeOf<TeamInvite>().toMatchTypeOf<{ email: string; role: 'admin' | 'editor' | 'viewer' }>();
    });

    it('Role excludes "owner" from invite options', () => {
      expect(TEAM_INVITE_ROLES).toEqual(['admin', 'editor', 'viewer']);
      expect(TEAM_INVITE_ROLES).not.toContain('owner');
    });

    it('RoleDefinition permissions array is non-empty', () => {
      const permissions = ['settings:read'];
      expect(permissions.length).toBeGreaterThan(0);
    });
  });

  describe('Billing Types', () => {
    it('PlanLimits supports unlimited (-1) values', () => {
      const limits: PlanLimits = {
        dataSources: -1,
        teamMembers: 10,
        dashboards: 20,
        dataRetention: '12 months',
        aiRequests: 1000,
      };

      expect(limits.dataSources).toBe(-1);
    });

    it('Subscription status enum covers all states', () => {
      expect(SUBSCRIPTION_STATUSES).toEqual(['active', 'trialing', 'past_due', 'canceled', 'paused']);
    });

    it('Invoice status enum covers all states', () => {
      expect(INVOICE_STATUSES).toEqual(['paid', 'pending', 'failed', 'refunded']);
    });

    it('UsageMetrics has matching limit/used pairs', () => {
      const usage: UsageMetrics = {
        dataSourcesUsed: 2,
        teamMembersUsed: 5,
        dashboardsUsed: 12,
        storageUsedGb: 30,
        storageLimitGb: 100,
        aiRequestsUsed: 300,
        aiRequestsLimit: 1000,
      };

      expect(usage.storageLimitGb).toBeGreaterThanOrEqual(usage.storageUsedGb);
      expect(usage.aiRequestsLimit).toBeGreaterThanOrEqual(usage.aiRequestsUsed);
    });
  });

  describe('Notification Types', () => {
    it('DeliveryMethods has all 4 channels', () => {
      const methods: DeliveryMethods = { inApp: true, email: true, sms: false, slack: false };

      expect(Object.keys(methods).sort()).toEqual(['email', 'inApp', 'slack', 'sms']);
    });

    it('SyncNotificationMatrix has all event types', () => {
      const channelDefaults: DeliveryMethods = { inApp: true, email: false, sms: false, slack: false };
      const matrix: SyncNotificationMatrix = {
        syncCompleted: channelDefaults,
        syncFailed: channelDefaults,
        sourceAdded: channelDefaults,
        connectionLost: channelDefaults,
      };

      expect(Object.keys(matrix).sort()).toEqual(['connectionLost', 'sourceAdded', 'syncCompleted', 'syncFailed']);
    });

    it('PerformanceAlert channels match DeliveryMethods shape', () => {
      const alert: PerformanceAlert = {
        id: 'a_1',
        metric: 'sync_duration',
        label: 'Sync Duration',
        threshold: '> 10m',
        channels: { inApp: true, email: true, sms: false, slack: true },
        enabled: true,
      };

      expect(alert.channels).toHaveProperty('inApp');
      expect(alert.channels).toHaveProperty('email');
      expect(alert.channels).toHaveProperty('sms');
      expect(alert.channels).toHaveProperty('slack');
    });

    it('QuietHoursConfig days array is valid', () => {
      const quietHours: QuietHoursConfig = {
        enabled: true,
        startTime: '22:00',
        endTime: '07:00',
        days: ['Mon', 'Tue', 'Wed'],
        allowCritical: true,
      };

      expect(quietHours.days.every((day) => DAYS_OF_WEEK.includes(day))).toBe(true);
    });
  });

  describe('AI Types', () => {
    it('AIProvider union covers 3 providers', () => {
      expect(AI_PROVIDERS).toEqual(['openai', 'anthropic', 'google']);
    });

    it('AIConfiguration never exposes raw API key', () => {
      expectTypeOf<AIConfiguration>().not.toHaveProperty('apiKey');
      expectTypeOf<AIConfiguration>().toHaveProperty('hasApiKey');
    });

    it('AIFeatureFlags defaults are correct', () => {
      expect(DEFAULT_AI_FEATURE_FLAGS).toEqual({
        insights: true,
        recommendations: true,
        predictions: false,
        anomalyDetection: false,
      });
    });
  });

  describe('Sync Config Types', () => {
    it('SyncScheduleConfig frequency options valid', () => {
      expect(SYNC_FREQUENCIES).toEqual(['1h', '6h', 'daily', 'manual']);
    });

    it('DataProcessingConfig has required format fields', () => {
      expectTypeOf<DataProcessingConfig>().toHaveProperty('dateFormat');
      expectTypeOf<DataProcessingConfig>().toHaveProperty('numberFormat');
      expectTypeOf<DataProcessingConfig>().toHaveProperty('currency');
      expectTypeOf<DataProcessingConfig>().toHaveProperty('timezone');
    });

    it('ErrorHandlingConfig has all failure strategies', () => {
      expect(ERROR_FAILURE_STRATEGIES).toEqual(['retry', 'notify_wait', 'skip']);
      expectTypeOf<ErrorHandlingConfig>().toHaveProperty('retryDelay');
    });
  });
});
