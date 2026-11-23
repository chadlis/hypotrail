// Deep links: a `vscode://` URI of one of the two forms of contract.json opens the panel on a Study the walk finds in
// the workspace. Anything else is refused with one notification. A link never writes.
import * as vscode from "vscode";
import * as path from "node:path";
import contract from "../contract.json";
import { openPanel, type Target } from "./panel";
import { findStudies, workspaceFolders } from "./studies";

export type LinkUri = { authority: string; path: string; query: string; fragment: string };

type Form = { authority: string; path: string; key: string };

function formOf(text: string): Form {
  const match = text.match(/^vscode:\/\/([^/?#]+)(\/[^?#]*)\?([^=]+)=\{path\}$/);
  if (!match) throw new Error(`contract.json holds a link form that cannot be read: ${text}`);
  return { authority: match[1], path: match[2], key: match[3] };
}

const [STUDY_FORM, DECISION_FORM] = contract.link_forms.map(formOf);
const DECISION_ID = new RegExp(contract.link_decision_id);

// The target a link names, read from its parts alone; undefined when it is not of one of the two forms.
function targetOf(uri: LinkUri): Target | undefined {
  if (uri.authority !== STUDY_FORM.authority || uri.fragment !== "") return undefined;
  const prefix = `${STUDY_FORM.key}=`;
  if (!uri.query.startsWith(prefix)) return undefined;
  const study = uri.query.slice(prefix.length);
  if (study.length === 0 || study.length > contract.link_max_path || study.includes("\0") || !path.isAbsolute(study)) return undefined;
  if (uri.path === STUDY_FORM.path) return { study };
  const [before, after] = DECISION_FORM.path.split("{uuid}");
  if (!uri.path.startsWith(before) || !uri.path.endsWith(after)) return undefined;
  const decision = uri.path.slice(before.length, uri.path.length - after.length);
  return DECISION_ID.test(decision) ? { study, decision } : undefined;
}

export async function handleLink(uri: LinkUri): Promise<void> {
  const target = targetOf(uri);
  const studies = target === undefined ? [] : await findStudies(workspaceFolders());
  if (target === undefined || !studies.includes(target.study)) {
    void vscode.window.showErrorMessage(contract.link_refusal);
    return;
  }
  openPanel(target);
}
