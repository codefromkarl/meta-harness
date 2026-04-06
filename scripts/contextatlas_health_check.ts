import path from 'node:path';
import { pathToFileURL } from 'node:url';

function parseArg(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  if (index === -1) return undefined;
  return process.argv[index + 1];
}

async function importWorkspaceModule<T>(workspaceRoot: string, relativePath: string): Promise<T> {
  const moduleUrl = pathToFileURL(path.join(workspaceRoot, relativePath)).href;
  return import(moduleUrl) as Promise<T>;
}

async function main(): Promise<void> {
  const workspaceRoot = process.cwd();
  const projectId = parseArg('--project-id');
  if (!projectId) {
    throw new Error('--project-id is required');
  }

  const { analyzeIndexHealth } = await importWorkspaceModule<{
    analyzeIndexHealth: (input: { projectIds?: string[] }) => Promise<unknown>;
  }>(workspaceRoot, 'src/monitoring/indexHealth.ts');

  const report = await analyzeIndexHealth({ projectIds: [projectId] });
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

void main();
