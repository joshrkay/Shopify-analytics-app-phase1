/**
 * ProfileMenu Component
 *
 * Profile dropdown menu in the AppHeader with:
 * - Current user name and email from Clerk
 * - Active workspace info from AgencyContext
 * - Settings link
 * - Sign Out action via Clerk
 *
 * Phase 1 — Header & ProfileSwitcher
 */

import { useState, useCallback } from 'react';
import { Popover, ActionList, Text, BlockStack } from '@shopify/polaris';
import { SettingsIcon, ExitIcon } from '@shopify/polaris-icons';
import { useUser, useClerk } from '@clerk/clerk-react';
import { useNavigate } from 'react-router-dom';
import { useAgency } from '../../contexts/AgencyContext';

export function ProfileMenu() {
  const [active, setActive] = useState(false);
  const { user } = useUser();
  const { signOut } = useClerk();
  const navigate = useNavigate();
  const { getActiveStore, isAgencyUser } = useAgency();

  const toggleActive = useCallback(() => setActive((prev) => !prev), []);

  const handleSignOut = useCallback(async () => {
    setActive(false);
    await signOut();
  }, [signOut]);

  const handleSettings = useCallback(() => {
    setActive(false);
    navigate('/settings');
  }, [navigate]);

  const displayName = user?.fullName || user?.firstName || 'User';
  const email = user?.primaryEmailAddress?.emailAddress || '';
  const initial = displayName.charAt(0).toUpperCase();

  const activeStore = getActiveStore();
  const workspaceName = activeStore?.store_name || (isAgencyUser ? 'Select workspace' : '');

  const activator = (
    <button
      type="button"
      onClick={toggleActive}
      aria-label={`Profile menu for ${displayName}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--p-space-200)',
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        padding: 'var(--p-space-100)',
        borderRadius: 'var(--p-border-radius-200)',
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: 'var(--p-color-bg-fill-emphasis)',
          color: 'var(--p-color-text-inverse)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 'var(--p-font-size-75)',
          fontWeight: 'var(--p-font-weight-semibold)',
          flexShrink: 0,
        }}
        aria-hidden="true"
      >
        {initial}
      </div>
      <Text as="span" variant="bodySm">{displayName}</Text>
    </button>
  );

  return (
    <Popover
      active={active}
      activator={activator}
      onClose={toggleActive}
      autofocusTarget="first-node"
      preferredAlignment="right"
    >
      <div style={{ padding: 'var(--p-space-300)', minWidth: 220 }}>
        <BlockStack gap="100">
          <Text as="p" variant="bodySm" fontWeight="semibold">{displayName}</Text>
          {email && (
            <Text as="p" variant="bodySm" tone="subdued">{email}</Text>
          )}
          {workspaceName && (
            <Text as="p" variant="bodySm" tone="subdued">{workspaceName}</Text>
          )}
        </BlockStack>
      </div>
      <ActionList
        items={[
          {
            content: 'Settings',
            icon: SettingsIcon,
            onAction: handleSettings,
          },
          {
            content: 'Sign out',
            icon: ExitIcon,
            onAction: handleSignOut,
            destructive: true,
          },
        ]}
      />
    </Popover>
  );
}
