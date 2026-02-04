/**
 * Date Utilities
 *
 * Shared date formatting functions for consistent display across the app.
 */

/**
 * Format a date as relative time (e.g., "2 hours ago").
 *
 * Returns short format for recent times (Xm, Xh, Xd) and full date for older.
 *
 * @param dateString - ISO date string
 * @param options - Formatting options
 * @returns Formatted relative time string
 */
export function formatRelativeTime(
  dateString: string,
  options: { verbose?: boolean } = {}
): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (options.verbose) {
    // Verbose format: "2 minutes ago", "3 hours ago"
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} minute${diffMins === 1 ? '' : 's'} ago`;
    if (diffHours < 24) return `${diffHours} hour${diffHours === 1 ? '' : 's'} ago`;
    if (diffDays < 7) return `${diffDays} day${diffDays === 1 ? '' : 's'} ago`;

    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
    });
  }

  // Compact format: "2m ago", "3h ago"
  if (diffMins < 60) {
    return `${diffMins}m ago`;
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  if (diffDays < 7) {
    return `${diffDays}d ago`;
  }
  return date.toLocaleDateString();
}

/**
 * Format minutes since a sync to human-readable string.
 *
 * @param minutes - Minutes since sync, or null if never synced
 * @returns Formatted string
 */
export function formatTimeSinceSync(minutes: number | null): string {
  if (minutes === null) {
    return 'Never synced';
  }

  if (minutes < 60) {
    return `${minutes} minutes ago`;
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
  }

  const days = Math.floor(hours / 24);
  return days === 1 ? '1 day ago' : `${days} days ago`;
}

/**
 * Format duration in seconds to human-readable format.
 *
 * @param seconds - Duration in seconds
 * @returns Formatted string (e.g., "1h 30m" or "45s")
 */
export function formatDuration(seconds?: number): string {
  if (seconds === undefined || seconds === null) return '-';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/**
 * Format a row count with thousands separator.
 *
 * @param count - Row count
 * @returns Formatted string (e.g., "1,234,567")
 */
export function formatRowCount(count?: number): string {
  if (count === undefined || count === null) return '-';
  return count.toLocaleString();
}

/**
 * Format expiry time relative to now.
 *
 * @param dateString - ISO date string of expiry time
 * @returns Formatted string (e.g., "Expires in 2h" or "Expired")
 */
export function formatExpiryTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMs <= 0) {
    return 'Expired';
  }
  if (diffHours < 24) {
    return `Expires in ${diffHours}h`;
  }
  return `Expires in ${diffDays}d`;
}
