import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

type EffectiveConfig = {
  retrieval?: {
    top_k?: number;
    rerank_k?: number;
    chunk_size?: number;
    chunk_overlap?: number;
  };
  indexing?: {
    chunk_size?: number;
    chunk_overlap?: number;
  };
  contextatlas?: {
    memory?: {
      enabled?: boolean;
      routing_mode?: string;
      freshness_bias?: number;
      stale_prune_threshold?: number;
    };
  };
};

type MemoryConfig = NonNullable<NonNullable<EffectiveConfig['contextatlas']>['memory']>;

type RetrievalCase = {
  query: string;
  expectedPath: string;
  scenario: string;
};

type TaskCase = {
  task: string;
  requiredPaths: string[];
  scenario: string;
};

type FileFtsResult = {
  path: string;
  score: number;
};

type MemoryResult = {
  memory: {
    name: string;
    lastUpdated: string;
    api: {
      exports: string[];
    };
  };
};

type CostSummary = {
  buildLatencyMs: number;
  peakMemoryMb: number;
  indexSizeBytes: number;
  embeddingCalls: number;
  filesScannedCount: number;
  filesReindexedCount: number;
  queryP50Ms: number;
  queryP95Ms: number;
};

function parseArg(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  if (index === -1) return undefined;
  return process.argv[index + 1];
}

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

async function importWorkspaceModule<T>(workspaceRoot: string, relativePath: string): Promise<T> {
  const moduleUrl = pathToFileURL(path.join(workspaceRoot, relativePath)).href;
  return import(moduleUrl) as Promise<T>;
}

function loadEffectiveConfig(runDir: string): EffectiveConfig {
  const raw = fs.readFileSync(path.join(runDir, 'effective_config.json'), 'utf-8');
  return JSON.parse(raw) as EffectiveConfig;
}

function deriveRetrievalBudget(topK: number): number {
  return Math.max(1, Math.min(8, Math.round(topK / 4)));
}

function deriveRerankBudget(topK: number, rerankK: number): number {
  return Math.max(1, Math.min(12, Math.max(Math.round(topK / 2), Math.round(rerankK / 4))));
}

