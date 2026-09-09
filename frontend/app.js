const API = window.OIL_PIPELINE_API || 'http://127.0.0.1:8000/api';
let current;
let currentEvent;
const $ = (id) => document.getElementById(id);
const stages = ['stage1', 'stage2', 'stage3'];
const pageNames = { stage1: 'Detection', stage2: 'Backtracking', stage3: 'Vessel Ranking', config: 'Configuration' };

async function request(path, options) {
  const response = await fetch(API + path, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function refreshEvents() {
  const events = await request('/investigations');
  $('events').innerHTML = events.map(event => `<button class="event ${event.status.includes('ready') ? 'complete' : ''}" data-id="${event.event_id}"><span class="dot"></span>${escapeHtml(event.name)}<small>${event.mode} · ${event.status}</small></button>`).join('');
  document.querySelectorAll('.event').forEach(button => button.onclick = () => selectEvent(button.dataset.id));
}

async function selectEvent(id) {
  current = id;
  currentEvent = await request(`/investigations/${id}`);
  document.querySelectorAll('.event').forEach(button => button.classList.toggle('active', button.dataset.id === id));
  renderPage(getPage());
}

function getPage() {
  const page = location.hash.replace('#/', '');
  return pageNames[page] ? page : 'stage1';
}

function navigate(page) {
  location.hash = `/${page}`;
  renderPage(page);
}

async function importStage(stage) {
  const input = document.querySelector(`#${stage}-path`);
  const path = input.value.trim();
  if (!path || !current) return;
  input.disabled = true;
  try {
    await request(`/investigations/${current}/run/${stage}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'replay', existing_output_dir: path }) });
    await selectEvent(current);
  } catch (error) {
    showMessage(error.message);
  } finally {
    input.disabled = false;
  }
}

async function generateQuickviews() {
  if (!current) return;
  const button = document.querySelector('#generate-quickviews');
  if (button) { button.disabled = true; button.textContent = 'Generating...'; }
  try {
    const result = await request(`/investigations/${current}/generate-quickviews`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stage: 'stage1' }) });
    await selectEvent(current);
    showMessage(`Quickview generation finished. ${result.results?.length || 0} raster result(s) processed.`);
  } catch (error) {
    showMessage(`Quickview generation failed: ${error.message}`);
  } finally {
    const refreshedButton = document.querySelector('#generate-quickviews');
    if (refreshedButton) { refreshedButton.disabled = false; refreshedButton.textContent = 'Generate quickviews'; }
  }
}

async function loadStageSummary(stage) {
  try { return (await request(`/investigations/${current}/stage${stage.slice(-1)}`)).summary; }
  catch { return { kind: 'empty', message: 'Summary unavailable.' }; }
}

function navigationMarkup(page) {
  return `<nav class="pipeline-nav">${stages.map(stage => `<button class="nav-tab ${page === stage ? 'selected' : ''}" data-page="${stage}"><span>${stage.slice(-1)}</span>${pageNames[stage]}</button>`).join('')}<button class="nav-tab ${page === 'config' ? 'selected' : ''}" data-page="config"><span>+</span>Configuration</button></nav>`;
}

function stageHeader(stage, description) {
  return `<div class="page-heading"><div><span class="eyebrow">${stage.toUpperCase()} · OFFLINE REPLAY</span><h2>${pageNames[stage]}</h2><p class="muted">${description}</p></div><span class="badge">${escapeHtml(currentEvent.mode)}</span></div>`;
}

function importPanel(stage) {
  const placeholders = { stage1: 'C:\\path\\to\\Model\\out', stage2: 'C:\\path\\to\\stage2 handoff folder', stage3: 'C:\\path\\to\\ais_attribution_output' };
  return `<section class="panel import-panel"><div class="panel-heading"><div><h3>Import existing ${pageNames[stage]} outputs</h3><p class="muted">Files are copied into this investigation. Originals are never modified.</p></div><button onclick="importStage('${stage}')">Import folder</button></div><input id="${stage}-path" class="path-input" placeholder="${placeholders[stage]}"></section>`;
}

function summaryMarkup(stage, summary) {
  if (summary.kind === 'backtracking') return `<div class="summary-grid"><div><b>Observation</b><span>${escapeHtml(summary.observation.t_obs_utc || 'n/a')}</span></div><div><b>Simulation</b><span>${escapeHtml(summary.simulation_window.start || 'n/a')} → ${escapeHtml(summary.simulation_window.end || 'n/a')}</span></div><div><b>Hypotheses</b><span>${summary.hypothesis_count}</span></div></div><h4>Top source-probability cells</h4><div class="table-wrap"><table><thead><tr><th>Time</th><th>Lon</th><th>Lat</th><th>Probability</th></tr></thead><tbody>${summary.top_cells.map(cell => `<tr><td>${escapeHtml(cell.time_utc || '')}</td><td>${Number(cell.lon_center).toFixed(3)}</td><td>${Number(cell.lat_center).toFixed(3)}</td><td>${(Number(cell.probability) * 100).toFixed(2)}%</td></tr>`).join('')}</tbody></table></div>${summary.limitations?.length ? `<div class="warning"><b>Limitations</b><ul>${summary.limitations.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul></div>` : ''}`;
  if (summary.kind === 'vessel_ranking') return `<div class="warning">${escapeHtml(summary.disclaimer)}</div><div class="table-wrap"><table><thead><tr><th>Rank</th><th>Vessel</th><th>MMSI</th><th>IMO</th><th>Score</th></tr></thead><tbody>${summary.candidates.map(candidate => `<tr><td>${candidate.rank ?? ''}</td><td>${escapeHtml(candidate.name || candidate.vessel_name || '')}</td><td>${escapeHtml(candidate.mmsi || '')}</td><td>${escapeHtml(candidate.imo || '')}</td><td>${candidate.score ?? candidate.total_score ?? ''}</td></tr>`).join('')}</tbody></table></div>`;
  if (summary.kind === 'detection') return `<div class="summary-grid"><div><b>Catalog</b><span>${escapeHtml(summary.metadata.catalog_id || 'n/a')}</span></div><div><b>Acquisition</b><span>${escapeHtml(summary.metadata.acquisition_start || 'n/a')}</span></div><div><b>Detected regions</b><span>${summary.region_count}</span></div></div>`;
  return `<p class="muted">${escapeHtml(summary.message || 'No summary available.')}</p>`;
}

function artifactsMarkup(stage) {
  const artifacts = (currentEvent.manifest.artifacts || []).filter(artifact => artifact.stage === stage);
  const images = artifacts.filter(artifact => artifact.category === 'raster_quickview' || artifact.category === 'image');
  const gallery = images.length ? `<div class="quickview-gallery">${images.map(artifact => `<figure><img src="${API}/investigations/${current}/artifacts/${artifact.artifact_id}" alt="${escapeHtml(artifact.label)}"><figcaption>${escapeHtml(artifact.label)}</figcaption></figure>`).join('')}</div>` : '';
  const list = artifacts.length ? artifacts.map(artifact => `<div class="artifact"><div><strong>${escapeHtml(artifact.label)}</strong><span>${escapeHtml(artifact.relative_path)}</span></div><a href="${API}/investigations/${current}/artifacts/${artifact.artifact_id}" target="_blank">Open</a></div>`).join('') : '<p class="muted">No artifacts imported yet.</p>';
  return `${gallery}<div class="artifact-list">${list}</div>`;
}

async function renderStage(stage) {
  const summary = await loadStageSummary(stage);
  const quickviewNote = stage === 'stage1' ? '<p class="muted">Source TIFFs stay downloadable; generated PNG quickviews appear here automatically after import.</p>' : '';
  const nextStage = stages[stages.indexOf(stage) + 1];
  const previousStage = stages[stages.indexOf(stage) - 1];
  const quickviewButton = stage === 'stage1' ? '<button id="generate-quickviews" class="quickview-button">Generate quickviews</button>' : '';
  $('workspace').innerHTML = `${navigationMarkup(stage)}${stageHeader(stage, stage === 'stage1' ? 'Inspect SAR detection, regions, metadata, and presentation-ready raster quickviews.' : stage === 'stage2' ? 'Inspect the source-time handoff, probability cells, simulation window, and limitations.' : 'Inspect the offline vessel compatibility ranking and supporting evidence.')} ${importPanel(stage)}<section class="panel"><div class="panel-heading"><div><h3>${stage === 'stage1' ? 'Quickviews and detection summary' : 'Stage summary'}</h3>${quickviewNote}</div>${quickviewButton}</div><div id="summary-content">${summaryMarkup(stage, summary)}</div></section><section class="panel"><h3>${stage === 'stage1' ? 'Stage 1 artifacts and downloads' : `${pageNames[stage]} artifacts and downloads`}</h3>${artifactsMarkup(stage)}</section><div class="stage-actions">${previousStage ? `<button class="quiet" data-page="${previousStage}">Back to ${pageNames[previousStage]}</button>` : ''}${nextStage ? `<button data-page="${nextStage}">Next: ${pageNames[nextStage]}</button>` : ''}</div>`;
}

function renderConfig() {
  const event = currentEvent;
  $('workspace').innerHTML = `${navigationMarkup('config')}${stageHeader('config', 'Prepare a saved investigation without mixing configuration with scientific results.')}<section class="panel config-card"><h3>Current investigation</h3><div class="config-grid"><div><b>Name</b><span>${escapeHtml(event.name)}</span></div><div><b>Event ID</b><span>${escapeHtml(event.event_id)}</span></div><div><b>Mode</b><span>${escapeHtml(event.mode)}</span></div><div><b>Data location</b><span>data/investigations/${escapeHtml(event.event_id)}</span></div></div></section><section class="panel"><h3>Expected input locations</h3><div class="config-path"><b>Stage 1</b><code>Model\\out</code></div><div class="config-path"><b>Stage 2</b><code>BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw</code></div><div class="config-path"><b>Stage 3</b><code>BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw\\ais_attribution_output</code></div></section><section class="panel"><h3>Pipeline order</h3><div class="order-line"><span>01</span>Detection and raster quickviews <b>→</b><span>02</span>Backtracking handoff <b>→</b><span>03</span>Vessel ranking</div></section>`;
}

function renderPage(page) {
  if (!currentEvent) return;
  if (page === 'config') renderConfig(); else renderStage(page);
}

function showMessage(message) { const target = $('workspace'); target.insertAdjacentHTML('afterbegin', `<div class="warning">${escapeHtml(message)}</div>`); }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character])); }

$('new-event').onclick = () => $('create-dialog').showModal();
$('create-form').onsubmit = async event => { event.preventDefault(); const form = new FormData(event.target); const created = await request('/investigations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: form.get('name'), mode: form.get('mode') }) }); $('create-dialog').close(); await refreshEvents(); await selectEvent(created.event_id); };
document.addEventListener('click', event => {
  const target = event.target.closest('[data-page]');
  if (target) navigate(target.dataset.page);
  if (event.target.closest('#generate-quickviews')) generateQuickviews();
});
window.addEventListener('hashchange', () => renderPage(getPage()));
window.navigate = navigate;
window.importStage = importStage;
window.generateQuickviews = generateQuickviews;
refreshEvents().catch(error => { $('workspace').innerHTML = `<div class="empty"><h2>Backend unavailable</h2><p>${escapeHtml(error.message)}</p><p>Start it with <code>uvicorn app.main:app --app-dir backend --reload --port 8000</code>.</p></div>`; });
