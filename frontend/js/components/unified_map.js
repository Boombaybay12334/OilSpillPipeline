/**
 * Unified Geospatial Map Component — Leaflet Multi-Layer Analytical Instrument
 */
import { store } from '../state.js';
import { Api } from '../api.js';

let mapInstance = null;
let footprintLayer = null;
let slicksLayer = null;
let probLayer = null;
let vesselsLayer = null;

export async function renderUnifiedMap(container) {
  const state = store.getState();
  const event = state.currentEvent;
  const s1 = state.stageSummaries.stage1;
  const s2 = state.stageSummaries.stage2;
  const s3 = state.stageSummaries.stage3;

  if (!event) {
    container.innerHTML = '<div class="empty-state"><h3>Select an investigation first</h3></div>';
    return;
  }

  container.innerHTML = `
    <div class="page-container">
      <div class="page-header">
        <div class="page-title-group">
          <span class="page-eyebrow">GEOSPATIAL ANALYTICAL INSTRUMENT</span>
          <h2 class="page-title">Multi-Layer Tactical Maritime Map</h2>
          <p class="page-desc">
            Interactive overlay of Sentinel-1 radar scene footprint, segmented oil-slick boundaries, backward hydrodynamic probability density grid, and GFW AIS candidate vessels.
          </p>
        </div>

        <div class="page-actions">
          <button id="btn-fit-all-bounds" class="btn-secondary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
            <span>Reset Spatial Extent</span>
          </button>
        </div>
      </div>

      <!-- Map Viewport -->
      <div class="map-viewport map-fullscreen">
        <div id="leaflet-map"></div>

        <!-- Layer Toggle Controls -->
        <div class="map-layer-control">
          <h4>Tactical Layers</h4>
          <label class="layer-toggle">
            <input type="checkbox" id="layer-chk-footprint" checked>
            <span class="layer-color-dot" style="background:#0ea5e9;"></span>
            <span>SAR Scene Extent</span>
          </label>
          <label class="layer-toggle">
            <input type="checkbox" id="layer-chk-slicks" checked>
            <span class="layer-color-dot" style="background:#f43f5e;"></span>
            <span>Detected Oil Slicks</span>
          </label>
          <label class="layer-toggle">
            <input type="checkbox" id="layer-chk-prob" checked>
            <span class="layer-color-dot" style="background:#f59e0b;"></span>
            <span>Origin Probability Grid</span>
          </label>
          <label class="layer-toggle">
            <input type="checkbox" id="layer-chk-vessels" checked>
            <span class="layer-color-dot" style="background:#00e5c9;"></span>
            <span>AIS Candidate Ships</span>
          </label>
        </div>

        <!-- Live Cursor Coordinates Telemetry Bar -->
        <div class="map-coords-bar">
          <div>
            <span>CURSOR: </span>
            <span id="map-cursor-coords" class="map-coords-val">--.----°N, ---.----°E</span>
          </div>
          <div class="font-mono">
            <span>EVENT AOI: </span>
            <span style="color:var(--text-secondary);">
              ${s2?.observation?.unpadded_bbox_wsen ? `[${s2.observation.unpadded_bbox_wsen.map(n => Number(n).toFixed(2)).join(', ')}]` : 'Global Ocean'}
            </span>
          </div>
        </div>
      </div>
    </div>
  `;

  // Initialize or re-attach Leaflet map
  setTimeout(() => initMap(event, s1, s2, s3), 50);

  // Bind Reset bounds button
  const fitBtn = container.querySelector('#btn-fit-all-bounds');
  if (fitBtn) {
    fitBtn.onclick = () => fitMapBounds(s1, s2, s3);
  }
}

