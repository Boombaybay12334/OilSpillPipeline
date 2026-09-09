/**
 * Header Component — Telemetry & Active Investigation Selector
 */
import { store } from '../state.js';
import { Api } from '../api.js';

export function renderHeader(container) {
  const state = store.getState();
  const currentEvent = state.currentEvent;
  const investigations = state.investigations || [];
  const health = state.health || { ok: false, checks: {} };

  const checks = health.checks || {};
  const isHealthy = (key) => {
    const val = checks[key];
    return val && (typeof val === 'object' ? val.available : Boolean(val));
  };

  container.innerHTML = `
    <header class="app-header">
      <div class="header-left">
        <a href="#/overview" class="brand-mark">
          <div class="brand-icon">OS</div>
          <div class="brand-title">
            <h1>Oil Spill Intelligence</h1>
            <span class="brand-subtitle">Subsurface & SAR Surveillance System</span>
          </div>
        </a>

        <div class="header-divider"></div>

        <div class="health-telemetry" title="Backend subsystem health diagnostics">
          <div class="telemetry-chip">
            <span class="telemetry-dot ${isHealthy('data_root') ? '' : 'error'}"></span>
            <span>STORAGE</span>
          </div>
          <div class="telemetry-chip">
            <span class="telemetry-dot ${isHealthy('stage1_service') ? '' : 'warn'}"></span>
            <span>SAR MODEL</span>
          </div>
          <div class="telemetry-chip">
            <span class="telemetry-dot ${isHealthy('rasterio') ? '' : 'warn'}"></span>
            <span>RASTERIO</span>
          </div>
          <div class="telemetry-chip">
            <span class="telemetry-dot ${isHealthy('opendrift') ? '' : 'warn'}"></span>
            <span>OPENDRIFT</span>
          </div>
          <div class="telemetry-chip">
            <span class="telemetry-dot ${isHealthy('gfw_configured') ? '' : 'warn'}"></span>
            <span>GFW AIS</span>
          </div>
        </div>
      </div>

      <div class="header-right">
        <div class="event-selector-wrap">
          <select id="header-event-select" class="event-select-btn font-mono" title="Switch active investigation">
            ${investigations.length === 0 ? '<option value="">No investigations available</option>' : ''}
            ${investigations.map(ev => `
              <option value="${ev.event_id}" ${currentEvent && currentEvent.event_id === ev.event_id ? 'selected' : ''}>
                ${escapeHtml(ev.name)} · [${ev.mode.toUpperCase()}]
              </option>
            `).join('')}
          </select>
        </div>

        <button id="btn-open-new-event" class="btn-primary">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
          <span>New Surveillance</span>
        </button>
      </div>
    </header>
  `;

  const selectEl = container.querySelector('#header-event-select');
  if (selectEl) {
    selectEl.onchange = async (e) => {
      const selectedId = e.target.value;
      if (!selectedId) return;
      try {
        store.setLoading(true);
        const eventData = await Api.getInvestigation(selectedId);
        store.setCurrentEvent(eventData);
        // Pre-fetch stage summaries
        loadStageSummaries(selectedId);
      } catch (err) {
        store.setError(err.message);
      } finally {
        store.setLoading(false);
      }
    };
  }

  const newBtn = container.querySelector('#btn-open-new-event');
  if (newBtn) {
    newBtn.onclick = () => {
      const modal = document.getElementById('new-event-modal');
      if (modal) modal.style.display = 'grid';
    };
  }
}

async function loadStageSummaries(eventId) {
  for (let s = 1; s <= 3; s++) {
    try {
      const res = await Api.getStageSummary(eventId, s);
      store.setStageSummary(`stage${s}`, res.summary);
    } catch {
      // optional
    }
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
