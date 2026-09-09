/**
 * Overview Component — Executive Intelligence Dossier
 */
import { store } from '../state.js';

export function renderOverview(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const s1 = state.stageSummaries.stage1;
  const s2 = state.stageSummaries.stage2;
  const s3 = state.stageSummaries.stage3;

  if (!event) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">OS</div>
        <h3>No Investigation Selected</h3>
        <p>Select an existing surveillance replay from the top bar or initialize a new incident analysis.</p>
        <button onclick="document.getElementById('new-event-modal').style.display='grid'" class="btn-primary">
          Start New Surveillance
        </button>
      </div>
    `;
    return;
  }

  // Extract key stats from summaries
  const s1Meta = s1?.metadata || {};
  const s1Area = s1?.detection_summary?.total_oil_area_km2 ?? 0;
  const s1Count = s1?.region_count ?? 0;
  const catalogId = s1Meta.catalog_id || s2?.observation?.catalog_id || 'Sentinel-1 SAR Scene';
  const obsTime = s2?.observation?.t_obs_utc || s1Meta.acquisition_start || event.created_at_utc;

  const topShip = s3?.candidates?.[0] || null;
  const simWindow = s2?.simulation_window || {};

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">INTELLIGENCE BRIEFING · ${escapeHtml(event.mode.toUpperCase())}</span>
          <h2 class="page-title">${escapeHtml(event.name)}</h2>
          <p class="page-desc">
            Geospatial SAR incident tracking, Lagrangian oceanographic backtracking, and Global Fishing Watch AIS candidate correlation.
          </p>
        </div>

        <div class="page-actions">
          <a href="#/map" class="btn-primary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>
            <span>Launch Geospatial Instrument</span>
          </a>
        </div>
      </div>

      <!-- Key Metrics Row -->
      <div class="metrics-row">
        <div class="metric-card">
          <span class="metric-label">Observation Timestamp</span>
          <div class="metric-value-wrap">
            <span class="metric-value" style="font-size:1.15rem;">${formatTimestamp(obsTime)}</span>
          </div>
          <span class="metric-sub">${catalogId.split('_')[0] || 'Sentinel-1'} C-band SAR</span>
        </div>

        <div class="metric-card">
          <span class="metric-label">Detected Oil Footprint</span>
          <div class="metric-value-wrap">
            <span class="metric-value">${s1Area > 0 ? Number(s1Area).toFixed(2) : (s1Count > 0 ? s1Count : '0')}</span>
            <span class="metric-unit">${s1Area > 0 ? 'km²' : 'regions'}</span>
          </div>
          <span class="metric-sub">${s1Count} candidate slick polygons classified</span>
        </div>

        <div class="metric-card">
          <span class="metric-label">Drift Backtrack Window</span>
          <div class="metric-value-wrap">
            <span class="metric-value">${s2?.hypothesis_count ? `${s2.hypothesis_count}h` : '69h'}</span>
            <span class="metric-unit">duration</span>
          </div>
          <span class="metric-sub">${s2?.backtracking?.current_forcing?.provider ? 'CMEMS GLORYS12V1 + ERA5' : 'Lagrangian particle simulation'}</span>
        </div>

        <div class="metric-card">
          <span class="metric-label">Top Vessel Candidate</span>
          <div class="metric-value-wrap">
            <span class="metric-value" style="font-size:1.15rem; color:var(--cyan-accent);">
              ${escapeHtml(topShip?.name || (topShip ? `MMSI ${topShip.mmsi}` : 'Pending'))}
            </span>
          </div>
          <span class="metric-sub">
            ${topShip ? `Score: ${(topShip.score * 100).toFixed(1)}% · Dist: ${topShip.best_distance_km ? Number(topShip.best_distance_km).toFixed(1) : 'N/A'}km` : 'Run Stage 3 Attribution'}
          </span>
        </div>
      </div>

      <!-- Pipeline Progression Flow -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            <span>Surveillance Pipeline Status</span>
          </h3>
          <span class="page-eyebrow">CLICK STAGE TO INSPECT</span>
        </div>
        <div class="panel-body">
          <div class="pipeline-flow">
            <div class="pipeline-step ${s1 ? 'ready' : ''}" onclick="location.hash='#/stage1'">
              <div class="pipeline-step-header">
                <span class="pipeline-step-num">STAGE 01</span>
                <span class="telemetry-dot ${s1 ? '' : 'warn'}"></span>
              </div>
              <div class="pipeline-step-title">SAR Detection</div>
              <div class="pipeline-step-desc">
                ${s1 ? `Acquisition verified. ${s1Count} regions detected with U-Net probability & dual-pol SAR Sigma0.` : 'No stage 1 data imported. Import outputs or execute detection.'}
              </div>
            </div>

            <div class="pipeline-step ${s2 ? 'ready' : ''}" onclick="location.hash='#/stage2'">
              <div class="pipeline-step-header">
                <span class="pipeline-step-num">STAGE 02</span>
                <span class="telemetry-dot ${s2 ? '' : 'warn'}"></span>
              </div>
              <div class="pipeline-step-title">Backtracking Drift</div>
              <div class="pipeline-step-desc">
                ${s2 ? `Lagrangian model completed across ${s2.hypothesis_count || 69} hourly steps with ocean current forcing.` : 'Awaiting Stage 1 handoff and oceanographic particle seeding.'}
              </div>
            </div>

            <div class="pipeline-step ${s3 ? 'ready' : ''}" onclick="location.hash='#/stage3'">
              <div class="pipeline-step-header">
                <span class="pipeline-step-num">STAGE 03</span>
                <span class="telemetry-dot ${s3 ? '' : 'warn'}"></span>
              </div>
              <div class="pipeline-step-title">AIS Attribution</div>
              <div class="pipeline-step-desc">
                ${s3 ? `${s3.candidates?.length || 0} candidate vessels ranked with spatial compatibility and trajectory consistency.` : 'Awaiting Stage 2 origin cells and AIS tracking correlation.'}
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Incident Scene Metadata Dossier -->
      <div class="analytical-grid">
        <div class="col-7">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                <span>Incident Telemetry & Dossier</span>
              </h3>
            </div>
            <div class="panel-body">
              <div class="dossier-grid">
                <div class="dossier-item">
                  <span class="dossier-key">Event Identifier</span>
                  <span class="dossier-val">${escapeHtml(event.event_id)}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Pipeline Mode</span>
                  <span class="dossier-val">${escapeHtml(event.mode.toUpperCase())}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Scene Catalog ID</span>
                  <span class="dossier-val">${escapeHtml(catalogId)}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Orbit State</span>
                  <span class="dossier-val">${escapeHtml(s2?.observation?.orbit_state || s1Meta.orbit_state || 'Descending')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Simulation Window Start</span>
                  <span class="dossier-val">${formatTimestamp(simWindow.start)}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Simulation Window End</span>
                  <span class="dossier-val">${formatTimestamp(simWindow.end)}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-5">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
                <span>Lead Candidate Dossier</span>
              </h3>
            </div>
            <div class="panel-body">
              ${topShip ? `
                <div style="display:flex; flex-direction:column; gap:var(--space-3);">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                      <h4 style="font-size:1.1rem; color:var(--text-primary); margin:0;">${escapeHtml(topShip.name || 'UNKNOWN NAME')}</h4>
                      <small class="font-mono">MMSI: ${escapeHtml(topShip.mmsi || 'N/A')} · IMO: ${escapeHtml(topShip.imo || 'N/A')} · FLAG: ${escapeHtml(topShip.flag || 'N/A')}</small>
                    </div>
                    <div style="text-align:right;">
                      <span class="candidate-score-val">${(topShip.score * 100).toFixed(2)}%</span>
                      <small style="display:block; color:var(--text-muted);">Attribution Score</small>
                    </div>
                  </div>

                  <div class="metric-bars-group">
                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>Spatial Compatibility</span>
                        <span>${Number(topShip.spatial_compatibility * 100).toFixed(1)}%</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, (topShip.spatial_compatibility || 0) * 100)}%;"></div>
                      </div>
                    </div>

                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>AIS Signal Coverage</span>
                        <span>${Number(topShip.coverage_percent || 0).toFixed(1)}%</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, topShip.coverage_percent || 0)}%;"></div>
                      </div>
                    </div>

                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>Trajectory Consistency</span>
                        <span>${Number(topShip.trajectory_consistency * 100).toFixed(0)}%</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, (topShip.trajectory_consistency || 1) * 100)}%;"></div>
                      </div>
                    </div>
                  </div>

                  <a href="#/stage3" class="btn-secondary btn-sm" style="margin-top:var(--space-2); text-align:center;">
                    Inspect All Candidate Ships & Evidence →
                  </a>
                </div>
              ` : `
                <div class="empty-state" style="padding:var(--space-6);">
                  <p>No AIS attribution data loaded for this investigation yet.</p>
                  <a href="#/stage3" class="btn-secondary btn-sm">Open Stage 3 Attribution</a>
                </div>
              `}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function formatTimestamp(isoStr) {
  if (!isoStr) return 'N/A';
  try {
    const d = new Date(isoStr);
    return d.toUTCString().replace('GMT', 'UTC');
  } catch {
    return isoStr;
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
