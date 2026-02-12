import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent } from 'react';
import {
  useSyncConfig,
  useUpdateDataProcessing,
  useUpdateErrorHandling,
  useUpdateStorageConfig,
  useUpdateSyncSchedule,
} from '../../hooks/useSyncConfig';
import type { SyncConfiguration } from '../../types/settingsTypes';

const TIMEZONES = ['UTC', 'America/New_York', 'Europe/London', 'Asia/Tokyo', 'Australia/Sydney'];

interface SectionProps {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="border border-gray-200 rounded-lg p-4" data-testid={`sync-section-${title.toLowerCase().replace(/\s+/g, '-')}`}>
      <h3 className="font-semibold text-gray-900 mb-3">{title}</h3>
      {children}
    </section>
  );
}

function usagePercent(config: SyncConfiguration): number {
  if (config.storage.limitGb <= 0) return 0;
  return Math.min(100, Math.round((config.storage.usedGb / config.storage.limitGb) * 100));
}

export function SyncSettingsTab() {
  const { config, isLoading, error } = useSyncConfig();
  const updateSchedule = useUpdateSyncSchedule();
  const updateDataProcessing = useUpdateDataProcessing();
  const updateStorageConfig = useUpdateStorageConfig();
  const updateErrorHandling = useUpdateErrorHandling();

  const [form, setForm] = useState<SyncConfiguration | null>(null);

  useEffect(() => {
    if (config) {
      setForm(config);
    }
  }, [config]);

  const isDirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(config),
    [config, form],
  );

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => {
      if (isDirty) {
        event.preventDefault();
        event.returnValue = '';
      }
    };

    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  if (isLoading || !form) {
    if (!isLoading && error) {
      return (
        <div className="rounded border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" data-testid="sync-settings-unavailable">
          Sync configuration endpoints are not available in this backend deployment yet.
        </div>
      );
    }
    return <p className="text-gray-600">Loading sync settings...</p>;
  }

  const onSave = async () => {
    await Promise.all([
      updateSchedule.mutateAsync(form.schedule),
      updateDataProcessing.mutateAsync(form.dataProcessing),
      updateStorageConfig.mutateAsync(form.storage),
      updateErrorHandling.mutateAsync(form.errorHandling),
    ]);
  };

  const onCancel = () => {
    if (config) {
      setForm(config);
    }
  };

  return (
    <section className="space-y-4" data-testid="sync-settings-tab">
      <Section title="Global Sync Schedule">
        <div className="space-y-3">
          <label className="block text-sm">
            Default frequency
            <select
              className="mt-1 w-full border rounded px-3 py-2"
              value={form.schedule.defaultFrequency}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                schedule: { ...prev.schedule, defaultFrequency: event.target.value as SyncConfiguration['schedule']['defaultFrequency'] },
              }) : prev)}
            >
              <option value="1h">Every 1 hour</option>
              <option value="6h">Every 6 hours</option>
              <option value="daily">Daily</option>
              <option value="manual">Manual only</option>
            </select>
          </label>

          <div>
            <p className="text-sm mb-2">Sync window</p>
            {['24_7', 'business_hours', 'custom'].map((window) => (
              <label key={window} className="flex items-center gap-2 text-sm mb-1">
                <input
                  type="radio"
                  name="syncWindow"
                  value={window}
                  checked={form.schedule.syncWindow === window}
                  onChange={(event) => setForm((prev) => prev ? ({
                    ...prev,
                    schedule: { ...prev.schedule, syncWindow: event.target.value as SyncConfiguration['schedule']['syncWindow'] },
                  }) : prev)}
                />
                {window === '24_7' ? '24/7' : window === 'business_hours' ? 'Business hours' : 'Custom schedule'}
              </label>
            ))}
          </div>

          {form.schedule.syncWindow === 'custom' ? (
            <div className="grid grid-cols-2 gap-2" data-testid="custom-schedule-inputs">
              <input
                aria-label="Custom start time"
                type="time"
                value={form.schedule.customSchedule?.start ?? '09:00'}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setForm((prev) => prev ? ({
                  ...prev,
                  schedule: {
                    ...prev.schedule,
                    customSchedule: {
                      start: event.target.value,
                      end: prev.schedule.customSchedule?.end ?? '17:00',
                    },
                  },
                }) : prev)}
                className="border rounded px-3 py-2"
              />
              <input
                aria-label="Custom end time"
                type="time"
                value={form.schedule.customSchedule?.end ?? '17:00'}
                onChange={(event: ChangeEvent<HTMLInputElement>) => setForm((prev) => prev ? ({
                  ...prev,
                  schedule: {
                    ...prev.schedule,
                    customSchedule: {
                      start: prev.schedule.customSchedule?.start ?? '09:00',
                      end: event.target.value,
                    },
                  },
                }) : prev)}
                className="border rounded px-3 py-2"
              />
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.schedule.pauseDuringMaintenance}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                schedule: { ...prev.schedule, pauseDuringMaintenance: event.target.checked },
              }) : prev)}
            />
            Pause syncs during maintenance windows
          </label>
        </div>
      </Section>

      <Section title="Data Processing">
        <div className="space-y-3">
          <label className="block text-sm">
            Currency
            <select
              className="mt-1 w-full border rounded px-3 py-2"
              value={form.dataProcessing.currency}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                dataProcessing: { ...prev.dataProcessing, currency: event.target.value },
              }) : prev)}
            >
              {['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY'].map((currency) => (
                <option key={currency} value={currency}>{currency}</option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            Timezone
            <select
              className="mt-1 w-full border rounded px-3 py-2"
              value={form.dataProcessing.timezone}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                dataProcessing: { ...prev.dataProcessing, timezone: event.target.value },
              }) : prev)}
            >
              {TIMEZONES.map((timezone) => (
                <option key={timezone} value={timezone}>{timezone}</option>
              ))}
            </select>
          </label>

          <div>
            <p className="text-sm mb-1">Date format</p>
            {['MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD'].map((format) => (
              <label key={format} className="flex gap-2 text-sm">
                <input
                  type="radio"
                  name="dateFormat"
                  value={format}
                  checked={form.dataProcessing.dateFormat === format}
                  onChange={(event) => setForm((prev) => prev ? ({
                    ...prev,
                    dataProcessing: { ...prev.dataProcessing, dateFormat: event.target.value as SyncConfiguration['dataProcessing']['dateFormat'] },
                  }) : prev)}
                />
                {format}
              </label>
            ))}
          </div>

          <div>
            <p className="text-sm mb-1">Number format</p>
            <label className="flex gap-2 text-sm">
              <input
                type="radio"
                name="numberFormat"
                value="comma_dot"
                checked={form.dataProcessing.numberFormat === 'comma_dot'}
                onChange={() => setForm((prev) => prev ? ({
                  ...prev,
                  dataProcessing: { ...prev.dataProcessing, numberFormat: 'comma_dot' },
                }) : prev)}
              />
              1,234.56
            </label>
            <label className="flex gap-2 text-sm">
              <input
                type="radio"
                name="numberFormat"
                value="dot_comma"
                checked={form.dataProcessing.numberFormat === 'dot_comma'}
                onChange={() => setForm((prev) => prev ? ({
                  ...prev,
                  dataProcessing: { ...prev.dataProcessing, numberFormat: 'dot_comma' },
                }) : prev)}
              />
              1.234,56
            </label>
          </div>
        </div>
      </Section>

      <Section title="Storage & Retention">
        <div className="space-y-3">
          <p className="text-sm text-gray-700">Current usage: {form.storage.usedGb} GB / {form.storage.limitGb} GB</p>
          <div className="w-full bg-gray-200 rounded h-2" data-testid="usage-bar-track">
            <div className="bg-blue-600 h-2 rounded" style={{ width: `${usagePercent(form)}%` }} data-testid="usage-bar-fill" />
          </div>
          <p className="text-xs text-gray-500">{usagePercent(form)}% used</p>

          <div>
            <label className="flex gap-2 text-sm">
              <input
                type="radio"
                name="retentionPolicy"
                value="all"
                checked={form.storage.retentionPolicy === 'all'}
                onChange={() => setForm((prev) => prev ? ({
                  ...prev,
                  storage: { ...prev.storage, retentionPolicy: 'all' },
                }) : prev)}
              />
              Keep all
            </label>
            <label className="flex gap-2 text-sm">
              <input
                type="radio"
                name="retentionPolicy"
                value="auto_delete"
                checked={form.storage.retentionPolicy === 'auto_delete'}
                onChange={() => setForm((prev) => prev ? ({
                  ...prev,
                  storage: { ...prev.storage, retentionPolicy: 'auto_delete' },
                }) : prev)}
              />
              Auto-delete after N days
            </label>

            {form.storage.retentionPolicy === 'auto_delete' ? (
              <select
                aria-label="Retention days"
                className="mt-2 border rounded px-3 py-2"
                value={form.storage.retentionDays ?? 365}
                onChange={(event) => setForm((prev) => prev ? ({
                  ...prev,
                  storage: { ...prev.storage, retentionDays: Number(event.target.value) },
                }) : prev)}
              >
                {[365, 180, 90].map((days) => (
                  <option key={days} value={days}>{days} days</option>
                ))}
              </select>
            ) : null}
          </div>

          <label className="block text-sm">
            Backup frequency
            <select
              className="mt-1 w-full border rounded px-3 py-2"
              value={form.storage.backupFrequency}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                storage: { ...prev.storage, backupFrequency: event.target.value as SyncConfiguration['storage']['backupFrequency'] },
              }) : prev)}
            >
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>

          <p className="text-sm text-gray-600">Last backup: {form.storage.lastBackup}</p>

          <div className="flex gap-2">
            <button type="button" className="px-3 py-1.5 border rounded text-sm">Download Backup</button>
            <button type="button" className="px-3 py-1.5 border rounded text-sm">Restore from Backup</button>
          </div>
        </div>
      </Section>

      <Section title="Error Handling">
        <div className="space-y-3">
          {[
            ['retry', 'Retry automatically'],
            ['notify_wait', 'Notify & wait'],
            ['skip', 'Skip'],
          ].map(([value, label]) => (
            <label key={value} className="flex gap-2 text-sm">
              <input
                type="radio"
                name="onFailure"
                value={value}
                checked={form.errorHandling.onFailure === value}
                onChange={() => setForm((prev) => prev ? ({
                  ...prev,
                  errorHandling: { ...prev.errorHandling, onFailure: value as SyncConfiguration['errorHandling']['onFailure'] },
                }) : prev)}
              />
              {label}
            </label>
          ))}

          <label className="block text-sm">
            Retry delay
            <select
              className="mt-1 w-full border rounded px-3 py-2"
              value={form.errorHandling.retryDelay}
              onChange={(event) => setForm((prev) => prev ? ({
                ...prev,
                errorHandling: { ...prev.errorHandling, retryDelay: event.target.value as SyncConfiguration['errorHandling']['retryDelay'] },
              }) : prev)}
            >
              <option value="15m">15 min</option>
              <option value="30m">30 min</option>
              <option value="1h">1 hour</option>
            </select>
          </label>

          <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.errorHandling.logErrors} onChange={(event) => setForm((prev) => prev ? ({ ...prev, errorHandling: { ...prev.errorHandling, logErrors: event.target.checked } }) : prev)} />Log all errors</label>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.errorHandling.emailOnCritical} onChange={(event) => setForm((prev) => prev ? ({ ...prev, errorHandling: { ...prev.errorHandling, emailOnCritical: event.target.checked } }) : prev)} />Email on critical</label>
          <label className="flex gap-2 text-sm"><input type="checkbox" checked={form.errorHandling.showDashboardNotifications} onChange={(event) => setForm((prev) => prev ? ({ ...prev, errorHandling: { ...prev.errorHandling, showDashboardNotifications: event.target.checked } }) : prev)} />Dashboard notifications</label>
        </div>
      </Section>

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="px-4 py-2 border rounded">Cancel</button>
        <button type="button" onClick={onSave} className="px-4 py-2 bg-blue-600 text-white rounded" disabled={!isDirty}>Save Changes</button>
      </div>
    </section>
  );
}

export default SyncSettingsTab;
