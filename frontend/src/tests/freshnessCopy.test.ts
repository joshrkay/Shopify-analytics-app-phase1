/**
 * Tests for freshness_copy.ts
 *
 * Validates all merchant-visible copy for data freshness states.
 * Ensures no raw timestamps leak and friendly text is always returned.
 */

import { describe, it, expect } from 'vitest';
import {
  getFreshnessLabel,
  getFreshnessBannerTitle,
  getFreshnessBannerMessage,
  getFreshnessTooltip,
  getFreshnessBadgeTone,
  getFreshnessBannerTone,
} from '../utils/freshness_copy';
import type { DataFreshnessState } from '../utils/freshness_copy';

// =============================================================================
// getFreshnessLabel
// =============================================================================

describe('getFreshnessLabel', () => {
  it('returns "Up to date" for fresh state', () => {
    expect(getFreshnessLabel('fresh')).toBe('Up to date');
  });

  it('returns "Data delayed" for stale state', () => {
    expect(getFreshnessLabel('stale')).toBe('Data delayed');
  });

  it('returns "Data temporarily unavailable" for unavailable state', () => {
    expect(getFreshnessLabel('unavailable')).toBe('Data temporarily unavailable');
  });
});

// =============================================================================
// getFreshnessBannerTitle
// =============================================================================

describe('getFreshnessBannerTitle', () => {
  it('returns empty string for fresh state', () => {
    expect(getFreshnessBannerTitle('fresh')).toBe('');
  });

  it('returns non-empty title for stale state', () => {
    const title = getFreshnessBannerTitle('stale');
    expect(title).toBe('Data Update in Progress');
    expect(title.length).toBeGreaterThan(0);
  });

  it('returns non-empty title for unavailable state', () => {
    const title = getFreshnessBannerTitle('unavailable');
    expect(title).toBe('Data Temporarily Unavailable');
    expect(title.length).toBeGreaterThan(0);
  });
});

// =============================================================================
// getFreshnessBannerMessage
// =============================================================================

describe('getFreshnessBannerMessage', () => {
  it('returns empty string for fresh state', () => {
    expect(getFreshnessBannerMessage('fresh')).toBe('');
  });

  describe('stale state', () => {
    it('returns default message when no reason', () => {
      const msg = getFreshnessBannerMessage('stale');
      expect(msg).toContain('refreshed');
    });

    it('returns SLA message for sla_exceeded reason', () => {
      const msg = getFreshnessBannerMessage('stale', 'sla_exceeded');
      expect(msg).toContain('updated');
      expect(msg).toContain('hours');
    });

    it('returns failure message for sync_failed reason', () => {
      const msg = getFreshnessBannerMessage('stale', 'sync_failed');
      expect(msg).toContain('issue');
      expect(msg).toContain('notified');
    });
  });

  describe('unavailable state', () => {
    it('returns default message when no reason', () => {
      const msg = getFreshnessBannerMessage('unavailable');
      expect(msg).toContain('temporarily unavailable');
    });

    it('returns grace window message for grace_window_exceeded', () => {
      const msg = getFreshnessBannerMessage('unavailable', 'grace_window_exceeded');
      expect(msg).toContain('temporarily unavailable');
      expect(msg).toContain('support');
    });

    it('returns sync failed message for sync_failed', () => {
      const msg = getFreshnessBannerMessage('unavailable', 'sync_failed');
      expect(msg).toContain('difficulties');
    });

    it('returns setup message for never_synced', () => {
      const msg = getFreshnessBannerMessage('unavailable', 'never_synced');
      expect(msg).toContain('first time');
    });
  });

  it('never contains raw ISO timestamps', () => {
    const states: DataFreshnessState[] = ['fresh', 'stale', 'unavailable'];
    const reasons = [undefined, 'sla_exceeded', 'sync_failed', 'grace_window_exceeded', 'never_synced'];

    for (const state of states) {
      for (const reason of reasons) {
        const msg = getFreshnessBannerMessage(state, reason);
        // ISO timestamps look like 2026-01-01T00:00:00
        expect(msg).not.toMatch(/\d{4}-\d{2}-\d{2}T/);
      }
    }
  });
});

// =============================================================================
// getFreshnessTooltip
// =============================================================================

describe('getFreshnessTooltip', () => {
  it('returns tooltip for fresh state', () => {
    const tip = getFreshnessTooltip('fresh');
    expect(tip).toContain('up to date');
  });

  it('returns tooltip for stale state', () => {
    const tip = getFreshnessTooltip('stale');
    expect(tip).toContain('updated');
  });

  it('returns tooltip for unavailable state', () => {
    const tip = getFreshnessTooltip('unavailable');
    expect(tip).toContain('temporarily unavailable');
  });

  it('never returns an empty string', () => {
    const states: DataFreshnessState[] = ['fresh', 'stale', 'unavailable'];
    for (const state of states) {
      expect(getFreshnessTooltip(state).length).toBeGreaterThan(0);
    }
  });
});

// =============================================================================
// getFreshnessBadgeTone
// =============================================================================

describe('getFreshnessBadgeTone', () => {
  it('maps fresh to success', () => {
    expect(getFreshnessBadgeTone('fresh')).toBe('success');
  });

  it('maps stale to attention', () => {
    expect(getFreshnessBadgeTone('stale')).toBe('attention');
  });

  it('maps unavailable to critical', () => {
    expect(getFreshnessBadgeTone('unavailable')).toBe('critical');
  });
});

// =============================================================================
// getFreshnessBannerTone
// =============================================================================

describe('getFreshnessBannerTone', () => {
  it('maps fresh to info', () => {
    expect(getFreshnessBannerTone('fresh')).toBe('info');
  });

  it('maps stale to warning', () => {
    expect(getFreshnessBannerTone('stale')).toBe('warning');
  });

  it('maps unavailable to critical', () => {
    expect(getFreshnessBannerTone('unavailable')).toBe('critical');
  });
});
