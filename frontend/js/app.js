/**
 * Oil Spill Intelligence Platform — Main Application Bootstrap
 */
import { store } from './state.js';
import { Api } from './api.js';

import { renderHeader } from './components/header.js';
import { renderNavigation } from './components/navigation.js';
import { renderOverview } from './components/overview.js';
import { renderStage1 } from './components/stage1_detection.js';
import { renderStage2 } from './components/stage2_backtracking.js';
import { renderStage3 } from './components/stage3_attribution.js';
import { renderUnifiedMap } from './components/unified_map.js';
import { renderArtifacts } from './components/artifacts.js';
import { renderConfig } from './components/config.js';
import { initNewEventModal } from './components/new_event_modal.js';

const $ = (id) => document.getElementById(id);

async function init() {
  const headerContainer = $('header-container');
  const navContainer = $('nav-container');
  const workspaceContainer = $('workspace-container');

  // Initialize Modal
  initNewEventModal();

  // Router handler
  function route() {
    const hash = window.location.hash.replace('#/', '').toLowerCase();
    const validPages = ['overview', 'stage1', 'stage2', 'stage3', 'map', 'artifacts', 'config'];
    const page = validPages.includes(hash) ? hash : 'overview';
    store.setActivePage(page);
    renderCurrentPage(workspaceContainer, page);
  }

  // Subscribe to store updates for header, navigation, and page
  store.subscribe((state) => {
    if (headerContainer) renderHeader(headerContainer);
    if (navContainer) renderNavigation(navContainer);
  });

  window.addEventListener('hashchange', route);

  // Keyboard Navigation Shortcuts
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
    if (e.key === '1') window.location.hash = '#/stage1';
    if (e.key === '2') window.location.hash = '#/stage2';
    if (e.key === '3') window.location.hash = '#/stage3';
    if (e.key === 'o' || e.key === 'O') window.location.hash = '#/overview';
    if (e.key === 'm' || e.key === 'M') window.location.hash = '#/map';
    if (e.key === 'a' || e.key === 'A') window.location.hash = '#/artifacts';
  });

  // Initial Data Fetch
  try {
    store.setLoading(true);

    // Fetch Health
    try {
      const health = await Api.getHealth();
      store.setHealth(health);
    } catch (err) {
      console.warn('[Health] Telemetry check failed:', err);
    }

    // Fetch Investigations
    const investigations = await Api.listInvestigations();
    store.setInvestigations(investigations);

    if (investigations.length > 0) {
      const firstEvent = await Api.getInvestigation(investigations[0].event_id);
      store.setCurrentEvent(firstEvent);

      // Load stage summaries
      for (let s = 1; s <= 3; s++) {
        try {
          const res = await Api.getStageSummary(firstEvent.event_id, s);
          store.setStageSummary(`stage${s}`, res.summary);
        } catch {
          // optional
        }
      }
    }

    route();
  } catch (err) {
    console.error('[Bootstrap] Initialization error:', err);
    workspaceContainer.innerHTML = `
      <div class="empty-state" style="border-color:var(--coral-border);">
        <h3 style="color:var(--coral-alert);">Backend Connection Offline</h3>
        <p>${err.message}</p>
        <p style="font-size:0.75rem; color:var(--text-muted);">
          Start the local backend with: <code>uvicorn app.main:app --app-dir backend --reload --port 8000</code>
        </p>
      </div>
    `;
  } finally {
    store.setLoading(false);
  }
}

function renderCurrentPage(container, page) {
  switch (page) {
    case 'overview':
      renderOverview(container);
      break;
    case 'stage1':
      renderStage1(container);
      break;
    case 'stage2':
      renderStage2(container);
      break;
    case 'stage3':
      renderStage3(container);
      break;
    case 'map':
      renderUnifiedMap(container);
      break;
    case 'artifacts':
      renderArtifacts(container);
      break;
    case 'config':
      renderConfig(container);
      break;
    default:
      renderOverview(container);
  }
}

// Global Exports for backwards compatibility if needed
window.OilApp = { store, Api, init };

document.addEventListener('DOMContentLoaded', init);
