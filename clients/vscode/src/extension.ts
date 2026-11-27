import * as vscode from "vscode";
import { handleLink } from "./links";
import { openPanel, openStationsPanel } from "./panel";
import { chooseStudy } from "./studies";
import { decideTool, packReadTool as readTool, runTool } from "./tools";

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("hypotrail.openPanel", openStudyPanel),
    vscode.commands.registerCommand("hypotrail.showStations", openStationsPanel),
    vscode.window.registerUriHandler({ handleUri: (uri) => handleLink(uri) }),
    vscode.lm.registerTool("hypotrail_read_study", readTool),
    vscode.lm.registerTool("hypotrail_decide", decideTool),
    vscode.lm.registerTool("hypotrail_run", runTool),
  );
}

async function openStudyPanel(): Promise<void> {
  const study = await chooseStudy(openStationsPanel);
  if (study !== undefined) openPanel({ study });
}

export function deactivate(): void {}
