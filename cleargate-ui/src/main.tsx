import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppProviders } from './app/providers';
import { AppRouter } from './app/router';
import './styles/globals.css';

async function initApp() {
  if (import.meta.env.VITE_API_MODE !== 'live') {
    const { worker } = await import('./mocks/browser');
    await worker.start({
      onUnhandledRequest: 'bypass',
      serviceWorker: {
        url: '/mockServiceWorker.js',
      },
    });
  }

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <AppProviders>
        <AppRouter />
      </AppProviders>
    </React.StrictMode>
  );
}

initApp();
