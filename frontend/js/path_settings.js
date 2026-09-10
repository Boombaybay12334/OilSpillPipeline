const DEFAULT_PATHS = {
  stage1: 'C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\Model\\outfinal',
  stage2: 'C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw',
  stage3: 'C:\\Users\\abhin\\Desktop\\OilSpillPipeline\\BacktrackModel\\ais_attribution_gfw\\ais_attribution_gfw\\ais_attribution_output',
};

const STORAGE_KEY = 'oil-pipeline-investigation-paths';

function readAll() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

export function getInvestigationPaths(eventId) {
  const saved = readAll()[eventId] || {};
  return {
    stage1: saved.stage1 || DEFAULT_PATHS.stage1,
    stage2: saved.stage2 || DEFAULT_PATHS.stage2,
    stage3: saved.stage3 || DEFAULT_PATHS.stage3,
  };
}

export function saveInvestigationPaths(eventId, paths) {
  const all = readAll();
  all[eventId] = {
    stage1: String(paths.stage1 || '').trim(),
    stage2: String(paths.stage2 || '').trim(),
    stage3: String(paths.stage3 || '').trim(),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
}
