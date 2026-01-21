/**
 * Main App Component
 *
 * Sets up Shopify Polaris provider and routing.
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppProvider } from '@shopify/polaris';
import enTranslations from '@shopify/polaris/locales/en.json';
import '@shopify/polaris/build/esm/styles.css';

import AdminPlans from './pages/AdminPlans';

function App() {
  return (
    <AppProvider i18n={enTranslations}>
      <BrowserRouter>
        <Routes>
          <Route path="/admin/plans" element={<AdminPlans />} />
          <Route path="/" element={<Navigate to="/admin/plans" replace />} />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
