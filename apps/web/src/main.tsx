import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '@travel-a2ui/renderer/styles.css';
import './styles.css';

import App from './App.js';

const container = document.getElementById('root');
if (!container) throw new Error('No #root element to mount into.');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
