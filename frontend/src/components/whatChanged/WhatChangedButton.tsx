/**
 * WhatChangedButton Component
 *
 * Floating or inline button to open the What Changed debug panel.
 * Shows a badge indicator if there are recent critical issues.
 *
 * Story 9.8 - "What Changed?" Debug Panel
 */

import { useState, useEffect, useCallback } from 'react';
import { Button, Badge, Tooltip } from '@shopify/polaris';
import { QuestionCircleIcon } from '@shopify/polaris-icons';
import { WhatChangedPanel } from './WhatChangedPanel';
import { hasCriticalIssues } from '../../services/whatChangedApi';

interface WhatChangedButtonProps {
  variant?: 'floating' | 'inline';
  showBadge?: boolean;
  refreshInterval?: number;
}

export function WhatChangedButton({
  variant = 'inline',
  showBadge = true,
  refreshInterval = 60000,
}: WhatChangedButtonProps) {
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [hasCritical, setHasCritical] = useState(false);

  const checkCritical = useCallback(async () => {
    if (!showBadge) return;

    try {
      const critical = await hasCriticalIssues();
      setHasCritical(critical);
    } catch (err) {
      console.error('Failed to check critical issues:', err);
    }
  }, [showBadge]);

  useEffect(() => {
    checkCritical();

    const intervalId = setInterval(checkCritical, refreshInterval);
    return () => clearInterval(intervalId);
  }, [checkCritical, refreshInterval]);

  const handleClick = () => {
    setIsPanelOpen(true);
    // Reset badge on open
    setHasCritical(false);
  };

  const button = (
    <Button
      onClick={handleClick}
      icon={QuestionCircleIcon}
      variant={variant === 'floating' ? 'primary' : 'plain'}
    >
      {variant === 'inline' ? 'What changed?' : undefined}
    </Button>
  );

  const floatingStyles: React.CSSProperties =
    variant === 'floating'
      ? {
          position: 'fixed',
          bottom: '20px',
          right: '20px',
          zIndex: 1000,
        }
      : {};

  return (
    <>
      <div style={floatingStyles}>
        <Tooltip content="View recent data changes">
          {button}
        </Tooltip>
        {variant === 'floating' && showBadge && hasCritical && (
          <div
            style={{
              position: 'absolute',
              top: '-5px',
              right: '-5px',
            }}
          >
            <Badge tone="critical" size="small">
              !
            </Badge>
          </div>
        )}
      </div>

      <WhatChangedPanel
        isOpen={isPanelOpen}
        onClose={() => setIsPanelOpen(false)}
      />
    </>
  );
}

export default WhatChangedButton;
