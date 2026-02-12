import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SyncSettingsTab } from '../components/settings/SyncSettingsTab';

vi.mock('../hooks/useSyncConfig', () => ({
  useSyncConfig: vi.fn(),
  useUpdateSyncSchedule: vi.fn(),
  useUpdateDataProcessing: vi.fn(),
  useUpdateStorageConfig: vi.fn(),
  useUpdateErrorHandling: vi.fn(),
}));

import {
  useSyncConfig,
  useUpdateDataProcessing,
  useUpdateErrorHandling,
  useUpdateStorageConfig,
  useUpdateSyncSchedule,
} from '../hooks/useSyncConfig';

const mutateSchedule = vi.fn().mockResolvedValue({});
const mutateData = vi.fn().mockResolvedValue({});
const mutateStorage = vi.fn().mockResolvedValue({});
const mutateError = vi.fn().mockResolvedValue({});

const baseConfig = {
  schedule: { defaultFrequency: 'daily', syncWindow: '24_7', pauseDuringMaintenance: false, customSchedule: { start: '09:00', end: '17:00' } },
  dataProcessing: { currency: 'USD', timezone: 'UTC', dateFormat: 'MM/DD/YYYY', numberFormat: 'comma_dot' },
  storage: { usedGb: 25, limitGb: 100, retentionPolicy: 'all', retentionDays: 365, backupFrequency: 'weekly', lastBackup: '2026-02-11T10:00:00Z' },
  errorHandling: { onFailure: 'retry', retryDelay: '15m', logErrors: true, emailOnCritical: false, showDashboardNotifications: true },
} as const;

describe('SyncSettingsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useSyncConfig).mockReturnValue({ config: baseConfig as never, isLoading: false, error: null, refetch: vi.fn() });
    vi.mocked(useUpdateSyncSchedule).mockReturnValue({ mutateAsync: mutateSchedule, isPending: false, error: null } as never);
    vi.mocked(useUpdateDataProcessing).mockReturnValue({ mutateAsync: mutateData, isPending: false, error: null } as never);
    vi.mocked(useUpdateStorageConfig).mockReturnValue({ mutateAsync: mutateStorage, isPending: false, error: null } as never);
    vi.mocked(useUpdateErrorHandling).mockReturnValue({ mutateAsync: mutateError, isPending: false, error: null } as never);
  });

  describe('Schedule Section', () => {
    it('Renders frequency dropdown with 4 options', () => {
      render(<SyncSettingsTab />);
      const frequency = screen.getByLabelText('Default frequency');
      expect(frequency).toBeInTheDocument();
      expect(within(frequency).getAllByRole('option')).toHaveLength(4);
    });

    it('Renders sync window radio group', () => {
      render(<SyncSettingsTab />);
      expect(screen.getByLabelText('24/7')).toBeInTheDocument();
      expect(screen.getByLabelText('Business hours')).toBeInTheDocument();
      expect(screen.getByLabelText('Custom schedule')).toBeInTheDocument();
    });

    it('Custom schedule inputs visible only when "Custom" selected', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      expect(screen.queryByTestId('custom-schedule-inputs')).not.toBeInTheDocument();
      await act(async () => {
        await user.click(screen.getByLabelText('Custom schedule'));
      });
      expect(screen.getByTestId('custom-schedule-inputs')).toBeInTheDocument();
    });

    it('Maintenance checkbox toggles correctly', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      const checkbox = screen.getByLabelText('Pause syncs during maintenance windows');
      expect(checkbox).not.toBeChecked();
      await act(async () => {
        await user.click(checkbox);
      });
      expect(checkbox).toBeChecked();
    });
  });

  describe('Data Processing Section', () => {
    it('Currency dropdown renders options', () => {
      render(<SyncSettingsTab />);
      expect(screen.getByLabelText('Currency')).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'JPY' })).toBeInTheDocument();
    });

    it('Date format radio group works', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      await act(async () => {
        await user.click(screen.getByLabelText('DD/MM/YYYY'));
      });
      expect(screen.getByLabelText('DD/MM/YYYY')).toBeChecked();
    });

    it('Number format radio group works', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      await act(async () => {
        await user.click(screen.getByLabelText('1.234,56'));
      });
      expect(screen.getByLabelText('1.234,56')).toBeChecked();
    });
  });

  describe('Storage Section', () => {
    it('Usage bar renders correct percentage', () => {
      render(<SyncSettingsTab />);
      expect(screen.getByText('25% used')).toBeInTheDocument();
    });

    it('Retention policy toggle shows/hides days dropdown', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      expect(screen.queryByLabelText('Retention days')).not.toBeInTheDocument();
      await act(async () => {
        await user.click(screen.getByLabelText('Auto-delete after N days'));
      });
      expect(screen.getByLabelText('Retention days')).toBeInTheDocument();
    });

    it('Backup buttons render', () => {
      render(<SyncSettingsTab />);
      expect(screen.getByRole('button', { name: 'Download Backup' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Restore from Backup' })).toBeInTheDocument();
    });
  });

  describe('Error Handling Section', () => {
    it('Failure strategy radio group works', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      await act(async () => {
        await user.click(screen.getByLabelText('Notify & wait'));
      });
      expect(screen.getByLabelText('Notify & wait')).toBeChecked();
    });

    it('Checkboxes toggle independently', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      const logAll = screen.getByLabelText('Log all errors');
      const emailCritical = screen.getByLabelText('Email on critical');
      await act(async () => {
        await user.click(logAll);
        await user.click(emailCritical);
      });
      expect(logAll).not.toBeChecked();
      expect(emailCritical).toBeChecked();
    });
  });

  describe('Form Behavior', () => {
    it('Save calls all 4 update mutations', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      await act(async () => {
        await user.selectOptions(screen.getByLabelText('Default frequency'), '6h');
        await user.click(screen.getByRole('button', { name: 'Save Changes' }));
      });
      expect(mutateSchedule).toHaveBeenCalledTimes(1);
      expect(mutateData).toHaveBeenCalledTimes(1);
      expect(mutateStorage).toHaveBeenCalledTimes(1);
      expect(mutateError).toHaveBeenCalledTimes(1);
    });

    it('Cancel resets form to initial values', async () => {
      const user = userEvent.setup();
      render(<SyncSettingsTab />);
      const frequency = screen.getByLabelText('Default frequency') as HTMLSelectElement;
      await act(async () => {
        await user.selectOptions(frequency, '6h');
      });
      expect(frequency.value).toBe('6h');
      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Cancel' }));
      });
      expect((screen.getByLabelText('Default frequency') as HTMLSelectElement).value).toBe('daily');
    });
  });
});
