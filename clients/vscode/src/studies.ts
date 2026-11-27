// Finds the Studies of the workspace. A Study is a folder that holds a `study.json`; the walk looks for that name and
// does not read the file: what a Study holds is read through the bridge only.
import * as vscode from "vscode";
import { readdir } from "node:fs/promises";
import * as path from "node:path";
import contract from "../contract.json";

const STUDY_FILE = "study.json";

function skipped(name: string): boolean {
  return contract.walk_skipped.some((pattern) => (pattern.endsWith("*") ? name.startsWith(pattern.slice(0, -1)) : name === pattern));
}

// Breadth first, from each workspace folder (depth 0) down to `walk_depth`, visiting at most `walk_max_folders`
// folders in all. A symbolic link is not a folder here, so the walk never follows one.
export async function findStudies(folders: readonly string[]): Promise<string[]> {
  const found: string[] = [];
  const queue = folders.map((folder) => ({ folder: path.resolve(folder), depth: 0 }));
  let visited = 0;
  while (queue.length > 0 && visited < contract.walk_max_folders) {
    const { folder, depth } = queue.shift()!;
    visited += 1;
    let entries;
    try {
      entries = await readdir(folder, { withFileTypes: true });
    } catch {
      continue;
    }
    if (entries.some((entry) => entry.name === STUDY_FILE && entry.isFile())) found.push(folder);
    if (depth >= contract.walk_depth) continue;
    for (const entry of entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
      if (entry.isDirectory() && !skipped(entry.name)) queue.push({ folder: path.join(folder, entry.name), depth: depth + 1 });
    }
  }
  return found.sort();
}

export function workspaceFolders(): string[] {
  return (vscode.workspace.workspaceFolders ?? []).map((folder) => folder.uri.fsPath);
}

// With one Study, that Study; with several, the one the user picks; with none, the message and a way to open the stations.
export async function chooseStudy(showStationsPanel?: () => void): Promise<string | undefined> {
  const studies = await findStudies(workspaceFolders());
  if (studies.length === 0) {
    const showStations = "Show stations";
    const selected = await vscode.window.showInformationMessage(contract.no_study_message, showStations);
    if (selected === showStations) showStationsPanel?.();
    return undefined;
  }
  if (studies.length === 1) return studies[0];
  return vscode.window.showQuickPick(studies, { placeHolder: "Pick the Study to open" });
}
