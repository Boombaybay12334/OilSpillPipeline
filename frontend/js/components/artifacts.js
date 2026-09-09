/**
 * Artifacts Component — Manifest Explorer & Secure Downloads
 */
import { store } from '../state.js';
import { Api } from '../api.js';

let selectedCategory = 'all';
let searchQuery = '';

export function renderArtifacts(container) {
  const state = store.getState();
  const event = state.currentEvent;

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  const allArtifacts = (event.manifest?.artifacts || []).filter(a => !isIgnored(a.relative_path));

  // Filter by category and search
  const filtered = allArtifacts.filter(art => {
    if (selectedCategory !== 'all') {
      if (selectedCategory.startsWith('stage')) {
        if (art.stage !== selectedCategory) return false;
      } else if (art.category !== selectedCategory) {
        return false;
      }
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return art.label.toLowerCase().includes(q) || art.relative_path.toLowerCase().includes(q);
    }
    return true;
  });

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">AUDITABLE INVESTIGATION MANIFEST</span>
          <h2 class="page-title">Artifacts & Scientific Downloads</h2>
          <p class="page-desc">
            Complete inventory of imported and derived GeoTIFF rasters, NetCDF trajectory sets, GeoJSON vector layers, and JSON analytical handoffs with cryptographic SHA-256 checksums.
          </p>
        </div>

        <div class="page-actions">
          <button id="btn-discover-artifacts" class="btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
            <span>Scan & Discover Artifacts</span>
          </button>
        </div>
      </div>

      <!-- Filters & Category Chips -->
      <div class="panel">
        <div class="panel-body" style="display:flex; flex-direction:column; gap:var(--space-3);">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:var(--space-3); flex-wrap:wrap;">
            <div style="display:flex; gap:6px; flex-wrap:wrap;">
              ${renderCategoryPill('all', 'All Files', allArtifacts.length)}
              ${renderCategoryPill('stage1', 'Stage 1 (SAR)', allArtifacts.filter(a => a.stage === 'stage1').length)}
              ${renderCategoryPill('stage2', 'Stage 2 (Drift)', allArtifacts.filter(a => a.stage === 'stage2').length)}
              ${renderCategoryPill('stage3', 'Stage 3 (AIS)', allArtifacts.filter(a => a.stage === 'stage3').length)}
              ${renderCategoryPill('raster_quickview', 'Quickviews', allArtifacts.filter(a => a.category === 'raster_quickview').length)}
              ${renderCategoryPill('geojson', 'GeoJSON', allArtifacts.filter(a => a.category === 'geojson' || a.label.includes('GeoJSON')).length)}
              ${renderCategoryPill('report', 'Reports & JSON', allArtifacts.filter(a => a.category === 'report' || a.category === 'stage_handoff').length)}
              ${renderCategoryPill('raster_source', 'Raw GeoTIFFs', allArtifacts.filter(a => a.category === 'raster_source').length)}
            </div>

            <div style="width:240px;">
              <input id="artifact-search" type="text" placeholder="Filter by name / path..." value="${escapeHtml(searchQuery)}">
            </div>
          </div>
        </div>
      </div>

      <!-- Artifacts Table -->
      <div class="panel">
        <div class="panel-header">
          <h3>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
            <span>Manifest Inventory (${filtered.length} items)</span>
          </h3>
        </div>
        <div class="panel-body" style="padding:0;">
          ${filtered.length > 0 ? `
            <div class="table-container" style="border:none;">
              <table class="tech-table">
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Category</th>
                    <th>Label & Relative Path</th>
                    <th>Size</th>
                    <th>SHA-256 Checksum</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  ${filtered.map(art => `
                    <tr>
                      <td>
                        <span class="rank-pill font-mono">${art.stage.toUpperCase()}</span>
                      </td>
                      <td>
                        <span class="vessel-flag-tag">${escapeHtml(art.category)}</span>
                      </td>
                      <td>
                        <strong style="color:var(--text-primary); display:block;">${escapeHtml(art.label)}</strong>
                        <small class="font-mono" style="color:var(--text-muted);">${escapeHtml(art.relative_path)}</small>
                      </td>
                      <td class="font-mono">${formatBytes(art.size_bytes)}</td>
                      <td class="font-mono" style="color:var(--text-muted); font-size:0.7rem;">
                        ${art.sha256 ? `${art.sha256.slice(0, 10)}...${art.sha256.slice(-8)}` : 'N/A'}
                      </td>
                      <td>
                        <div style="display:flex; gap:6px;">
                          <a href="${Api.getArtifactUrl(event.event_id, art.artifact_id)}" target="_blank" class="btn-secondary btn-sm" download>
                            Download
                          </a>
                          ${isTextOrJson(art) ? `
                            <button class="btn-secondary btn-sm btn-preview-text" data-artifact-id="${art.artifact_id}" data-label="${escapeHtml(art.label)}">
                              Preview
                            </button>
                          ` : ''}
                        </div>
                      </td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          ` : `
            <div class="empty-state" style="padding:var(--space-6);">
              <p>No artifacts match the selected category or filter.</p>
            </div>
          `}
        </div>
      </div>
    </div>
  `;

  // Bind category pills
  container.querySelectorAll('.category-pill').forEach(pill => {
    pill.onclick = () => {
      selectedCategory = pill.dataset.cat;
      renderArtifacts(container);
    };
  });

  // Bind search input
  const searchInput = container.querySelector('#artifact-search');
  if (searchInput) {
    searchInput.oninput = (e) => {
      searchQuery = e.target.value;
      renderArtifacts(container);
    };
  }

  // Bind Discover Artifacts button
  const discBtn = container.querySelector('#btn-discover-artifacts');
  if (discBtn) {
    discBtn.onclick = async () => {
      discBtn.disabled = true;
      discBtn.innerHTML = '<span class="spinner"></span> Scanning...';
      try {
        await Api.discoverArtifacts(event.event_id);
        const refreshed = await Api.getInvestigation(event.event_id);
        store.setCurrentEvent(refreshed);
        renderArtifacts(container);
      } catch (err) {
        alert(`Artifact discovery failed: ${err.message}`);
      } finally {
        discBtn.disabled = false;
        discBtn.textContent = 'Scan & Discover Artifacts';
      }
    };
  }

  // Bind Text/JSON preview buttons
  container.querySelectorAll('.btn-preview-text').forEach(btn => {
    btn.onclick = async () => {
      const artId = btn.dataset.artifactId;
      const label = btn.dataset.label;
      openJsonPreviewModal(event.event_id, artId, label);
    };
  });
}

function renderCategoryPill(key, label, count) {
  const active = selectedCategory === key;
  return `
    <button class="category-pill btn-secondary btn-sm ${active ? 'btn-primary' : ''}" data-cat="${key}" style="font-size:0.75rem;">
      ${label} (${count})
    </button>
  `;
}

async function openJsonPreviewModal(eventId, artifactId, label) {
  let modal = document.getElementById('preview-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'preview-modal';
    modal.className = 'modal-backdrop';
    document.body.appendChild(modal);
  }

  modal.innerHTML = `
    <div class="modal-dialog" style="max-width:850px;">
      <div class="modal-header">
        <div>
          <h3 style="margin:0;">Artifact Preview</h3>
          <small class="font-mono">${escapeHtml(label)}</small>
        </div>
        <button id="btn-close-preview" class="btn-secondary btn-sm" style="padding:4px 8px;">✕</button>
      </div>
      <div class="modal-body" style="max-height:500px; padding:var(--space-3);">
        <pre id="preview-code-block" style="background:var(--bg-void); padding:var(--space-3); border:1px solid var(--border-subtle); border-radius:var(--radius-xs); color:#38efd8; font-family:var(--font-mono); font-size:0.78rem; overflow:auto; max-height:450px;">Loading contents...</pre>
      </div>
    </div>
  `;

  modal.style.display = 'grid';
  modal.querySelector('#btn-close-preview').onclick = () => { modal.style.display = 'none'; };
  modal.onclick = (e) => { if (e.target === modal) modal.style.display = 'none'; };

  try {
    const data = await Api.getArtifact(eventId, artifactId);
    const codeEl = modal.querySelector('#preview-code-block');
    if (codeEl) {
      codeEl.textContent = typeof data === 'object' ? JSON.stringify(data, null, 2) : String(data);
    }
  } catch (err) {
    const codeEl = modal.querySelector('#preview-code-block');
    if (codeEl) codeEl.textContent = `Error loading preview: ${err.message}`;
  }
}

function isTextOrJson(art) {
  const mime = art.mime_type || '';
  const path = art.relative_path || '';
  return mime.includes('json') || mime.includes('text') || path.endsWith('.json') || path.endsWith('.geojson') || path.endsWith('.txt') || path.endsWith('.log') || path.endsWith('.py');
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function isIgnored(path) {
  return /(^|[\\/])(thumbnail|thumb)[^\\/]*\./i.test(path) || /(^|[\\/])(?:thumbnail|thumb)(?:[\\/]|$)/i.test(path) || /(^|[\\/])(?:quick-look|logo)\.png$/i.test(path);
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
