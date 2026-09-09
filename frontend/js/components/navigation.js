/**
 * Navigation Component — Pipeline Stage Tabs & Global Sections
 */
import { store } from '../state.js';

export function renderNavigation(container) {
  const state = store.getState();
  const currentEvent = state.currentEvent;
  const activePage = state.activePage || 'overview';

  const status = currentEvent ? (currentEvent.status || 'created') : 'none';
  const isStage1Ready = status.includes('stage1_ready') || status.includes('stage2') || status.includes('stage3');
  const isStage2Ready = status.includes('stage2_ready') || status.includes('stage3');
  const isStage3Ready = status.includes('stage3_ready');

  container.innerHTML = `
    <nav class="app-nav">
      <div class="nav-tabs">
        <a href="#/overview" class="nav-tab-item ${activePage === 'overview' ? 'active' : ''}">
          <span>Overview</span>
        </a>

        <a href="#/stage1" class="nav-tab-item ${activePage === 'stage1' ? 'active' : ''}">
          <span class="nav-tab-num">01</span>
          <span>SAR Detection</span>
          ${isStage1Ready ? '<span class="telemetry-dot" style="width:4px;height:4px;background:var(--cyan-accent);box-shadow:none;"></span>' : ''}
        </a>

        <a href="#/stage2" class="nav-tab-item ${activePage === 'stage2' ? 'active' : ''}">
          <span class="nav-tab-num">02</span>
          <span>Backtracking</span>
          ${isStage2Ready ? '<span class="telemetry-dot" style="width:4px;height:4px;background:var(--cyan-accent);box-shadow:none;"></span>' : ''}
        </a>

        <a href="#/stage3" class="nav-tab-item ${activePage === 'stage3' ? 'active' : ''}">
          <span class="nav-tab-num">03</span>
          <span>Vessel Attribution</span>
          ${isStage3Ready ? '<span class="telemetry-dot" style="width:4px;height:4px;background:var(--cyan-accent);box-shadow:none;"></span>' : ''}
        </a>

        <a href="#/map" class="nav-tab-item ${activePage === 'map' ? 'active' : ''}">
          <span>Geospatial Map</span>
        </a>

        <a href="#/artifacts" class="nav-tab-item ${activePage === 'artifacts' ? 'active' : ''}">
          <span>Artifacts</span>
        </a>

        <a href="#/config" class="nav-tab-item ${activePage === 'config' ? 'active' : ''}">
          <span>System & Setup</span>
        </a>
      </div>

      <div class="nav-status-badge">
        <span class="telemetry-dot ${status.includes('ready') ? '' : 'warn'}"></span>
        <span>${escapeHtml(status.toUpperCase().replace('_', ' '))}</span>
      </div>
    </nav>
  `;
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
