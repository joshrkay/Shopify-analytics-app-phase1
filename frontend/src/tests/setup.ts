/**
 * Test Setup
 *
 * Configures testing environment for Vitest.
 */

import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Mock window.location
Object.defineProperty(window, 'location', {
  value: {
    pathname: '/',
    search: '',
    href: 'http://localhost:3000/',
    replace: vi.fn(),
  },
  writable: true,
});

// Mock window.history
Object.defineProperty(window, 'history', {
  value: {
    pushState: vi.fn(),
    replaceState: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
  },
  writable: true,
});

// Mock window.top for iframe context
Object.defineProperty(window, 'top', {
  value: window,
  writable: true,
});
