import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useDataSources } from '../../hooks/useDataSources';
import type { Source, SourceStatus } from '../../types/sources';

function statusClass(status: SourceStatus) {
  switch (status) {
    case 'active':
      return 'bg-green-100 text-green-700';
    case 'pending':
      return 'bg-yellow-100 text-yellow-700';
    case 'failed':
      return 'bg-red-100 text-red-700';
    default:
      return 'bg-gray-100 text-gray-700';
  }
}

interface DataSourcesSettingsTabProps {
  onDisconnect?: (sourceId: string) => Promise<void> | void;
  onTest?: (sourceId: string) => Promise<void> | void;
}

export function DataSourcesSettingsTab({ onDisconnect, onTest }: DataSourcesSettingsTabProps) {
  const navigate = useNavigate();
  const { sources, isLoading } = useDataSources();
  const [confirmSourceId, setConfirmSourceId] = useState<string | null>(null);

  const sortedSources = useMemo(
    () => sources.slice().sort((a, b) => a.displayName.localeCompare(b.displayName)),
    [sources],
  );

  const handleDisconnect = async (source: Source) => {
    if (!onDisconnect) return;
    await onDisconnect(source.id);
    setConfirmSourceId(null);
  };

  const handleTest = async (source: Source) => {
    if (!onTest) return;
    await onTest(source.id);
  };

  if (isLoading) {
    return <p className="text-gray-600">Loading connected sources...</p>;
  }

  return (
    <section data-testid="data-sources-settings-tab" className="space-y-4">
      {sortedSources.length === 0 ? (
        <div className="border border-dashed border-gray-300 rounded-lg p-8 text-center" data-testid="sources-empty-state">
          <h3 className="font-semibold text-gray-900">No sources connected</h3>
          <p className="text-sm text-gray-600 mt-2">Connect a source to start syncing analytics data.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sortedSources.map((source) => (
            <article key={source.id} className="border border-gray-200 rounded-lg p-4" data-testid="connected-source-card">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="font-semibold text-gray-900">{source.displayName}</h3>
                  <p className="text-sm text-gray-600">{source.platform}</p>
                  <p className="text-xs text-gray-500 mt-1">
                    Last sync: {source.lastSyncAt ? new Date(source.lastSyncAt).toLocaleString() : 'Never'}
                  </p>
                </div>
                <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusClass(source.status)}`}>
                  {source.status}
                </span>
              </div>

              <div className="flex gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => navigate(`/sources?source=${source.id}`)}
                  className="px-3 py-1.5 border border-gray-300 rounded text-sm"
                >
                  Manage
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmSourceId(source.id)}
                  className="px-3 py-1.5 border border-red-300 text-red-700 rounded text-sm"
                  disabled={!onDisconnect}
                  title={!onDisconnect ? 'Disconnect endpoint is not available yet' : undefined}
                >
                  Disconnect
                </button>
                <button
                  type="button"
                  onClick={() => handleTest(source)}
                  className="px-3 py-1.5 border border-gray-300 rounded text-sm"
                  disabled={!onTest}
                  title={!onTest ? 'Test endpoint is not available yet' : undefined}
                >
                  Test
                </button>
              </div>

              {confirmSourceId === source.id ? (
                <div className="mt-3 border border-red-200 bg-red-50 rounded p-3" data-testid="disconnect-confirmation">
                  <p className="text-sm text-red-800">Are you sure you want to disconnect this source?</p>
                  <div className="flex gap-2 mt-2">
                    <button
                      type="button"
                      onClick={() => handleDisconnect(source)}
                      className="px-3 py-1.5 bg-red-600 text-white rounded text-sm"
                    >
                      Confirm Disconnect
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmSourceId(null)}
                      className="px-3 py-1.5 border border-gray-300 rounded text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      )}

      <div className="border border-dashed border-blue-300 rounded-lg p-6" data-testid="add-source-cta">
        <h3 className="font-semibold text-gray-900">Add New Data Source</h3>
        <p className="text-sm text-gray-600 mt-2">Connect Shopify, Google Ads, Meta, or other integrations.</p>
        <Link to="/sources" className="inline-block mt-3 text-blue-600 text-sm font-medium">
          Browse Integrations →
        </Link>
      </div>
    </section>
  );
}

export default DataSourcesSettingsTab;
