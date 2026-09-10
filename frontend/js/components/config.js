/**
 * Configuration & System Setup Component
 */
import { store } from '../state.js';
import { Api } from '../api.js';
import { getInvestigationPaths, saveInvestigationPaths } from '../path_settings.js';

export function renderConfig(container) {
  const state = store.getState();
  const event = state.currentEvent;

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  const paths = getInvestigationPaths(event.event_id);

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">SYSTEM & SURVEILLANCE SETUP</span>
          <h2 class="page-title">Configuration & Data Paths</h2>
          <p class="page-desc">
            Manage the active investigation directory, execution mode, stage input bindings, and safe event teardown.
          </p>
        </div>
      </div>

      <!-- Active Event Details -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            <span>Investigation Parameters</span>
          </h3>
        </div>
        <div class="panel-body">
          <div class="dossier-grid">
            <div class="dossier-item">
              <span class="dossier-key">Event Name</span>
              <span class="dossier-val">${escapeHtml(event.name)}</span>
            </div>
            <div class="dossier-item">
              <span class="dossier-key">Event Identifier</span>
              <span class="dossier-val">${escapeHtml(event.event_id)}</span>
            </div>
            <div class="dossier-item">
              <span class="dossier-key">Surveillance Mode</span>
              <span class="dossier-val">${escapeHtml(event.mode.toUpperCase())}</span>
            </div>
            <div class="dossier-item">
              <span class="dossier-key">Isolation Root</span>
              <span class="dossier-val">data/investigations/${escapeHtml(event.event_id)}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Expected Paths Reference -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
            <span>Default Input Locations (Replay & Offline Mode)</span>
          </h3>
        </div>
        <div class="panel-body">
          <div class="dossier-grid">
            <div class="dossier-item">
              <span class="dossier-key">Stage 1 SAR Detection Outputs</span>
              <input id="stage1-default-path" class="font-mono" type="text" value="${escapeHtml(paths.stage1)}">
            </div>
            <div class="dossier-item">
              <span class="dossier-key">Stage 2 Backtracking Handoff</span>
              <input id="stage2-default-path" class="font-mono" type="text" value="${escapeHtml(paths.stage2)}">
            </div>
            <div class="dossier-item">
              <span class="dossier-key">Stage 3 AIS Ranking Outputs</span>
              <input id="stage3-default-path" class="font-mono" type="text" value="${escapeHtml(paths.stage3)}">
            </div>
          </div>
          <button id="btn-save-paths" class="btn-primary">Save Input Paths</button>
          <span id="paths-save-status" style="margin-left:var(--space-2); color:var(--text-muted);"></span>
        </div>
      </div>

      <!-- Danger Zone / Teardown -->
      <div class="panel" style="border-color:var(--coral-border);">
        <div class="panel-header" style="background:var(--coral-bg); border-bottom-color:var(--coral-border);">
          <h3 style="color:var(--coral-alert);">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            <span>Delete Investigation</span>
          </h3>
        </div>
        <div class="panel-body">
          <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:var(--space-3);">
            Permanently deletes this investigation's copied data, manifest, quickviews, and SQLite records. Original source folders in <code>Model</code> and <code>BacktrackModel</code> remain untouched.
          </p>
          <button id="btn-delete-event" class="btn-danger">
            Delete Investigation (${escapeHtml(event.name)})
          </button>
        </div>
      </div>
    </div>
  `;

  const savePathsBtn = container.querySelector('#btn-save-paths');
  if (savePathsBtn) {
    savePathsBtn.onclick = () => {
      saveInvestigationPaths(event.event_id, {
        stage1: container.querySelector('#stage1-default-path').value,
        stage2: container.querySelector('#stage2-default-path').value,
        stage3: container.querySelector('#stage3-default-path').value,
      });
      container.querySelector('#paths-save-status').textContent = 'Saved for this investigation';
    };
  }

  // Bind Delete
  const deleteBtn = container.querySelector('#btn-delete-event');
  if (deleteBtn) {
    deleteBtn.onclick = async () => {
      const confirmed = window.confirm(`Permanently delete investigation "${event.name}" (${event.event_id})?`);
      if (!confirmed) return;

      try {
        await Api.deleteInvestigation(event.event_id);
        const list = await Api.listInvestigations();
        store.setInvestigations(list);
        if (list.length > 0) {
          const first = await Api.getInvestigation(list[0].event_id);
          store.setCurrentEvent(first);
          location.hash = '#/overview';
        } else {
          store.setCurrentEvent(null);
          location.hash = '#/overview';
        }
      } catch (err) {
        alert(`Deletion failed: ${err.message}`);
      }
    };
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
