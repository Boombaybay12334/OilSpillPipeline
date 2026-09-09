/**
 * New Surveillance Modal Component — Event Creation & Preset Incident Quick-Load
 */
import { store } from '../state.js';
import { Api } from '../api.js';

export function initNewEventModal() {
  let modal = document.getElementById('new-event-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'new-event-modal';
    modal.className = 'modal-backdrop';
    modal.style.display = 'none';
    document.body.appendChild(modal);
  }

  modal.innerHTML = `
    <div class="modal-dialog">
      <div class="modal-header">
        <div>
          <h3 style="margin:0;">Initialize New Surveillance</h3>
          <small class="font-mono">Create an event directory or load an incident benchmark</small>
        </div>
        <button id="btn-close-modal" class="btn-secondary btn-sm" style="padding:4px 8px;">✕</button>
      </div>

      <form id="new-event-form">
        <div class="modal-body">
          <!-- Preset Incident Benchmarks -->
          <div>
            <h4 style="margin-bottom:var(--space-2);">Historical Benchmark Presets</h4>
            <div class="preset-grid">
              <div class="preset-card" data-name="MT Sanchi (2018 East China Sea)" data-mode="replay">
                <h4>MT Sanchi (2018)</h4>
                <p>East China Sea tanker collision & condensate drift. 69h backtrack simulation benchmark.</p>
              </div>
              <div class="preset-card" data-name="Novorossiysk CPC (2024 Black Sea)" data-mode="replay">
                <h4>Novorossiysk CPC (2024)</h4>
                <p>Black Sea marine terminal loading-hose spill with 50-80 km² slick tracking.</p>
              </div>
            </div>
          </div>

          <!-- Custom Event Form -->
          <label>
            <span>Surveillance Event Name</span>
            <input id="input-event-name" name="name" type="text" required placeholder="e.g. North Sea Pipeline Survey">
          </label>

          <label>
            <span>Orchestration Mode</span>
            <select id="input-event-mode" name="mode">
              <option value="offline">Offline (Local Replay & Discovery)</option>
              <option value="replay">Replay (Cached Outputs)</option>
              <option value="online">Online (Live Sentinel-1 / GFW API)</option>
            </select>
          </label>
        </div>

        <div class="modal-footer">
          <button type="button" id="btn-cancel-modal" class="btn-secondary">Cancel</button>
          <button type="submit" class="btn-primary">Initialize Event</button>
        </div>
      </form>
    </div>
  `;

  // Close bindings
  modal.querySelector('#btn-close-modal').onclick = () => { modal.style.display = 'none'; };
  modal.querySelector('#btn-cancel-modal').onclick = () => { modal.style.display = 'none'; };
  modal.onclick = (e) => { if (e.target === modal) modal.style.display = 'none'; };

  // Preset clicks
  modal.querySelectorAll('.preset-card').forEach(card => {
    card.onclick = () => {
      const name = card.dataset.name;
      const mode = card.dataset.mode;
      const nameInput = modal.querySelector('#input-event-name');
      const modeSelect = modal.querySelector('#input-event-mode');
      if (nameInput) nameInput.value = name;
      if (modeSelect) modeSelect.value = mode;
    };
  });

  // Submit form
  modal.querySelector('#new-event-form').onsubmit = async (e) => {
    e.preventDefault();
    const name = modal.querySelector('#input-event-name').value.trim();
    const mode = modal.querySelector('#input-event-mode').value;
    if (!name) return;

    try {
      store.setLoading(true);
      const created = await Api.createInvestigation(name, mode);
      const list = await Api.listInvestigations();
      store.setInvestigations(list);
      const fullEvent = await Api.getInvestigation(created.event_id);
      store.setCurrentEvent(fullEvent);
      modal.style.display = 'none';
      location.hash = '#/overview';
    } catch (err) {
      alert(`Event creation failed: ${err.message}`);
    } finally {
      store.setLoading(false);
    }
  };
}
