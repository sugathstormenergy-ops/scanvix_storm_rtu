import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

// Self-hosted fonts and icons (no CDN): the dashboard works on a LAN without Internet access.
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './index.css';
import App from './App.jsx';

// No service worker / PWA: API responses must never be cached by the browser app.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
