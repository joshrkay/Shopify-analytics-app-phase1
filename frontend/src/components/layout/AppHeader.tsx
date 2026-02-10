/**
 * AppHeader Component
 *
 * Global header with navigation links and status indicators.
 * Includes ChangelogBadge and WhatChangedButton for stories 9.7 and 9.8.
 * Adds "Analytics" and "Dashboards" nav items for Phase 4D.
 *
 * Story 9.7 - In-App Changelog & Release Notes
 * Story 9.8 - "What Changed?" Debug Panel
 * Phase 4D  - Integration & Navigation Polish
 */

import { Button, InlineStack, Box } from '@shopify/polaris';
import { useNavigate, useLocation } from 'react-router-dom';
import { ChangelogBadge } from '../changelog/ChangelogBadge';
import { WhatChangedButton } from '../whatChanged/WhatChangedButton';

export function AppHeader() {
  const navigate = useNavigate();
  const location = useLocation();

  const handleWhatsNewClick = () => {
    navigate('/whats-new');
  };

  const isOnWhatsNewPage = location.pathname === '/whats-new';
  const isOnAnalytics = location.pathname === '/analytics';
  const isOnDashboards = location.pathname.startsWith('/dashboards');

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
        {/* Left: Navigation links */}
        <InlineStack gap="200" blockAlign="center">
          <Button
            variant={isOnAnalytics ? 'primary' : 'plain'}
            onClick={() => navigate('/analytics')}
          >
            Analytics
          </Button>
          <Button
            variant={isOnDashboards ? 'primary' : 'plain'}
            onClick={() => navigate('/dashboards')}
          >
            Dashboards
          </Button>
        </InlineStack>

        {/* Right: Status indicators */}
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
        </InlineStack>
      </InlineStack>
    </Box>
  );
}

export default AppHeader;
