/**
 * Stage 2 Component — Oceanographic Lagrangian Backtracking & Origin Hypotheses
 */
import { store } from '../state.js';
import { Api } from '../api.js';

export function renderStage2(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const summary = state.stageSummaries.stage2;

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  const obs = summary?.observation || {};
  const bt = summary?.backtracking || {};
  const simWin = summary?.simulation_window || {};
  const hypotheses = summary?.origin_hypotheses || [];
  const topCells = summary?.top_cells || [];
  const limitations = summary?.limitations || [];

  const scrubberIdx = Math.min(state.scrubberIndex || 0, Math.max(0, hypotheses.length - 1));
  const currentHypo = hypotheses[scrubberIdx] || hypotheses[0] || null;

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">STAGE 02 · HYDRODYNAMIC BACKTRACKING</span>
          <h2 class="page-title">Oceanographic Drift Simulation</h2>
          <p class="page-desc">
            Lagrangian reverse particle tracking forced by Copernicus Marine (CMEMS) ocean currents and ECMWF ERA5 surface wind fields to infer candidate release origins.
          </p>
        </div>

        <div class="page-actions">
          <a href="#/map" class="btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/></svg>
            <span>View Probability Grid on Map</span>
          </a>
        </div>
      </div>

      <!-- Limitations Banner -->
      ${limitations.length > 0 ? `
        <div class="alert-box warn">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          <div>
            <strong>Scientific Limitations & Drift Caveats</strong>
            <ul>
              ${limitations.map(lim => `<li>${escapeHtml(lim)}</li>`).join('')}
            </ul>
          </div>
        </div>
      ` : ''}

      <!-- Interactive Temporal Hypotheses Scrubber -->
      ${hypotheses.length > 0 ? `
        <div class="timeline-scrubber">
          <div class="scrubber-header">
            <div>
              <span class="page-eyebrow">TEMPORAL DRIFT RECONSTRUCTION</span>
              <h3 style="margin-top:2px;">Origin Hypothesis at Step: ${currentHypo ? `${currentHypo.hours_before_observation}h before observation` : 'T_obs'}</h3>
            </div>
            <div class="scrubber-time-badge font-mono">
              ${currentHypo?.time_utc ? new Date(currentHypo.time_utc).toUTCString() : 'N/A'}
            </div>
          </div>

          <div class="scrubber-slider-wrap">
            <button id="btn-scrub-prev" class="btn-secondary btn-sm" ${scrubberIdx === 0 ? 'disabled' : ''}>← Step Forward</button>
            <input id="hypo-slider" type="range" class="scrubber-slider" min="0" max="${hypotheses.length - 1}" value="${scrubberIdx}">
            <button id="btn-scrub-next" class="btn-secondary btn-sm" ${scrubberIdx === hypotheses.length - 1 ? 'disabled' : ''}>Step Back →</button>
          </div>

          <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono);">
            <span>Observation ($T_{obs}$)</span>
            <span>Active Particles: ${currentHypo?.active_particles?.toLocaleString() || '8,526'}</span>
            <span>Maximum Backtrack ($T - ${bt.backtrack_hours || 69}h$)</span>
          </div>
        </div>
      ` : ''}

      <!-- Environmental Forcing & Simulation Parameters -->
      <div class="analytical-grid">
        <div class="col-6">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12h20M2 6h20M2 18h20"/></svg>
                <span>Hydrodynamic & Wind Forcing</span>
              </h3>
            </div>
            <div class="panel-body">
              <div class="dossier-grid">
                <div class="dossier-item">
                  <span class="dossier-key">Ocean Current Provider</span>
                  <span class="dossier-val">${escapeHtml(bt.current_forcing?.provider || 'CMEMS GLORYS12V1')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Current Velocity Vars</span>
                  <span class="dossier-val">uo, vo (0.083° daily reanalysis)</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Surface Wind Model</span>
                  <span class="dossier-val">${escapeHtml(bt.wind_forcing?.provider || 'ECMWF ERA5 (10m u/v)')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Landmask Database</span>
                  <span class="dossier-val">${escapeHtml(bt.landmask || 'GSHHG High Resolution')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Initial Seed Particles</span>
                  <span class="dossier-val">${bt.initial_seed_particles?.toLocaleString() || '8,600 particles'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Subsurface Oil Type</span>
                  <span class="dossier-val">${escapeHtml(bt.oil_type || 'GENERIC HEAVY CRUDE')}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-6">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span>Observation & Simulation Bounds</span>
              </h3>
            </div>
            <div class="panel-body">
              <div class="dossier-grid">
                <div class="dossier-item">
                  <span class="dossier-key">SAR Observation Time (T_obs)</span>
                  <span class="dossier-val">${obs.t_obs_utc ? new Date(obs.t_obs_utc).toUTCString() : 'N/A'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Simulation Window Start</span>
                  <span class="dossier-val">${simWin.start ? new Date(simWin.start).toUTCString() : 'N/A'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Simulation Window End</span>
                  <span class="dossier-val">${simWin.end ? new Date(simWin.end).toUTCString() : 'N/A'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Spatial Padding</span>
                  <span class="dossier-val">±2.0° Lon/Lat (Search Window AOI)</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Top Source Probability Grid Cells -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
            <span>Top Modeled Origin Probability Cells</span>
          </h3>
          <span class="page-eyebrow">${topCells.length} HIGH-PROBABILITY CELLS IDENTIFIED</span>
        </div>
        <div class="panel-body">
          ${topCells.length > 0 ? `
            <div class="table-container">
              <tech-table class="tech-table">
                <thead>
                  <tr>
                    <th>Timestamp (UTC)</th>
                    <th>Rank</th>
                    <th>Center Longitude</th>
                    <th>Center Latitude</th>
                    <th>Particle Count</th>
                    <th>Probability %</th>
                  </tr>
                </thead>
                <tbody>
                  ${topCells.slice(0, 15).map(cell => `
                    <tr>
                      <td class="font-mono">${cell.time_utc ? new Date(cell.time_utc).toISOString().replace('T', ' ').slice(0, 19) : 'N/A'}</td>
                      <td><span class="rank-pill">${cell.rank || 1}</span></td>
                      <td class="font-mono">${Number(cell.lon_center).toFixed(4)}°E</td>
                      <td class="font-mono">${Number(cell.lat_center).toFixed(4)}°N</td>
                      <td class="font-mono">${cell.particle_count ?? 'N/A'}</td>
                      <td class="font-mono" style="color:var(--cyan-accent); font-weight:700;">
                        ${(Number(cell.probability) * 100).toFixed(2)}%
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </tech-table>
            </div>
          ` : `
            <div class="empty-state" style="padding:var(--space-6);">
              <p>No backtracking probability cells imported yet. Import the stage 2 handoff directory below.</p>
            </div>
          `}
        </div>
      </div>

      <!-- Import Tool for Stage 2 -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Import Stage 2 Backtracking Outputs</span>
          </h3>
        </div>
        <div class="panel-body">
          <p style="font-size:0.82rem; margin-bottom:var(--space-3);">
            Enter a local directory containing generated Stage 2 handoff files (e.g. <code>sanchi_2018_stage2_handoff.json</code>, <code>sanchi_2018_source_probability.geojson</code>).
          </p>
          <div style="display:flex; gap:var(--space-2);">
            <input id="stage2-import-path" type="text" class="font-mono" placeholder="C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw" value="C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw">
            <button id="btn-stage2-import" class="btn-primary">Import Stage 2 Handoff</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Bind slider & step buttons
  const slider = container.querySelector('#hypo-slider');
  if (slider) {
    slider.oninput = (e) => {
      store.setScrubberIndex(parseInt(e.target.value, 10));
    };
  }

  const prevBtn = container.querySelector('#btn-scrub-prev');
  if (prevBtn) {
    prevBtn.onclick = () => {
      if (scrubberIdx > 0) store.setScrubberIndex(scrubberIdx - 1);
    };
  }

  const nextBtn = container.querySelector('#btn-scrub-next');
  if (nextBtn) {
    nextBtn.onclick = () => {
      if (scrubberIdx < hypotheses.length - 1) store.setScrubberIndex(scrubberIdx + 1);
    };
  }

  // Bind Stage 2 Import
  const importBtn = container.querySelector('#btn-stage2-import');
  if (importBtn) {
    importBtn.onclick = async () => {
      const pathInput = container.querySelector('#stage2-import-path');
      const dirPath = pathInput.value.trim();
      if (!dirPath) return;

      importBtn.disabled = true;
      importBtn.innerHTML = '<span class="spinner"></span> Importing...';
      try {
        await Api.runStage(event.event_id, 'stage2', { mode: 'replay', existing_output_dir: dirPath });
        const refreshed = await Api.getInvestigation(event.event_id);
        store.setCurrentEvent(refreshed);
        const s2Sum = await Api.getStageSummary(event.event_id, 2);
        store.setStageSummary('stage2', s2Sum.summary);
      } catch (err) {
        alert(`Import failed: ${err.message}`);
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = 'Import Stage 2 Handoff';
      }
    };
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
