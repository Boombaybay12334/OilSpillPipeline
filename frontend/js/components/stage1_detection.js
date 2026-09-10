/**
 * Stage 1 Component — SAR Oil Spill Detection & Raster Quickviews
 */
import { store } from '../state.js';
import { Api } from '../api.js';
import { getInvestigationPaths } from '../path_settings.js';
import { openImageryModal } from './imagery_viewer.js';

export function renderStage1(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const paths = event ? getInvestigationPaths(event.event_id) : getInvestigationPaths('');
  const summary = state.stageSummaries.stage1;
  const artifacts = (event?.manifest?.artifacts || []).filter(a => a.stage === 'stage1' && !isIgnored(a.relative_path));

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  const meta = summary?.metadata || {};
  const detSummary = summary?.detection_summary || {};
  const regionCount = summary?.region_count ?? detSummary.n_regions ?? 0;
  const totalArea = detSummary.total_oil_area_km2 ?? 0;

  // Find quickviews
  const quickviews = artifacts.filter(a => a.category === 'raster_quickview' || a.category === 'image');

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">STAGE 01 · RADAR SURVEILLANCE & SEGMENTATION</span>
          <h2 class="page-title">SAR Oil-Spill Detection</h2>
          <p class="page-desc">
            Sentinel-1 synthetic aperture radar (SAR) backscatter preprocessing, CFAR candidate filtering, and deep-learning semantic segmentation.
          </p>
        </div>

        <div class="page-actions">
          <button id="btn-gen-quickviews" class="btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            <span>Derive Presentation Quickviews</span>
          </button>
        </div>
      </div>

      <!-- Quickviews Presentation Gallery -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M20.4 14.5L16 10 4 20"/></svg>
            <span>Presentation-Ready Satellite Quickviews</span>
          </h3>
          <span class="page-eyebrow">CLICK IMAGE TO INSPECT WITH HIGH-RESOLUTION ZOOM</span>
        </div>
        <div class="panel-body">
          ${quickviews.length > 0 ? `
            <div class="imagery-gallery">
              ${quickviews.map(art => `
                <div class="raster-card" data-artifact-id="${art.artifact_id}">
                  <div class="raster-preview-wrap">
                    <img src="${Api.getArtifactUrl(event.event_id, art.artifact_id)}" alt="${escapeHtml(art.label)}" class="raster-img">
                    <span class="raster-overlay-badge">${escapeHtml(art.label)}</span>
                  </div>
                  <div class="raster-info">
                    <div class="raster-title">${escapeHtml(art.label)}</div>
                    <div class="raster-meta">${escapeHtml(art.relative_path.split('/').pop())} · ${(art.size_bytes / 1024).toFixed(1)} KB</div>
                  </div>
                  <div class="raster-actions">
                    <button class="btn-secondary btn-sm btn-inspect-raster" data-artifact-id="${art.artifact_id}">
                      Inspect Zoom & Details
                    </button>
                    <a href="${Api.getArtifactUrl(event.event_id, art.artifact_id)}" target="_blank" class="btn-secondary btn-sm">
                      Raw View ↗
                    </a>
                  </div>
                </div>
              `).join('')}
            </div>
          ` : `
            <div class="empty-state" style="padding:var(--space-6);">
              <p>No presentation raster quickviews generated yet. Source TIFFs are preserved; click 'Derive Presentation Quickviews' to render display PNGs.</p>
            </div>
          `}
        </div>
      </div>

      <!-- Scene Dossier & Detection Summary Grid -->
      <div class="analytical-grid">
        <div class="col-6">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                <span>SAR Scene Metadata</span>
              </h3>
            </div>
            <div class="panel-body">
              <div class="dossier-grid">
                <div class="dossier-item">
                  <span class="dossier-key">Catalog Scene ID</span>
                  <span class="dossier-val">${escapeHtml(meta.catalog_id || 'N/A')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Acquisition Start</span>
                  <span class="dossier-val">${meta.acquisition_start ? new Date(meta.acquisition_start).toUTCString() : 'N/A'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Acquisition Stop</span>
                  <span class="dossier-val">${meta.acquisition_stop ? new Date(meta.acquisition_stop).toUTCString() : 'N/A'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Orbit Pass</span>
                  <span class="dossier-val">${escapeHtml(meta.orbit_state || 'Ascending')}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Polarisation Mode</span>
                  <span class="dossier-val">VV + VH Dual-Pol</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Source Verification</span>
                  <span class="dossier-val">${escapeHtml(meta.acquisition_time_source || 'manifest.safe')}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-6">
          <div class="panel">
            <div class="panel-header">
              <h3>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
                <span>Detection & Morphology Summary</span>
              </h3>
            </div>
            <div class="panel-body">
              <div class="dossier-grid">
                <div class="dossier-item">
                  <span class="dossier-key">Detected Slicks</span>
                  <span class="dossier-val" style="color:var(--cyan-accent); font-weight:700;">${regionCount} regions</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Total Estimated Area</span>
                  <span class="dossier-val" style="color:var(--cyan-accent); font-weight:700;">${Number(totalArea).toFixed(2)} km²</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">CFAR Prefilter</span>
                  <span class="dossier-val">${detSummary.cfar_prefilter_used ? `Active (k = ${detSummary.cfar_k ?? 2.5})` : 'Standard pass'}</span>
                </div>
                <div class="dossier-item">
                  <span class="dossier-key">Segmentation Model</span>
                  <span class="dossier-val">U-Net Sigma0 Binary Classifier</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Replay & Output Folder Import Tool -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            <span>Import Stage 1 Detection Outputs</span>
          </h3>
        </div>
        <div class="panel-body">
          <p style="font-size:0.82rem; margin-bottom:var(--space-3);">
            Enter a local directory containing generated Stage 1 files (e.g., <code>detection_report.json</code>, <code>oil_regions.geojson</code>, <code>sigma0_vv_vh.tif</code>, <code>oil_mask_prob.tif</code>). Files are copied safely into the investigation sandbox.
          </p>
          <div style="display:flex; gap:var(--space-2);">
            <input id="stage1-import-path" type="text" class="font-mono" placeholder="${escapeHtml(paths.stage1)}" value="${escapeHtml(paths.stage1)}">
            <button id="btn-stage1-import" class="btn-primary">Import Folder</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Bind Quickview generator
  const genBtn = container.querySelector('#btn-gen-quickviews');
  if (genBtn) {
    genBtn.onclick = async () => {
      genBtn.disabled = true;
      genBtn.innerHTML = '<span class="spinner"></span> Processing...';
      try {
        await Api.generateQuickviews(event.event_id, 'stage1');
        const refreshed = await Api.getInvestigation(event.event_id);
        store.setCurrentEvent(refreshed);
        const s1Sum = await Api.getStageSummary(event.event_id, 1);
        store.setStageSummary('stage1', s1Sum.summary);
      } catch (err) {
        alert(`Quickview generation failed: ${err.message}`);
      } finally {
        genBtn.disabled = false;
        genBtn.textContent = 'Derive Presentation Quickviews';
      }
    };
  }

  // Bind Import
  const importBtn = container.querySelector('#btn-stage1-import');
  if (importBtn) {
    importBtn.onclick = async () => {
      const pathInput = container.querySelector('#stage1-import-path');
      const dirPath = pathInput.value.trim();
      if (!dirPath) return;

      importBtn.disabled = true;
      importBtn.innerHTML = '<span class="spinner"></span> Importing...';
      try {
        await Api.runStage(event.event_id, 'stage1', { mode: 'replay', existing_output_dir: dirPath });
        const refreshed = await Api.getInvestigation(event.event_id);
        store.setCurrentEvent(refreshed);
        const s1Sum = await Api.getStageSummary(event.event_id, 1);
        store.setStageSummary('stage1', s1Sum.summary);
      } catch (err) {
        alert(`Import failed: ${err.message}`);
      } finally {
        importBtn.disabled = false;
        importBtn.textContent = 'Import Folder';
      }
    };
  }

  // Bind Quickview zoom inspect clicks
  container.querySelectorAll('.btn-inspect-raster, .raster-preview-wrap').forEach(el => {
    el.onclick = () => {
      const card = el.closest('.raster-card');
      const artId = card?.dataset.artifactId;
      if (artId) openImageryModal(event.event_id, artId);
    };
  });
}

function isIgnored(path) {
  return /(^|[\\/])(thumbnail|thumb)[^\\/]*\./i.test(path) || /(^|[\\/])(?:thumbnail|thumb)(?:[\\/]|$)/i.test(path) || /(^|[\\/])(?:quick-look|logo)\.png$/i.test(path);
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
