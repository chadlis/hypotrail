// The four default themes of VS Code as headless Chrome is given them, and the texts of a page drawn under AA contrast, for the
// tests that look at a document as a browser draws it.

// The defaults of VS Code's Light+, Dark+, High Contrast and High Contrast Light for the variables the style reads, as the class
// VS Code gives the body and the variables; a variable a theme leaves undefined is left out.
export const THEMES: Record<string, { kind: string; variables: Record<string, string> }> = {
  light: {
    kind: "vscode-light",
    variables: {
      "panel-border": "rgba(128,128,128,0.35)", foreground: "#616161", "editor-foreground": "#000000", "editor-background": "#ffffff", descriptionForeground: "#717171",
      "textLink-foreground": "#006ab1", focusBorder: "#0090f1", "button-background": "#007acc", "button-foreground": "#ffffff", "button-hoverBackground": "#0062a3",
      "button-secondaryBackground": "#5f6a79", "button-secondaryForeground": "#ffffff", "textBlockQuote-background": "#f2f2f2", "inputValidation-errorBorder": "#be1100",
      "list-hoverBackground": "#f0f0f0", "list-inactiveSelectionBackground": "#e4e6f1", "editorWidget-background": "#f3f3f3", "charts-blue": "#1a85ff",
      "charts-orange": "#d18616", "charts-lines": "rgba(97,97,97,0.5)", "charts-foreground": "#616161", "badge-background": "#c4c4c4", "badge-foreground": "#333333",
      "editorWarning-foreground": "#bf8803",
    },
  },
  dark: {
    kind: "vscode-dark",
    variables: {
      "panel-border": "rgba(128,128,128,0.35)", foreground: "#cccccc", "editor-foreground": "#d4d4d4", "editor-background": "#1e1e1e", descriptionForeground: "rgba(204,204,204,0.7)",
      "textLink-foreground": "#3794ff", focusBorder: "#007fd4", "button-background": "#0e639c", "button-foreground": "#ffffff", "button-hoverBackground": "#1177bb",
      "button-secondaryBackground": "#3a3d41", "button-secondaryForeground": "#ffffff", "textBlockQuote-background": "#222222", "inputValidation-errorBorder": "#be1100",
      "list-hoverBackground": "#2a2d2e", "list-inactiveSelectionBackground": "#37373d", "editorWidget-background": "#252526", "charts-blue": "#3794ff",
      "charts-orange": "#d18616", "charts-lines": "rgba(204,204,204,0.5)", "charts-foreground": "#cccccc", "badge-background": "#4d4d4d", "badge-foreground": "#ffffff",
      "editorWarning-foreground": "#cca700",
    },
  },
  hc: {
    kind: "vscode-high-contrast",
    variables: {
      foreground: "#ffffff", "editor-foreground": "#ffffff", "editor-background": "#000000", descriptionForeground: "rgba(255,255,255,0.7)", "textLink-foreground": "#21a6ff",
      focusBorder: "#f38518", contrastBorder: "#6fc3df", contrastActiveBorder: "#f38518", "button-foreground": "#ffffff", "button-secondaryForeground": "#ffffff",
      "panel-border": "#6fc3df", "inputValidation-errorBorder": "#6fc3df", "list-hoverBackground": "rgba(255,255,255,0.1)", "editorWidget-background": "#0c141f",
      "charts-blue": "#3794ff", "charts-orange": "#d18616", "charts-lines": "rgba(255,255,255,0.5)", "charts-foreground": "#ffffff", "badge-background": "#000000",
      "badge-foreground": "#ffffff", "editorWarning-foreground": "#ffd370",
    },
  },
  hcl: {
    kind: "vscode-high-contrast vscode-high-contrast-light",
    variables: {
      foreground: "#292929", "editor-foreground": "#292929", "editor-background": "#ffffff", descriptionForeground: "rgba(41,41,41,0.7)", "textLink-foreground": "#0f4a85",
      focusBorder: "#006bbd", contrastBorder: "#0f4a85", contrastActiveBorder: "#006bbd", "button-background": "#0f4a85", "button-foreground": "#ffffff",
      "button-hoverBackground": "rgba(15,74,133,0.8)", "button-secondaryBackground": "#ffffff", "button-secondaryForeground": "#292929", "panel-border": "#0f4a85",
      "textBlockQuote-background": "#f2f2f2", "inputValidation-errorBorder": "#0f4a85", "list-hoverBackground": "rgba(15,74,133,0.1)",
      "list-inactiveSelectionBackground": "rgba(15,74,133,0.1)", "editorWidget-background": "#ffffff", "charts-blue": "#1a85ff", "charts-orange": "#d18616",
      "charts-lines": "rgba(41,41,41,0.5)", "charts-foreground": "#292929", "badge-background": "#0f4a85", "badge-foreground": "#ffffff", "editorWarning-foreground": "#895503",
    },
  },
};

// The theme's variables and the part of VS Code's default webview style that sets the text's colour and font, then the body's class;
// the style added carries the nonce of the document's own, which the policy allows.
export function themed(name: string): string {
  const theme = THEMES[name];
  const variables = Object.entries(theme.variables).map(([key, value]) => `--vscode-${key}:${value};`).join("");
  const css = `:root{${variables}--vscode-font-family:sans-serif;--vscode-font-size:13px;}html{background:var(--vscode-editor-background)}body{background-color:transparent;color:var(--vscode-editor-foreground);font-size:var(--vscode-font-size);margin:0;padding:0 20px;}a{color:var(--vscode-textLink-foreground);}`;
  return `(() => { const style = document.createElement("style"); style.nonce = document.querySelector("style").nonce; style.textContent = ${JSON.stringify(css)}; document.head.append(style); document.body.className = ${JSON.stringify(theme.kind)}; return true; })()`;
}

// Each text of the page whose contrast with the colour it stands on, every opacity and every background under it composited, is
// under WCAG's AA: 4.5, or 3 for large text.
export const BELOW_AA = `(() => {
  const parse = (colour) => { const found = /rgba?\\(([^)]+)\\)/.exec(colour); if (!found) return [0, 0, 0, 0]; const parts = found[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1]; };
  const over = (top, under) => [0, 1, 2].map((at) => top[at] * top[3] + under[at] * (1 - top[3])).concat([1]);
  const luminance = (colour) => { const channel = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * channel(colour[0]) + 0.7152 * channel(colour[1]) + 0.0722 * channel(colour[2]); };
  const backgroundOf = (element) => { const chain = []; for (let each = element; each; each = each.parentElement) chain.unshift(each); let colour = parse(getComputedStyle(document.documentElement).backgroundColor); for (const each of chain) { const own = parse(getComputedStyle(each).backgroundColor); if (own[3] > 0) colour = over(own, colour); } return colour; };
  const opacityOf = (element) => { let opacity = 1; for (let each = element; each; each = each.parentElement) opacity *= Number(getComputedStyle(each).opacity); return opacity; };
  const below = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim() || node.parentElement.closest("script, style")) continue;
    const element = node.parentElement;
    const style = getComputedStyle(element);
    const background = backgroundOf(element);
    const own = parse(style.color);
    const colour = over([own[0], own[1], own[2], own[3] * opacityOf(element)], background);
    const [high, low] = [luminance(colour), luminance(background)].sort((a, b) => b - a);
    const ratio = (high + 0.05) / (low + 0.05);
    const size = parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && Number(style.fontWeight) >= 700);
    if (ratio < (large ? 3 : 4.5)) below.push(node.textContent.trim().slice(0, 40) + " " + ratio.toFixed(2));
  }
  return below;
})()`;
