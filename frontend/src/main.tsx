import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { ClerkProvider } from '@clerk/clerk-react';
import App from './App';

// Clerk publishable key from environment
const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

if (!PUBLISHABLE_KEY) {
  // Show a visible error instead of a silent white screen.
  // This fires when the env var was missing at Vite build time.
  const root = document.getElementById('root')!;
  root.innerHTML =
    '<div style="padding:40px;text-align:center;font-family:system-ui,sans-serif">' +
    '<h1 style="color:#d32f2f">Configuration Error</h1>' +
    '<p>Missing <code>VITE_CLERK_PUBLISHABLE_KEY</code> environment variable.</p>' +
    '<p style="color:#666">This variable must be set at build time. Redeploy after setting it in your hosting dashboard.</p>' +
    '</div>';
} else {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ClerkProvider publishableKey={PUBLISHABLE_KEY} afterSignOutUrl="/">
        <App />
      </ClerkProvider>
    </StrictMode>
  );
}
