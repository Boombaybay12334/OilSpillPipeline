/**
 * Stage 2 Component — Oceanographic Lagrangian Backtracking & Origin Hypotheses
 */
import { store } from '../state.js';
import { Api } from '../api.js';
import { getInvestigationPaths } from '../path_settings.js';

let backtrackingMap = null;

export function renderStage2(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const paths = event ? getInvestigationPaths(event.event_id) : getInvestigationPaths('');
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

      <!-- Temporal Origin Reconstruction -->
      ${hypotheses.length > 0 ? `
        <div class="backtracking-visualization panel">
          <div class="panel-header">
            <div>
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 17l6-6 4 4 8-9"/><circle cx="3" cy="17" r="2"/><circle cx="9" cy="11" r="2"/><circle cx="13" cy="15" r="2"/><circle cx="21" cy="6" r="2"/></svg>
                <span>Backtracked Origin Drift</span>
              </h3>
              <span class="page-eyebrow">${hypotheses.length} MODELED TIMESTEPS · PATH OF MOST PROBABLE CELLS</span>
            </div>
            <div class="backtracking-map-legend">
              <span><i class="legend-line"></i> probable drift path</span>
              <span><i class="legend-dot"></i> timestep</span>
              <span><i class="legend-box"></i> 90% envelope</span>
            </div>
          </div>
          <div id="stage2-backtracking-map" class="backtracking-map"></div>
          <div class="backtracking-map-caption">
            <span>Each marker is the highest-probability cell at a saved timestep. Marker size reflects active particles.</span>
            <span class="font-mono">${formatHours(hypotheses[0]?.hours_before_observation)} to ${formatHours(hypotheses[hypotheses.length - 1]?.hours_before_observation)} before T_obs</span>
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
            <input id="stage2-import-path" type="text" class="font-mono" placeholder="${escapeHtml(paths.stage2)}" value="${escapeHtml(paths.stage2)}">
            <button id="btn-stage2-import" class="btn-primary">Import Stage 2 Handoff</button>
          </div>
        </div>
      </div>
    </div>
  `;

  if (hypotheses.length > 0) {
    setTimeout(() => renderBacktrackingMap(hypotheses), 50);
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

function formatHours(hours) {
  return Number.isFinite(Number(hours)) ? `${Number(hours).toFixed(0)}h` : 'N/A';
}

function renderBacktrackingMap(hypotheses) {
  const mapEl = document.getElementById('stage2-backtracking-map');
  if (!mapEl || !window.L) return;

  if (backtrackingMap) {
    backtrackingMap.remove();
    backtrackingMap = null;
  }

  const points = hypotheses.map((hypothesis, index) => {
    const cell = hypothesis.top_cells?.[0];
    if (!cell || !Number.isFinite(Number(cell.lat_center)) || !Number.isFinite(Number(cell.lon_center))) return null;
    return {
      index,
      lat: Number(cell.lat_center),
      lon: Number(cell.lon_center),
      probability: Number(cell.probability || 0),
      particles: Number(hypothesis.active_particles || 0),
      hours: hypothesis.hours_before_observation,
      time: hypothesis.time_utc,
    };
  }).filter(Boolean);

  if (!points.length) return;

  backtrackingMap = window.L.map(mapEl, { zoomControl: true, attributionControl: true });
  window.L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 18,
  }).addTo(backtrackingMap);

  const path = points.map(point => [point.lat, point.lon]);
  window.L.polyline(path, { color: '#00e5c9', weight: 2, opacity: 0.75, dashArray: '5, 7' }).addTo(backtrackingMap);

  points.forEach((point, index) => {
    const radius = Math.max(5, Math.min(14, 5 + Math.sqrt(point.particles / 100)));
    window.L.circleMarker([point.lat, point.lon], {
      radius,
      color: index === 0 ? '#f59e0b' : '#00e5c9',
      weight: index === 0 ? 2 : 1,
      fillColor: index === 0 ? '#f59e0b' : '#00e5c9',
      fillOpacity: 0.75,
    }).bindPopup(`
      <div class="map-popup-header">${index === 0 ? 'EARLIEST MODELED ORIGIN' : 'BACKTRACK TIMESTEP'}</div>
      <div class="map-popup-grid">
        <span>Time:</span><span>${point.time ? new Date(point.time).toUTCString() : 'N/A'}</span>
        <span>Before T_obs:</span><span>${formatHours(point.hours)}</span>
        <span>Probability:</span><span>${(point.probability * 100).toFixed(2)}%</span>
        <span>Active particles:</span><span>${point.particles.toLocaleString()}</span>
      </div>
    `).addTo(backtrackingMap);
  });

  const envelope = hypotheses.reduce((widest, hypothesis) => {
    const coverage = hypothesis.coverage_thresholds?.find(item => Number(item.threshold) === 0.9);
    if (!coverage?.bbox_wsen || coverage.bbox_wsen.length !== 4) return widest;
    const [west, south, east, north] = coverage.bbox_wsen.map(Number);
    const area = Math.abs((east - west) * (north - south));
    return !widest || area > widest.area ? { bounds: [[south, west], [north, east]], area } : widest;
  }, null);

  const bounds = window.L.latLngBounds(points.map(point => [point.lat, point.lon]));
  if (envelope) {
    window.L.rectangle(envelope.bounds, {
      color: '#f59e0b',
      weight: 1,
      dashArray: '4, 5',
      fillColor: '#f59e0b',
      fillOpacity: 0.06,
    }).bindTooltip('Widest 90% probability envelope').addTo(backtrackingMap);
    bounds.extend(envelope.bounds);
  }
  backtrackingMap.fitBounds(bounds, { padding: [24, 24] });
}
