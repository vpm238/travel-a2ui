import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import '@travel-a2ui/renderer/styles.css';
import './styles.css';

import App from './App.js';
import { Specimen } from './components/Specimen.js';

const container = document.getElementById('root');
if (!container) throw new Error('No #root element to mount into.');

// `/catalog/<Name>` is one component on its own; everything else is the app,
// which opens on the Catalog view at `/catalog`.
const specimen = /^\/catalog\/([A-Za-z][A-Za-z0-9]*)\/?$/.exec(window.location.pathname)?.[1];

createRoot(container).render(
  <StrictMode>{specimen ? <Specimen name={specimen} /> : <App />}</StrictMode>,
);
