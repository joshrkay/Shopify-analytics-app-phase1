/**
 * Sidebar Component
 *
 * Fixed left sidebar with navigation sections and user footer.
 * Active route highlighting via useLocation().
 * Feature-gated items via isFeatureEntitled().
 * Admin section conditionally shown for org:admin role.
 * Mobile: slides in/out via SidebarContext.
 *
 * Epic 0.2 — Sidebar navigation + access control
 * Story 0.2.1 — Nav sections: MAIN, CONNECTIONS, SETTINGS + user footer
 * Story 0.2.2 — Active route highlighting
 * Story 0.2.3 — Feature-gated links hidden when not entitled
 * Story 0.2.4 — Admin links only appear for admin roles
 * Epic 0.3 — Responsive + accessibility
 * Story 0.3.1 — Mobile hamburger toggles sidebar
 * Story 0.3.2 — Keyboard navigation through sidebar
 */

import { Icon, Text } from '@shopify/polaris';
import type { IconSource } from '@shopify/polaris';
import {
  HomeIcon,
  ChartVerticalIcon,
  LightbulbIcon,
  DatabaseIcon,
  SettingsIcon,
  CreditCardIcon,
  SearchIcon,
} from '@shopify/polaris-icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { useUser, useOrganization } from '@clerk/clerk-react';
import { useEntitlements } from '../../hooks/useEntitlements';
import { isFeatureEntitled } from '../../services/entitlementsApi';
import { useSidebar } from './RootLayout';
import './Sidebar.css';

interface NavItem {
  label: string;
  path: string;
  icon: IconSource;
  matchPrefix?: boolean;
  feature?: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Main',
    items: [
      { label: 'Home', path: '/home', icon: HomeIcon },
      { label: 'Builder', path: '/dashboards', icon: ChartVerticalIcon, matchPrefix: true, feature: 'custom_reports' },
      { label: 'Insights', path: '/insights', icon: LightbulbIcon, feature: 'ai_insights' },
    ],
  },
  {
    title: 'Connections',
    items: [
      { label: 'Sources', path: '/data-sources', icon: DatabaseIcon },
    ],
  },
  {
    title: 'Settings',
    items: [
      { label: 'Settings', path: '/settings', icon: SettingsIcon },
    ],
  },
];

const ADMIN_SECTION: NavSection = {
  title: 'Admin',
  items: [
    { label: 'Plans', path: '/admin/plans', icon: CreditCardIcon },
    { label: 'Diagnostics', path: '/admin/diagnostics', icon: SearchIcon },
  ],
};

function isActiveRoute(location: { pathname: string }, item: NavItem): boolean {
  if (item.matchPrefix) {
    return location.pathname.startsWith(item.path);
  }
  return location.pathname === item.path;
}

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useUser();
  const { membership } = useOrganization();
  const { entitlements } = useEntitlements();
  const { isOpen, close } = useSidebar();

  const isAdmin = membership?.role === 'org:admin';
  const userName = user?.fullName || user?.firstName || 'User';
  const userEmail = user?.primaryEmailAddress?.emailAddress || '';
  const avatarInitial = userName.charAt(0).toUpperCase();

  const handleNavigate = (path: string) => {
    navigate(path);
    close();
  };

  const renderSection = (section: NavSection) => {
    const visibleItems = section.items.filter(
      (item) => !item.feature || isFeatureEntitled(entitlements, item.feature)
    );

    if (visibleItems.length === 0) return null;

    return (
      <div key={section.title} className="sidebar-section">
        <div className="sidebar-section-header">{section.title}</div>
        {visibleItems.map((item) => {
          const active = isActiveRoute(location, item);
          return (
            <div
              key={item.path}
              className={`sidebar-nav-item${active ? ' sidebar-nav-item--active' : ''}`}
              role="link"
              tabIndex={0}
              aria-current={active ? 'page' : undefined}
              onClick={() => handleNavigate(item.path)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  handleNavigate(item.path);
                }
              }}
            >
              <Icon source={item.icon} />
              <Text as="span" variant="bodyMd">
                {item.label}
              </Text>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <nav
      id="sidebar-nav"
      className={`sidebar${isOpen ? ' sidebar--open' : ''}`}
      aria-label="Main navigation"
    >
      <div className="sidebar-nav">
        {NAV_SECTIONS.map(renderSection)}
        {isAdmin && renderSection(ADMIN_SECTION)}
      </div>

      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="sidebar-avatar">{avatarInitial}</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">{userName}</div>
            {userEmail && <div className="sidebar-user-email">{userEmail}</div>}
          </div>
        </div>
      </div>
    </nav>
  );
}
