/**
 * AppHeader Component
 *
 * Slim top utility bar with changelog, debug controls, notifications,
 * and profile menu. Navigation lives in the Sidebar component (Phase 0).
 * Includes hamburger toggle for mobile sidebar.
 *
 * Story 9.7 - In-App Changelog & Release Notes
 * Story 9.8 - "What Changed?" Debug Panel
 * Story 0.1.2 - AppHeader becomes slim top utility bar
 * Story 0.3.1 - Mobile hamburger toggles sidebar
 * Phase 1 - Header & ProfileSwitcher
 */

import { InlineStack, Box, Icon } from '@shopify/polaris';
import { MenuIcon } from '@shopify/polaris-icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { ChangelogBadge } from '../changelog/ChangelogBadge';
import { WhatChangedButton } from '../whatChanged/WhatChangedButton';
import { NotificationBadge } from '../common/NotificationBadge';
import { ProfileMenu } from './ProfileMenu';
import { useSidebar } from './RootLayout';
import { getUnreadInsightsCount } from '../../services/insightsApi';
import './AppHeader.css';

export function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isOpen, toggle } = useSidebar();

  const handleWhatsNewClick = () => {
    navigate('/whats-new');
  };

  const handleInsightsClick = () => {
    navigate('/insights');
  };

  const isOnWhatsNewPage = location.pathname === '/whats-new';

  return (
    <Box
      paddingBlockStart="200"
      paddingBlockEnd="200"
      paddingInlineStart="400"
      paddingInlineEnd="400"
      background="bg-surface-secondary"
      borderBlockEndWidth="025"
      borderColor="border"
    >
      <InlineStack align="space-between" gap="400" blockAlign="center">
        {/* Left: hamburger (mobile only) */}
        <button
          className="sidebar-hamburger"
          onClick={toggle}
          aria-label="Toggle navigation"
          aria-expanded={isOpen}
          aria-controls="sidebar-nav"
          type="button"
        >
          <Icon source={MenuIcon} />
        </button>

        {/* Right: Status indicators + profile */}
        <InlineStack gap="400" blockAlign="center">
          {!isOnWhatsNewPage && (
            <ChangelogBadge
              onClick={handleWhatsNewClick}
              showLabel
              label="What's New"
              refreshInterval={60000}
            />
          )}
          <WhatChangedButton
            variant="inline"
            showBadge
            refreshInterval={60000}
          />
          <NotificationBadge
            fetchCount={getUnreadInsightsCount}
            onClick={handleInsightsClick}
            refreshInterval={60000}
            singularNoun="insight"
            pluralNoun="insights"
            tone="info"
          />
          <ProfileMenu />
        </InlineStack>
      </InlineStack>
    </Box>
  );
}

export default AppHeader;
