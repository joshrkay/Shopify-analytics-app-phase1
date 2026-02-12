import { useEffect, useMemo } from 'react';
import {
  Bell,
  CreditCard,
  Database,
  Key,
  RefreshCw,
  Sparkles,
  User,
  Users,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useAgency } from '../contexts/AgencyContext';
import type { SettingsTab } from '../types/settingsTypes';
import { SettingsTabButton } from '../components/settings/SettingsTabButton';
import { DataSourcesSettingsTab } from '../components/settings/DataSourcesSettingsTab';
import { SyncSettingsTab } from '../components/settings/SyncSettingsTab';
import { TeamSettings } from '../components/settings/TeamSettings';

const ROLE_RANK = {
  viewer: 0,
  admin: 1,
  owner: 2,
} as const;

type RequiredRole = keyof typeof ROLE_RANK;

interface SettingsTabDefinition {
  id: SettingsTab;
  label: string;
  icon: LucideIcon;
  requiredRole: RequiredRole;
}

const SETTINGS_TABS: SettingsTabDefinition[] = [
  { id: 'sources', label: 'Data Sources', icon: Database, requiredRole: 'viewer' },
  { id: 'sync', label: 'Sync Settings', icon: RefreshCw, requiredRole: 'admin' },
  { id: 'notifications', label: 'Notifications', icon: Bell, requiredRole: 'viewer' },
  { id: 'account', label: 'Account', icon: User, requiredRole: 'viewer' },
  { id: 'team', label: 'Team', icon: Users, requiredRole: 'admin' },
  { id: 'billing', label: 'Billing', icon: CreditCard, requiredRole: 'owner' },
  { id: 'api', label: 'API Keys', icon: Key, requiredRole: 'admin' },
  { id: 'ai', label: 'AI Insights', icon: Sparkles, requiredRole: 'admin' },
];

function deriveUserRole(userRoles: string[] = []): RequiredRole {
  if (userRoles.some((role) => role === 'owner' || role === 'super_admin' || role === 'agency_admin')) {
    return 'owner';
  }

  if (userRoles.some((role) => role === 'admin' || role === 'merchant_admin' || role === 'editor')) {
    return 'admin';
  }

  return 'viewer';
}

function canAccessTab(userRole: RequiredRole, requiredRole: RequiredRole): boolean {
  return ROLE_RANK[userRole] >= ROLE_RANK[requiredRole];
}

function renderTabContent(tab: SettingsTab) {
  if (tab === 'sources') {
    return (
      <section data-testid="settings-panel-sources">
        <DataSourcesSettingsTab />
      </section>
    );
  }

  if (tab === 'sync') {
    return (
      <section data-testid="settings-panel-sync">
        <SyncSettingsTab />
      </section>
    );
  }

  if (tab === 'team') {
    return (
      <section data-testid="settings-panel-team">
        <TeamSettings />
      </section>
    );
  }

  return (
    <section data-testid={`settings-panel-${tab}`}>
      <h2 className="text-xl font-semibold mb-2">{SETTINGS_TABS.find((t) => t.id === tab)?.label}</h2>
      <p className="text-gray-600">Configure your {tab} settings.</p>
    </section>
  );
}

export default function Settings() {
  const { userRoles } = useAgency();
  const userRole = deriveUserRole(userRoles);
  const [searchParams, setSearchParams] = useSearchParams();
  const tabFromUrl = searchParams.get('tab');

  const visibleTabs = useMemo(
    () => SETTINGS_TABS.filter((tab) => canAccessTab(userRole, tab.requiredRole)),
    [userRole],
  );

  const fallbackTab = visibleTabs[0]?.id ?? 'sources';
  const requestedTab = (tabFromUrl ?? fallbackTab) as SettingsTab;
  const activeTab = visibleTabs.some((tab) => tab.id === requestedTab) ? requestedTab : fallbackTab;

  useEffect(() => {
    if (!visibleTabs.some((tab) => tab.id === requestedTab)) {
      const nextParams = new URLSearchParams(searchParams);
      nextParams.set('tab', fallbackTab);
      setSearchParams(nextParams, { replace: true });
    }
  }, [fallbackTab, requestedTab, searchParams, setSearchParams, visibleTabs]);

  return (
    <div className="p-6" data-testid="settings-page">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>
      <div className="flex flex-col md:flex-row gap-6">
        <aside className="md:w-64" data-testid="settings-sidebar">
          <div className="flex md:flex-col gap-2 overflow-x-auto" data-testid="settings-tab-list">
            {visibleTabs.map((tab) => (
              <SettingsTabButton
                key={tab.id}
                icon={tab.icon}
                active={activeTab === tab.id}
                onClick={() => {
                  const nextParams = new URLSearchParams(searchParams);
                  nextParams.set('tab', tab.id);
                  setSearchParams(nextParams);
                }}
              >
                {tab.label}
              </SettingsTabButton>
            ))}
          </div>
        </aside>

        <main className="flex-1" data-testid="settings-content">
          {renderTabContent(activeTab)}
        </main>
      </div>
    </div>
  );
}

export { SETTINGS_TABS, deriveUserRole, canAccessTab };
