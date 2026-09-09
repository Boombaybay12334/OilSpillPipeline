/**
 * Imagery Viewer Component — High-Resolution Raster Zoom & Sidecar Metadata
 */
import { Api } from '../api.js';

let currentZoom = 1;

export async function openImageryModal(eventId, artifactId) {
  let modal = document.getElementById('imagery-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'imagery-modal';
    modal.className = 'modal-backdrop';
    document.body.appendChild(modal);
  }

  currentZoom = 1;
  const artifactUrl = Api.getArtifactUrl(eventId, artifactId);

  // Fetch metadata if available
  let meta = null;
  try {
    meta = await Api.getArtifactMetadata(eventId, artifactId);
  } catch {
    // optional
  }

  modal.innerHTML = `
    <div class="modal-dialog imagery-modal-dialog">
      <div class="modal-header">
        <div>
          <h3 style="margin:0;">Satellite Raster Inspector</h3>
          <small class="font-mono">${meta ? escapeHtml(meta.relative_path) : 'High-Resolution Quickview'}</small>
        </div>
        <button id="btn-close-imagery" class="btn-secondary btn-sm" style="padding:4px 8px;">✕</button>
      </div>

      <div class="modal-body" style="padding:var(--space-3);">
        <div class="raster-inspector-viewport">
          <img id="inspector-img" src="${artifactUrl}" alt="Satellite Raster Quickview" style="transform: scale(1);">
        </div>

        <div class="inspector-controls-bar">
          <div style="display:flex; gap:var(--space-2);">
            <button id="btn-zoom-in" class="btn-secondary btn-sm">Zoom +</button>
            <button id="btn-zoom-out" class="btn-secondary btn-sm">Zoom −</button>
            <button id="btn-zoom-reset" class="btn-secondary btn-sm">Reset (100%)</button>
          </div>

          <div style="display:flex; gap:var(--space-3); font-family:var(--font-mono); font-size:0.75rem; color:var(--text-muted);">
            <span>ZOOM: <strong id="zoom-readout" style="color:var(--text-primary);">100%</strong></span>
            <span>FORMAT: <strong style="color:var(--text-primary);">${meta?.mime_type || 'image/png'}</strong></span>
            <span>SIZE: <strong style="color:var(--text-primary);">${meta?.size_bytes ? `${(meta.size_bytes / 1024).toFixed(1)} KB` : 'N/A'}</strong></span>
          </div>

          <a href="${artifactUrl}" target="_blank" download class="btn-primary btn-sm">
            Download PNG
          </a>
        </div>
      </div>
    </div>
  `;

  modal.style.display = 'grid';

  const imgEl = modal.querySelector('#inspector-img');
  const zoomReadout = modal.querySelector('#zoom-readout');

  const updateZoom = (z) => {
    currentZoom = Math.min(4, Math.max(0.5, z));
    if (imgEl) imgEl.style.transform = `scale(${currentZoom})`;
    if (zoomReadout) zoomReadout.textContent = `${Math.round(currentZoom * 100)}%`;
  };

  modal.querySelector('#btn-zoom-in').onclick = () => updateZoom(currentZoom + 0.25);
  modal.querySelector('#btn-zoom-out').onclick = () => updateZoom(currentZoom - 0.25);
  modal.querySelector('#btn-zoom-reset').onclick = () => updateZoom(1);

  modal.querySelector('#btn-close-imagery').onclick = () => {
    modal.style.display = 'none';
  };

  modal.onclick = (e) => {
    if (e.target === modal) modal.style.display = 'none';
  };
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
