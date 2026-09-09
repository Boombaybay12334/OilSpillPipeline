/**
 * Oil Spill Intelligence Platform — API Client
 * Authoritative connection layer to the FastAPI backend.
 */

const API_BASE = window.OIL_PIPELINE_API || (
  window.location.port === '8000' || window.location.port === '' 
    ? '/api' 
    : 'http://127.0.0.1:8000/api'
);

export async function request(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const config = {
    ...options,
    headers: {
      'Accept': 'application/json',
      ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  };

  try {
    const response = await fetch(url, config);
    if (!response.ok) {
      let errorDetail = response.statusText;
      try {
        const errJson = await response.json();
        errorDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
      } catch {
        errorDetail = await response.text();
      }
      throw new Error(`API Error (${response.status}): ${errorDetail}`);
    }
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      return await response.json();
    }
    return response;
  } catch (error) {
    console.error(`[API] Request failed for ${path}:`, error);
    throw error;
  }
}

export const Api = {
  // System Health
  async getHealth() {
    return request('/health');
  },

  // Investigations
  async listInvestigations() {
    return request('/investigations');
  },

  async createInvestigation(name, mode = 'offline') {
    return request('/investigations', {
      method: 'POST',
      body: JSON.stringify({ name, mode }),
    });
  },

  async getInvestigation(eventId) {
    return request(`/investigations/${eventId}`);
  },

  async deleteInvestigation(eventId) {
    return request(`/investigations/${eventId}`, { method: 'DELETE' });
  },

  // Execution & Replay Run
  async runStage(eventId, stage, payload = {}) {
    return request(`/investigations/${eventId}/run/${stage}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async cancelRun(eventId) {
    return request(`/investigations/${eventId}/cancel`, { method: 'POST' });
  },

  async getStatus(eventId) {
    return request(`/investigations/${eventId}/status`);
  },

  async getLogs(eventId) {
    return request(`/investigations/${eventId}/logs`);
  },

  // Stage Summaries
  async getStageSummary(eventId, stageNumber) {
    return request(`/investigations/${eventId}/stage${stageNumber}`);
  },

  // Artifacts & Quickviews
  async getArtifacts(eventId) {
    return request(`/investigations/${eventId}/artifacts`);
  },

  async getArtifactMetadata(eventId, artifactId) {
    return request(`/investigations/${eventId}/artifacts/${artifactId}/metadata`);
  },

  async generateQuickviews(eventId, stage = 'stage1') {
    return request(`/investigations/${eventId}/generate-quickviews`, {
      method: 'POST',
      body: JSON.stringify({ stage }),
    });
  },

  async discoverArtifacts(eventId) {
    return request(`/investigations/${eventId}/discover-artifacts`, { method: 'POST' });
  },

  getArtifactUrl(eventId, artifactId) {
    return `${API_BASE}/investigations/${eventId}/artifacts/${artifactId}`;
  }
};