async function initMap(event, s1, s2, s3) {
  const mapEl = document.getElementById('leaflet-map');
  if (!mapEl || !window.L) return;

  if (mapInstance) {
    mapInstance.remove();
    mapInstance = null;
  }

  // Default ocean center (e.g. East China Sea 28.5N, 124.5E)
  const defaultLat = s2?.observation?.t_obs_utc ? 28.37 : 30.0;
  const defaultLon = s2?.observation?.t_obs_utc ? 124.5 : 35.0;

  mapInstance = window.L.map('leaflet-map', {
    center: [defaultLat, defaultLon],
    zoom: 7,
    zoomControl: false,
    attributionControl: true,
  });

  window.L.control.zoom({ position: 'topleft' }).addTo(mapInstance);

  // Dark nautical cartography tiles (CartoDB Dark Matter / OSM Dark)
  window.L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap',
    subdomains: 'abcd',
    maxZoom: 18,
  }).addTo(mapInstance);

  // Track cursor coordinates
  mapInstance.on('mousemove', (e) => {
    const coordsEl = document.getElementById('map-cursor-coords');
    if (coordsEl) {
      coordsEl.textContent = `${e.latlng.lat.toFixed(4)}°N, ${e.latlng.lng.toFixed(4)}°E`;
    }
  });

  // Layer groups
  footprintLayer = window.L.layerGroup().addTo(mapInstance);
  slicksLayer = window.L.layerGroup().addTo(mapInstance);
  probLayer = window.L.layerGroup().addTo(mapInstance);
  vesselsLayer = window.L.layerGroup().addTo(mapInstance);

  // 1. Plot Footprint Bounding Box
  const bbox = s2?.observation?.unpadded_bbox_wsen || s3?.query?.bbox_wsen || null;
  if (bbox && bbox.length === 4) {
    const [w, s, e, n] = bbox;
    const bounds = [[s, w], [n, e]];
    window.L.rectangle(bounds, {
      color: '#0ea5e9',
      weight: 1.5,
      dashArray: '4, 4',
      fillColor: '#0ea5e9',
      fillOpacity: 0.04,
    }).bindTooltip('SAR Scene Footprint Area', { sticky: true }).addTo(footprintLayer);
  }

  // 2. Fetch and Plot Real GeoJSON Oil Slicks (from manifest artifacts)
  const artifacts = event?.manifest?.artifacts || [];
  const slickArtifact = artifacts.find(a => a.stage === 'stage1' && a.category === 'stage_handoff' && a.relative_path.endsWith('.geojson'));
  if (slickArtifact) {
    try {
      const geojson = await Api.getArtifact(event.event_id, slickArtifact.artifact_id);
      if (geojson && geojson.features && geojson.features.length > 0) {
        window.L.geoJSON(geojson, {
          style: {
            color: '#f43f5e',
            weight: 2,
            fillColor: '#f43f5e',
            fillOpacity: 0.5,
          },
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            layer.bindPopup(`
              <div class="map-popup-header">DETECTED OIL SLICK</div>
              <div class="map-popup-grid">
                <span>Cluster ID:</span><span>${props.cluster_id || 1}</span>
                <span>Area:</span><span>${props.area_km2 ? `${Number(props.area_km2).toFixed(3)} km²` : 'N/A'}</span>
                <span>Mean Prob:</span><span>${props.mean_probability ? `${(props.mean_probability * 100).toFixed(1)}%` : 'High'}</span>
              </div>
            `);
          }
        }).addTo(slicksLayer);
      }
    } catch {
      // fallback
    }
  }

  // 3. Fetch and Plot Source Probability GeoJSON (Stage 2)
  const probArtifact = artifacts.find(a => a.stage === 'stage2' && (a.category === 'geojson' || a.label.includes('probability')));
  if (probArtifact) {
    try {
      const probGeojson = await Api.getArtifact(event.event_id, probArtifact.artifact_id);
      if (probGeojson && probGeojson.features) {
        window.L.geoJSON(probGeojson, {
          style: (feature) => {
            const prob = feature.properties?.probability || 0.01;
            const opacity = Math.min(0.8, Math.max(0.2, prob * 12));
            return {
              color: '#f59e0b',
              weight: 0.8,
              fillColor: '#f59e0b',
              fillOpacity: opacity,
            };
          },
          onEachFeature: (feature, layer) => {
            const props = feature.properties || {};
            layer.bindPopup(`
              <div class="map-popup-header">SOURCE PROBABILITY CELL</div>
              <div class="map-popup-grid">
                <span>Rank:</span><span>#${props.rank || 1}</span>
                <span>Timestamp:</span><span>${props.time_utc || 'N/A'}</span>
                <span>Probability:</span><span>${(Number(props.probability || 0) * 100).toFixed(2)}%</span>
                <span>Particles:</span><span>${props.particle_count || 'N/A'}</span>
              </div>
            `);
          }
        }).addTo(probLayer);
      }
    } catch {
      // fallback: plot top cells from summary
      const topCells = s2?.top_cells || [];
      topCells.slice(0, 20).forEach(cell => {
        window.L.circleMarker([cell.lat_center, cell.lon_center], {
          radius: 6,
          color: '#f59e0b',
          fillColor: '#f59e0b',
          fillOpacity: 0.6,
          weight: 1,
        }).bindTooltip(`Probability: ${(cell.probability * 100).toFixed(1)}%`).addTo(probLayer);
      });
    }
  }

  // 4. Plot Candidate Vessels (Stage 3)
  const candidates = s3?.candidates || [];
  candidates.forEach((ship, idx) => {
    if (!ship.best_match_lat || !ship.best_match_lon) return;

    const isSelected = store.getState().selectedCandidate?.mmsi === ship.mmsi;
    const markerIcon = window.L.divIcon({
      className: 'vessel-marker-icon',
      html: `<div class="vessel-pin ${isSelected ? 'selected' : ''}">${ship.rank || idx + 1}</div>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });

    const marker = window.L.marker([ship.best_match_lat, ship.best_match_lon], { icon: markerIcon })
      .bindPopup(`
        <div class="map-popup-header">CANDIDATE VESSEL #${ship.rank}</div>
        <div class="map-popup-grid">
          <span>Name:</span><span>${escapeHtml(ship.name || 'UNKNOWN')}</span>
          <span>MMSI:</span><span>${ship.mmsi || 'N/A'}</span>
          <span>Flag:</span><span>${ship.flag || 'N/A'}</span>
          <span>Score:</span><span style="color:var(--cyan-accent);">${(ship.score * 100).toFixed(2)}%</span>
          <span>Dist to Origin:</span><span>${ship.best_distance_km ? `${Number(ship.best_distance_km).toFixed(2)} km` : 'N/A'}</span>
          <span>AIS Coverage:</span><span>${Number(ship.coverage_percent || 0).toFixed(0)}%</span>
        </div>
      `)
      .addTo(vesselsLayer);

    marker.on('click', () => {
      store.setSelectedCandidate(ship);
    });
  });

  // Fit bounds to meaningful layers
  fitMapBounds(s1, s2, s3);

  // Bind Layer Checkbox Toggles
  bindLayerToggle('layer-chk-footprint', footprintLayer);
  bindLayerToggle('layer-chk-slicks', slicksLayer);
  bindLayerToggle('layer-chk-prob', probLayer);
  bindLayerToggle('layer-chk-vessels', vesselsLayer);
}

function bindLayerToggle(chkId, layer) {
  const chk = document.getElementById(chkId);
  if (!chk || !mapInstance || !layer) return;
  chk.onchange = () => {
    if (chk.checked) {
      mapInstance.addLayer(layer);
    } else {
      mapInstance.removeLayer(layer);
    }
  };
}

function fitMapBounds(s1, s2, s3) {
  if (!mapInstance || !window.L) return;

  const bbox = s2?.observation?.unpadded_bbox_wsen || s3?.query?.bbox_wsen || null;
  if (bbox && bbox.length === 4) {
    const [w, s, e, n] = bbox;
    mapInstance.fitBounds([[s, w], [n, e]], { padding: [30, 30] });
  } else if (s3?.candidates?.[0]?.best_match_lat) {
    const top = s3.candidates[0];
    mapInstance.setView([top.best_match_lat, top.best_match_lon], 8);
  }
}

function escapeHtml(str) {
  return String(str || '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
}
