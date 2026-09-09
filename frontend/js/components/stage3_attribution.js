/**
 * Stage 3 Component — AIS Vessel Attribution & Candidate Ranking Evidence
 */
import { store } from '../state.js';
import { Api } from '../api.js';

export function renderStage3(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const summary = state.stageSummaries.stage3;

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  const candidates = summary?.candidates || [];
  const disclaimer = summary?.disclaimer || "Investigative candidates only. A ranking reflects compatibility with modeled source probability and available AIS evidence; it is not proof of responsibility.";
  
  const selectedShip = state.selectedCandidate || candidates[0] || null;

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">STAGE 03 · AIS VESSEL ATTRIBUTION</span>
          <h2 class="page-title">Vessel Compatibility Ranking</h2>
          <p class="page-desc">
            Multi-hypothesis spatio-temporal correlation of Global Fishing Watch AIS vessel trajectories against modeled Lagrangian oil slick origin probabilities.
          </p>
        </div>

        <div class="page-actions">
          <a href="#/map" class="btn-primary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>
            <span>Plot Candidates on Map</span>
          </a>
        </div>
      </div>

      <!-- Non-Culpability Disclaimer Alert -->
      <div class="alert-box info">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        <div>
          <strong>Investigative Intelligence Disclaimer</strong>
          <p style="margin-top:2px; font-size:0.8rem; color:#bae6fd;">
            ${escapeHtml(disclaimer)}
          </p>
        </div>
      </div>

      <!-- Candidate Ranking & Detailed Evidence Dossier -->
      <div class="analytical-grid">
        <!-- Left: Ranked Candidates List -->
        <div class="col-5">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
                <span>Ranked Vessel Candidates (${candidates.length})</span>
              </h3>
              <span class="page-eyebrow">SELECT TO INSPECT</span>
            </div>
            <div class="panel-body">
              ${candidates.length > 0 ? `
                <div class="candidates-list">
                  ${candidates.map(ship => {
                    const isSelected = selectedShip && (selectedShip.mmsi === ship.mmsi || selectedShip.rank === ship.rank);
                    return `
                      <div class="candidate-card ${isSelected ? 'selected' : ''}" data-mmsi="${ship.mmsi}" data-rank="${ship.rank}">
                        <div class="candidate-card-top">
                          <div class="candidate-rank-name">
                            <span class="rank-pill">${String(ship.rank).padStart(2, '0')}</span>
                            <span class="vessel-name">${escapeHtml(ship.name || 'UNKNOWN IDENTITY')}</span>
                            ${ship.flag ? `<span class="vessel-flag-tag">${escapeHtml(ship.flag)}</span>` : ''}
                          </div>
                          <span class="candidate-score-val">${(ship.score * 100).toFixed(2)}%</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono);">
                          <span>MMSI: ${escapeHtml(ship.mmsi || 'N/A')}</span>
                          <span>Dist: ${ship.best_distance_km ? `${Number(ship.best_distance_km).toFixed(1)} km` : 'N/A'}</span>
                          <span>Coverage: ${Number(ship.coverage_percent || 0).toFixed(0)}%</span>
                        </div>
                      </div>
                    `;
                  }).join('')}
                </div>
              ` : `
                <div class="empty-state" style="padding:var(--space-6);">
                  <p>No vessel attribution candidates imported yet. Import the Stage 3 output folder below.</p>
                </div>
              `}
            </div>
          </div>
        </div>

        <!-- Right: Selected Candidate Evidence Dossier -->
        <div class="col-7">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                <span>Attribution Evidence & Score Breakdown</span>
              </h3>
              ${selectedShip ? `
                <span class="page-eyebrow font-mono" style="color:var(--cyan-accent);">
                  RANK #${selectedShip.rank} CANDIDATE
                </span>
              ` : ''}
            </div>
            <div class="panel-body">
              ${selectedShip ? `
                <div style="display:flex; flex-direction:column; gap:var(--space-4);">
                  <!-- Vessel Identity Header -->
                  <div style="display:flex; justify-content:space-between; align-items:flex-start; padding-bottom:var(--space-3); border-bottom:1px solid var(--border-hairline);">
                    <div>
                      <h3 style="font-size:1.3rem; margin:0; color:var(--text-primary);">
                        ${escapeHtml(selectedShip.name || 'UNKNOWN VESSEL NAME')}
                      </h3>
                      <div style="display:flex; gap:var(--space-2); margin-top:4px;" class="font-mono">
                        <span>MMSI: <strong>${escapeHtml(selectedShip.mmsi || 'N/A')}</strong></span>
                        <span>·</span>
                        <span>IMO: <strong>${escapeHtml(selectedShip.imo || 'N/A')}</strong></span>
                        <span>·</span>
                        <span>CALLSIGN: <strong>${escapeHtml(selectedShip.callsign || 'N/A')}</strong></span>
                      </div>
                    </div>

                    <div style="text-align:right;">
                      <div class="candidate-score-val" style="font-size:1.6rem;">
                        ${(selectedShip.score * 100).toFixed(2)}%
                      </div>
                      <small style="display:block; color:var(--text-muted); font-family:var(--font-mono);">
                        Final Attribution Score
                      </small>
                    </div>
                  </div>

                  <!-- Evidence Breakdown Bars -->
                  <div class="metric-bars-group">
                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>Spatial Origin Compatibility</span>
                        <span>${Number(selectedShip.spatial_compatibility * 100).toFixed(2)}% (Peak: ${Number((selectedShip.best_spatial_compatibility || 0) * 100).toFixed(2)}%)</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, (selectedShip.spatial_compatibility || 0) * 100)}%;"></div>
                      </div>
                    </div>

                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>AIS Signal Temporal Coverage</span>
                        <span>${Number(selectedShip.coverage_percent || 0).toFixed(1)}% (${selectedShip.matched_hours || 0} / ${selectedShip.modeled_hours || 70} hrs)</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, selectedShip.coverage_percent || 0)}%;"></div>
                      </div>
                    </div>

                    <div class="metric-bar-item">
                      <div class="metric-bar-header">
                        <span>Trajectory Consistency</span>
                        <span>${Number((selectedShip.trajectory_consistency || 1) * 100).toFixed(0)}%</span>
                      </div>
                      <div class="metric-bar-track">
                        <div class="metric-bar-fill" style="width:${Math.min(100, (selectedShip.trajectory_consistency || 1) * 100)}%;"></div>
                      </div>
                    </div>
                  </div>

                  <!-- Spatial Proximity & Navigation Profile -->
                  <div class="dossier-grid">
                    <div class="dossier-item">
                      <span class="dossier-key">Closest Distance to Origin Cell</span>
                      <span class="dossier-val" style="color:var(--cyan-accent); font-weight:700;">
                        ${selectedShip.best_distance_km ? `${Number(selectedShip.best_distance_km).toFixed(2)} km` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Mean Distance Over Window</span>
                      <span class="dossier-val">
                        ${selectedShip.best_mean_distance_km ? `${Number(selectedShip.best_mean_distance_km).toFixed(1)} km` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Best Match Timestamp</span>
                      <span class="dossier-val">
                        ${selectedShip.best_match_time_utc ? new Date(selectedShip.best_match_time_utc).toUTCString() : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Best Match Coordinates</span>
                      <span class="dossier-val">
                        ${selectedShip.best_match_lat ? `${Number(selectedShip.best_match_lat).toFixed(4)}°N, ${Number(selectedShip.best_match_lon).toFixed(4)}°E` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Mean Vessel Speed</span>
                      <span class="dossier-val">
                        ${selectedShip.mean_speed_knots !== undefined ? `${Number(selectedShip.mean_speed_knots).toFixed(2)} knots` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Maximum Vessel Speed</span>
                      <span class="dossier-val">
                        ${selectedShip.max_speed_knots !== undefined ? `${Number(selectedShip.max_speed_knots).toFixed(2)} knots` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Continuous AIS Window</span>
                      <span class="dossier-val">
                        ${selectedShip.longest_consecutive_match_hours ? `${selectedShip.longest_consecutive_match_hours} consecutive hrs` : 'N/A'}
                      </span>
                    </div>
                    <div class="dossier-item">
                      <span class="dossier-key">Flag State</span>
                      <span class="dossier-val">${escapeHtml(selectedShip.flag || 'Unspecified')}</span>
                    </div>
                  </div>

                  <div style="display:flex; justify-content:flex-end;">
                    <button id="btn-focus-candidate-map" class="btn-primary">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
                      <span>Focus Vessel on Geospatial Map →</span>
                    </button>
                  </div>
                </div>
              ` : `
                <div class="empty-state">
                  <p>Select a candidate vessel from the left to inspect its attribution evidence dossier.</p>
                </div>
              `}
            </div>
          </div>
        </div>
      </div>

      <!-- Import Tool for Stage 3 -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Import Stage 3 Attribution Outputs</span>
          </h3>
        </div>
        <div class="panel-body">
          <p style="font-size:0.82rem; margin-bottom:var(--space-3);">
            Enter a local directory containing generated Stage 3 attribution files (e.g. <code>sanchi_2018_final_ships.json</code>, <code>sanchi_2018_ais_attribution.json</code>).
          </p>
          <div style="display:flex; gap:var(--space-2);">
            <input id="stage3-import-path" type="text" class="font-mono" placeholder="C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw\\ais_attribution_output" value="C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw\\ais_attribution_output">
            <button id="btn-stage3-import" class="btn-primary">Import Stage 3 Ranking</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Bind Candidate clicks
  container.querySelectorAll('.candidate-card').forEach(card => {
    card.onclick = () => {
      const mmsi = card.dataset.mmsi;
      const rank = parseInt(card.dataset.rank, 10);
      const ship = candidates.find(c => c.mmsi === mmsi || c.rank === rank);
      if (ship) {
        store.setSelectedCandidate(ship);
        renderStage3(container);
      }
    };
  });

  // Bind Focus on map
  const focusBtn = container.querySelector('#btn-focus-candidate-map');
  if (focusBtn && selectedShip) {
    focusBtn.onclick = () => {
      store.setSelectedCandidate(selectedShip);
      location.hash = '#/map';
    };
  }

  // Bind Stage 3 Import
  const importBtn = container.querySelector('#btn-stage3-import');
  if (importBtn) {
    importBtn.onclick = async () => {
      const pathInput = container.querySelector('#stage3-import-path');
      const dirPath = pathInput.value.trim();
      if (!dirPath) return;

      importBtn.disabled = true;
      importBtn.innerHTML = '<span class="spinner"></span> Importing...';
      try {
        await Api.runStage(event.event_id, 'stage3', { mode: 'replay', existing_output_dir: dirPath });
        const refreshed = await Api.getInvestigation(event.event_id);
        store.setCurrentEvent(refreshed);
        const s3Sum = await Api.getStageSummary(event.event_id, 3);
        store.setStageSummary('stage3', s3Sum.summary);
      } catch (err) {
        alert(`Import failed: ${err.message}`);
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = 'Import Stage 3 Ranking';
      }
    };
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