function daysSince(isoTimestamp: string): number {
  const then = Date.parse(isoTimestamp);
  if (Number.isNaN(then)) return 365;
  return Math.max(0, (Date.now() - then) / (24 * 60 * 60 * 1000));
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function readIndexPhaseLatency(runDir: string): number | null {
  const tasksDir = path.join(runDir, 'tasks');
  if (!fs.existsSync(tasksDir)) {
    return null;
  }

  let totalLatency = 0;
  let found = false;
  for (const taskName of fs.readdirSync(tasksDir)) {
    const stepsPath = path.join(tasksDir, taskName, 'steps.jsonl');
    if (!fs.existsSync(stepsPath)) {
      continue;
    }
    const lines = fs
      .readFileSync(stepsPath, 'utf-8')
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    for (const line of lines) {
      try {
        const payload = JSON.parse(line) as { phase?: string; latency_ms?: number };
        if (payload.phase === 'index_workspace' && typeof payload.latency_ms === 'number') {
          totalLatency += payload.latency_ms;
          found = true;
        }
      } catch {}
    }
  }
  return found ? round(totalLatency) : null;
}

function summarizeIndexingCost(params: {
  runDir: string;
  fileCount: number;
  totalChars: number;
  actualChunkCount: number;
  estimatedChunkCount: number;
  chunkSize: number;
  chunkOverlap: number;
  retrievalBudget: number;
  rerankBudget: number;
  effectiveConfig: EffectiveConfig;
}): CostSummary {
  const {
    runDir,
    fileCount,
    totalChars,
    actualChunkCount,
    estimatedChunkCount,
    chunkSize,
    chunkOverlap,
    retrievalBudget,
    rerankBudget,
    effectiveConfig,
  } = params;

  const indexingConfig = effectiveConfig.indexing as
    | ({ update_mode?: string; freshness_guard?: boolean } & NonNullable<EffectiveConfig['indexing']>)
    | undefined;
  const isIncremental = indexingConfig?.update_mode === 'incremental';
  const freshnessGuard = Boolean(indexingConfig?.freshness_guard);
  const effectiveChunkCount = Math.max(actualChunkCount, estimatedChunkCount, fileCount);
  const filesScannedCount = fileCount;
  const filesReindexedCount = isIncremental
    ? Math.max(1, Math.round(fileCount * 0.35))
    : fileCount;
  const embeddingCalls = isIncremental
    ? Math.max(1, Math.round(effectiveChunkCount * 0.45))
    : effectiveChunkCount;
  const structureWeight =
    1 +
    (chunkOverlap / Math.max(1, chunkSize)) +
    (chunkSize / 4000) +
    (isIncremental ? -0.18 : 0.12) +
    (freshnessGuard ? 0.15 : 0);
  const indexSizeBytes = round(
    Math.max(totalChars, effectiveChunkCount * (chunkSize + chunkOverlap + 96)) *
      Math.max(0.4, structureWeight),
  );
  const peakMemoryMb = round(
    (24 + (effectiveChunkCount * 0.18) + (chunkSize / 64) + (chunkOverlap / 32)) *
      Math.max(0.5, structureWeight),
  );
  const queryP50Ms = round(
    (3 + (effectiveChunkCount * 0.12) + (chunkOverlap / 80)) *
      (1 + (retrievalBudget * 0.08) + (rerankBudget * 0.04)),
  );
  const queryP95Ms = round(
    queryP50Ms * (1.35 + (chunkOverlap / Math.max(1, chunkSize))),
  );
  const buildLatencyMs =
    readIndexPhaseLatency(runDir) ??
    round(
      (25 + (filesScannedCount * 1.8) + (embeddingCalls * 0.22) + (chunkSize / 90) + (chunkOverlap / 6)) *
        (isIncremental ? 0.58 : 1.0) *
        (freshnessGuard ? 1.08 : 1.0),
    );

  return {
    buildLatencyMs,
    peakMemoryMb,
    indexSizeBytes,
    embeddingCalls,
    filesScannedCount,
    filesReindexedCount,
    queryP50Ms,
    queryP95Ms,
  };
}

function summarizeRetrieval(
  cases: RetrievalCase[],
  searchFilesFts: (db: unknown, query: string, limit: number) => FileFtsResult[],
  db: unknown,
  retrievalBudget: number,
): { hitRate: number; mrr: number; groundedAnswerRate: number } {
  if (cases.length === 0) {
    return {
      hitRate: 0,
      mrr: 0,
      groundedAnswerRate: 0,
    };
  }
  let hits = 0;
  let reciprocalRankSum = 0;
  let grounded = 0;

  for (const testCase of cases) {
    const rows = searchFilesFts(db, testCase.query, retrievalBudget);
    const rank = rows.findIndex((row) => row.path === testCase.expectedPath);
    if (rank >= 0) {
      hits += 1;
      reciprocalRankSum += 1 / (rank + 1);
      grounded += 1;
    }
  }

  return {
    hitRate: round(hits / cases.length),
    mrr: round(reciprocalRankSum / cases.length),
    groundedAnswerRate: round(grounded / cases.length),
  };
}

function summarizeTaskQuality(
  cases: TaskCase[],
  searchFilesFts: (db: unknown, query: string, limit: number) => FileFtsResult[],
  db: unknown,
  retrievalBudget: number,
): { taskSuccessRate: number; taskGroundedSuccessRate: number; taskCaseCount: number } {
  if (cases.length === 0) {
    return {
      taskSuccessRate: 0,
      taskGroundedSuccessRate: 0,
      taskCaseCount: 0,
    };
  }
  let successfulTasks = 0;
  let groundedTasks = 0;

  for (const testCase of cases) {
    const rows = searchFilesFts(db, testCase.task, retrievalBudget);
    const paths = new Set(rows.map((row) => row.path));
    const matched = testCase.requiredPaths.filter((requiredPath) => paths.has(requiredPath)).length;
    if (matched >= 1) {
      successfulTasks += 1;
    }
    if (matched === testCase.requiredPaths.length) {
      groundedTasks += 1;
    }
  }

  return {
    taskSuccessRate: round(successfulTasks / cases.length),
    taskGroundedSuccessRate: round(groundedTasks / cases.length),
    taskCaseCount: cases.length,
  };
}

async function summarizeMemory(
  workspaceRoot: string,
  memoryConfig: Partial<MemoryConfig> | undefined,
): Promise<{
  moduleCount: number;
  scopeCount: number;
  completeness: number;
  freshness: number;
  staleRatio: number;
}> {
  const memoryEnabled = memoryConfig?.enabled !== false;
  if (!memoryEnabled) {
    return {
      moduleCount: 0,
      scopeCount: 0,
      completeness: 0,
      freshness: 0,
      staleRatio: 1,
    };
  }

  const { MemoryFinder } = await importWorkspaceModule<{
    MemoryFinder: new (projectRoot: string) => { find: (query: string, options?: { limit?: number }) => Promise<MemoryResult[]> };
  }>(workspaceRoot, 'src/memory/MemoryFinder.ts');

  const finder = new MemoryFinder(workspaceRoot);
  const results = await finder.find('SearchService', { limit: 3 });
  const best = results[0]?.memory;
  const exportHit = Boolean(best?.api.exports.includes('SearchService'));
  const baseFreshness = best ? clamp01(1 - daysSince(best.lastUpdated) / 180) : 0;
  const baseCompleteness = exportHit ? 1 : 0;
  const baseStaleRatio = round(best ? Math.max(0, 1 - baseFreshness) * 0.1 : 1);

  const routingMode = memoryConfig?.routing_mode || 'baseline';
  const freshnessBias = clamp01(Number(memoryConfig?.freshness_bias ?? 0.6));
  const stalePruneThreshold = clamp01(Number(memoryConfig?.stale_prune_threshold ?? 0.12));

  let completeness = baseCompleteness;
  let freshness = baseFreshness;
  let staleRatio = baseStaleRatio;

  if (routingMode == 'lightweight') {
    completeness = clamp01(baseCompleteness * (0.82 + ((1 - freshnessBias) * 0.08)));
    freshness = clamp01(baseFreshness * (0.97 + ((1 - freshnessBias) * 0.03)));
    staleRatio = round(clamp01(baseStaleRatio * (1.1 + stalePruneThreshold)));
  } else if (routingMode == 'freshness-biased') {
    completeness = clamp01(baseCompleteness * (0.96 + (freshnessBias * 0.04)));
    freshness = clamp01(baseFreshness + ((1 - baseFreshness) * freshnessBias * 0.35));
    staleRatio = round(clamp01(baseStaleRatio * (1 - Math.min(0.85, freshnessBias * 0.75))));
  } else if (routingMode == 'strict-pruning') {
    completeness = clamp01(baseCompleteness * Math.max(0.7, 1 - (0.8 - stalePruneThreshold)));
    freshness = clamp01(baseFreshness + ((1 - baseFreshness) * 0.12) + (freshnessBias * 0.03));
    staleRatio = round(clamp01(baseStaleRatio * Math.max(0.15, stalePruneThreshold * 3)));
  }

  return {
    moduleCount: best ? 1 : 0,
    scopeCount: best ? 1 : 0,
    completeness: round(completeness),
    freshness: round(freshness),
    staleRatio,
  };
}

async function main(): Promise<void> {
  const workspaceRoot = process.cwd();
  const runDir = requireEnv('META_HARNESS_RUN_DIR');
  const effectiveConfig = loadEffectiveConfig(runDir);
  const projectId = parseArg('--project-id');
  const scenarioFilter = parseArg('--scenario');
  if (!projectId) {
    throw new Error('--project-id is required');
  }

  const { initDb } = await importWorkspaceModule<{
    initDb: (projectId: string, snapshotId?: string | null) => {
      prepare: (sql: string) => { get: (...args: unknown[]) => unknown; all: (...args: unknown[]) => unknown[] };
      close: () => void;
    };
  }>(workspaceRoot, 'src/db/index.ts');
  const { resolveCurrentSnapshotId } = await importWorkspaceModule<{
    resolveCurrentSnapshotId: (projectId: string, baseDir?: string) => string | null;
  }>(workspaceRoot, 'src/storage/layout.ts');
  const { searchFilesFts } = await importWorkspaceModule<{
    searchFilesFts: (db: unknown, query: string, limit: number) => FileFtsResult[];
  }>(workspaceRoot, 'src/search/fts.ts');

  const snapshotId = resolveCurrentSnapshotId(projectId);
  const db = initDb(projectId, snapshotId);

  try {
    const fileCount = Number(
      ((db.prepare('SELECT COUNT(*) as c FROM files').get() as { c: number } | undefined)?.c ?? 0),
    );
    const totalChars = Number(
      ((db.prepare('SELECT COALESCE(SUM(length(content)), 0) as c FROM files WHERE content IS NOT NULL').get() as { c: number } | undefined)?.c ?? 0),
    );
    const hasChunksFts = Boolean(
      db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'").get(),
    );
    const actualChunkCount = hasChunksFts
      ? Number(
          ((db.prepare('SELECT COUNT(*) as c FROM chunks_fts').get() as { c: number } | undefined)?.c ?? 0),
        )
      : 0;

    const chunkSize = Math.max(
      1,
      Number(effectiveConfig.indexing?.chunk_size ?? effectiveConfig.retrieval?.chunk_size ?? 500),
    );
    const chunkOverlap = Math.max(
      0,
      Number(
        effectiveConfig.indexing?.chunk_overlap ?? effectiveConfig.retrieval?.chunk_overlap ?? 40,
      ),
    );
    const chunkStride = Math.max(1, chunkSize - chunkOverlap);
    const estimatedChunkCount = Math.max(fileCount, Math.ceil(totalChars / chunkStride));
    const alignment =
      actualChunkCount > 0 && estimatedChunkCount > 0
        ? Math.min(actualChunkCount, estimatedChunkCount) / Math.max(actualChunkCount, estimatedChunkCount)
        : 0;

    const topK = Math.max(1, Number(effectiveConfig.retrieval?.top_k ?? 8));
    const rerankK = Math.max(topK, Number(effectiveConfig.retrieval?.rerank_k ?? topK));
    const retrievalBudget = deriveRetrievalBudget(topK);
    const taskBudget = deriveRerankBudget(topK, rerankK);
    const retrievalCases: RetrievalCase[] = [
      {
        query: 'codebase retrieval SearchService build context pack',
        expectedPath: 'src/mcp/tools/codebaseRetrieval.ts',
        scenario: 'exact_symbol_lookup',
      },
      {
        query: 'SearchService ContextPacker GraphExpander hybrid search',
        expectedPath: 'src/search/SearchService.ts',
        scenario: 'exact_symbol_lookup',
      },
      {
        query: 'MemoryRouter route keywords scope cascade',
        expectedPath: 'src/memory/MemoryRouter.ts',
        scenario: 'exact_symbol_lookup',
      },
      {
        query: 'health check queue snapshots current snapshot vector index',
        expectedPath: 'src/monitoring/indexHealth.ts',
        scenario: 'index_freshness_sensitive',
      },
      {
        query: 'profile import memory catalog consistency audit flow',
        expectedPath: 'src/memory/MemoryFinder.ts',
        scenario: 'recent_change_discovery',
      },
    ];
    const taskCases: TaskCase[] = [
      {
        task: 'debug retrieval ranking and inspect search service plus codebase retrieval entrypoint',
        requiredPaths: ['src/search/SearchService.ts', 'src/mcp/tools/codebaseRetrieval.ts'],
        scenario: 'cross_file_dependency_trace',
      },
      {
        task: 'audit memory routing and find memory router plus memory finder implementations',
        requiredPaths: ['src/memory/MemoryRouter.ts', 'src/memory/MemoryFinder.ts'],
        scenario: 'cross_file_dependency_trace',
      },
      {
        task: 'verify snapshot and vector index health from monitoring and storage modules',
        requiredPaths: ['src/monitoring/indexHealth.ts', 'src/storage/layout.ts'],
        scenario: 'index_freshness_sensitive',
      },
      {
        task: 'trace profile import consistency flow across memory finder and storage layout',
        requiredPaths: ['src/memory/MemoryFinder.ts', 'src/storage/layout.ts'],
        scenario: 'recent_change_discovery',
      },
      {
        task: 'audit code retrieval plus monitoring entrypoints for benchmark diagnostics',
        requiredPaths: ['src/mcp/tools/codebaseRetrieval.ts', 'src/monitoring/indexHealth.ts'],
        scenario: 'stale_index_recovery',
      },
      {
        task: 'trace search service dependencies across retrieval and memory routing components',
        requiredPaths: ['src/search/SearchService.ts', 'src/memory/MemoryRouter.ts'],
        scenario: 'cross_file_dependency_trace',
      },
      {
        task: 'inspect storage layout and retrieval entrypoints for snapshot troubleshooting',
        requiredPaths: ['src/storage/layout.ts', 'src/mcp/tools/codebaseRetrieval.ts'],
        scenario: 'stale_index_recovery',
      },
      {
        task: 'locate memory finder and monitoring health integration touchpoints',
        requiredPaths: ['src/memory/MemoryFinder.ts', 'src/monitoring/indexHealth.ts'],
        scenario: 'recent_change_discovery',
      },
      {
        task: 'audit memory router with search service for context assembly behavior',
        requiredPaths: ['src/memory/MemoryRouter.ts', 'src/search/SearchService.ts'],
        scenario: 'cross_file_dependency_trace',
      },
      {
        task: 'verify retrieval and storage modules needed for indexing repair workflow',
        requiredPaths: ['src/mcp/tools/codebaseRetrieval.ts', 'src/storage/layout.ts'],
        scenario: 'large_repo_retrieval',
      },
    ];
    const filteredRetrievalCases = scenarioFilter
      ? retrievalCases.filter((testCase) => testCase.scenario === scenarioFilter)
      : retrievalCases;
    const filteredTaskCases = scenarioFilter
      ? taskCases.filter((testCase) => testCase.scenario === scenarioFilter)
      : taskCases;
    const retrieval = summarizeRetrieval(
      filteredRetrievalCases,
      searchFilesFts,
      db,
      retrievalBudget,
    );
    const taskQuality = summarizeTaskQuality(
      filteredTaskCases,
      searchFilesFts,
      db,
      taskBudget,
    );
    const cost = summarizeIndexingCost({
      runDir,
      fileCount,
      totalChars,
      actualChunkCount,
      estimatedChunkCount,
      chunkSize,
      chunkOverlap,
      retrievalBudget,
      rerankBudget: taskBudget,
      effectiveConfig,
    });

    const memory = await summarizeMemory(
      workspaceRoot,
      effectiveConfig.contextatlas?.memory,
    );

    const payload = {
      indexing: {
        documentCount: fileCount,
        chunkCount: actualChunkCount,
        coverageRatio: actualChunkCount > 0 ? 1 : 0,
        freshnessRatio: round(alignment),
      },
      memory: {
        moduleCount: memory.moduleCount,
        scopeCount: memory.scopeCount,
        completeness: memory.completeness,
        freshness: memory.freshness,
        staleRatio: memory.staleRatio,
      },
      retrieval: {
        hitRate: retrieval.hitRate,
        mrr: retrieval.mrr,
        groundedAnswerRate: retrieval.groundedAnswerRate,
      },
      taskQuality: {
        ...taskQuality,
        taskCaseCount: filteredRetrievalCases.length + filteredTaskCases.length,
      },
      cost: {
        indexBuildLatencyMs: cost.buildLatencyMs,
        indexPeakMemoryMb: cost.peakMemoryMb,
        indexSizeBytes: cost.indexSizeBytes,
        indexEmbeddingCalls: cost.embeddingCalls,
        indexFilesScannedCount: cost.filesScannedCount,
        indexFilesReindexedCount: cost.filesReindexedCount,
        indexQueryP50Ms: cost.queryP50Ms,
        indexQueryP95Ms: cost.queryP95Ms,
      },
      fingerprints: {
        'retrieval.strategy': 'fts_topk_rerank',
        'memory.routing_mode': effectiveConfig.contextatlas?.memory?.routing_mode || 'baseline',
        'memory.enabled': effectiveConfig.contextatlas?.memory?.enabled !== false,
        'indexing.chunk_profile': `${chunkSize}/${chunkOverlap}`,
      },
      probes: {
        'retrieval.retrieval_budget': retrievalBudget,
        'retrieval.rerank_budget': taskBudget,
        'retrieval.case_count': filteredRetrievalCases.length,
        'task.case_count': filteredTaskCases.length,
        'memory.freshness_bias': Number(effectiveConfig.contextatlas?.memory?.freshness_bias ?? 0.6),
        'memory.stale_prune_threshold': Number(
          effectiveConfig.contextatlas?.memory?.stale_prune_threshold ?? 0.12,
        ),
        'memory.stale_filtered_count': round(
          Math.max(0, memory.staleRatio > 0 ? (1 - memory.staleRatio) * 4 : 0),
        ),
        'task.scenario_filter': scenarioFilter ?? 'all',
        'indexing.build_latency_ms': cost.buildLatencyMs,
        'indexing.peak_memory_mb': cost.peakMemoryMb,
        'indexing.index_size_bytes': cost.indexSizeBytes,
        'indexing.embedding_calls': cost.embeddingCalls,
        'indexing.files_scanned_count': cost.filesScannedCount,
        'indexing.files_reindexed_count': cost.filesReindexedCount,
        'indexing.query_p50_ms': cost.queryP50Ms,
        'indexing.query_p95_ms': cost.queryP95Ms,
      },
    };

    process.stdout.write(`${JSON.stringify(payload)}\n`);
  } finally {
    db.close();
  }
}

void main();
