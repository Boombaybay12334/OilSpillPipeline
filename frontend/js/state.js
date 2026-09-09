/**
 * Oil Spill Intelligence Platform — Reactive State Store
 */

class StateStore {
  constructor() {
    this.state = {
      currentEventId: null,
      currentEvent: null,
      investigations: [],
      health: { ok: false, checks: {} },
      stageSummaries: {
        stage1: null,
        stage2: null,
        stage3: null,
      },
      selectedCandidate: null,
      scrubberIndex: 0,
      mapLayers: {
        footprint: true,
        oilSlicks: true,
        probCells: true,
        vessels: true,
      },
      activePage: 'overview',
      isLoading: false,
      error: null,
    };
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    this.state = { ...this.state, ...updates };
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (err) {
        console.error('[State] Listener error:', err);
      }
    }
  }

  setInvestigations(list) {
    this.setState({ investigations: list });
  }

  setCurrentEvent(event) {
    this.setState({
      currentEvent: event,
      currentEventId: event ? event.event_id : null,
      selectedCandidate: null,
      scrubberIndex: 0,
    });
  }

  setStageSummary(stageKey, summaryData) {
    this.setState({
      stageSummaries: {
        ...this.state.stageSummaries,
        [stageKey]: summaryData,
      },
    });
  }

  setSelectedCandidate(candidate) {
    this.setState({ selectedCandidate: candidate });
  }

  setScrubberIndex(index) {
    this.setState({ scrubberIndex: index });
  }

  toggleMapLayer(layerName) {
    this.setState({
      mapLayers: {
        ...this.state.mapLayers,
        [layerName]: !this.state.mapLayers[layerName],
      },
    });
  }

  setActivePage(page) {
    this.setState({ activePage: page });
  }

  setLoading(isLoading) {
    this.setState({ isLoading });
  }

  setError(error) {
    this.setState({ error });
  }

  setHealth(health) {
    this.setState({ health });
  }
}

export const store = new StateStore();
