// The panel's style holds literal colours only in its two charter palette blocks, one per theme kind, its high-contrast block names
// VS Code's variables only, and its script sets no style (D-136, C4 amended).
import { test, type TestContext } from "node:test";
import assert from "node:assert/strict";
import contract from "../contract.json";
import { documentFor, keptObject, partsOf, success } from "./panel-harness";

/**
 * The named colours and the system colours of CSS Color Module Level 4 (https://www.w3.org/TR/css-color-4/, sections 6.1
 * and 6.2), matched without regard to case.
 */
const NAMED_COLOURS = new Set(
  [
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue",
    "chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey",
    "darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray",
    "darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen",
    "fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki",
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen",
    "lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime",
    "limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue",
    "mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive",
    "olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum",
    "powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver",
    "skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white",
    "whitesmoke yellow yellowgreen",
    "accentcolor accentcolortext activetext buttonborder buttonface buttontext canvas canvastext field fieldtext graytext",
    "highlight highlighttext linktext mark marktext selecteditem selecteditemtext visitedtext",
  ]
    .join(" ")
    .split(" "),
);

// The names a script would set a style with.
const STYLE_SETTERS = [".style", "setProperty", "cssText", "insertRule", "adoptedStyleSheets"];

// The value of each declaration of a style.
const valuesOf = (style: string): string[] =>
  [...style.matchAll(/\{([^{}]*)\}/g)]
    .flatMap((block) => block[1].split(";"))
    .filter((declaration) => declaration.includes(":"))
    .map((declaration) => declaration.slice(declaration.indexOf(":") + 1));

function withoutVar(value: string): string {
  for (let before = ""; before !== value; ) [before, value] = [value, value.replace(/var\([^()]*\)/g, " ")];
  return value;
}

// Whether one form of `colour_forms` stands in a style: a hexadecimal colour, a functional notation by its name, or a named
// colour as a whole value token outside `var(…)`.
function holds(style: string, form: string): boolean {
  const values = valuesOf(style);
  if (form === "hexadecimal") return values.some((value) => /#[0-9a-f]{3,8}(?![\w-])/i.test(value));
  if (form === "named") return values.some((value) => withoutVar(value).split(/[\s,()/]+/).some((token) => NAMED_COLOURS.has(token.toLowerCase())));
  const name = /^([a-z-]+)\(\)$/.exec(form)?.[1];
  assert.ok(name, `a form of colour_forms this test cannot read: ${form}`);
  return values.some((value) => new RegExp(`(?<![\\w-])${name}\\(`, "i").test(value));
}

// A style that holds `form` and no other colour.
function plantOf(form: string): string {
  if (form === "hexadecimal") return "body { border: 1px solid #c0ffee; }";
  if (form === "named") return "body { box-shadow: 0 0 2px Red; }";
  return `body { outline: 1px solid ${form.slice(0, -2)}(0 0 0); }`;
}

async function styleAndScript(t: TestContext): Promise<{ style: string; script: string }> {
  const { document } = await documentFor(t, success(keptObject("status-success")));
  return partsOf(document);
}

// The selectors of the palette blocks: the charter's two, which alone hold literal colours, and the high-contrast one.
const PALETTES = ["body.vscode-dark", "body.vscode-light"];
const HIGH_CONTRAST = "body.vscode-high-contrast";
const rulesOf = (style: string): [string, string][] => [...style.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => [match[1].trim(), `{${match[2]}}`]);
// The style with its two charter palette blocks left out.
const outsideThePalettes = (style: string): string => rulesOf(style).filter(([selector]) => !PALETTES.includes(selector)).map(([selector, body]) => `${selector} ${body}`).join("\n");

test("the style holds the two charter palette blocks and the high-contrast block, each once, first and in that order", async (t) => {
  const { style } = await styleAndScript(t);
  assert.deepEqual(rulesOf(style).slice(0, 3).map(([selector]) => selector), [...PALETTES, HIGH_CONTRAST]);
  for (const selector of [...PALETTES, HIGH_CONTRAST]) assert.equal(rulesOf(style).filter(([each]) => each === selector).length, 1, selector);
  for (const selector of PALETTES) assert.ok(contract.colour_forms.some((form) => holds(rulesOf(style).find(([each]) => each === selector)![1], form)), selector);
});

test("each declaration of the high-contrast block takes one of VS Code's variables, or none at all", async (t) => {
  const { style } = await styleAndScript(t);
  const block = rulesOf(style).find(([selector]) => selector === HIGH_CONTRAST)![1];
  const values = valuesOf(block);
  assert.ok(values.length > 10);
  for (const value of values) assert.ok(/^\s*none\s*$/.test(value) || [...value.matchAll(/var\(--([a-z0-9-]+)/gi)].every((match) => match[1].startsWith("vscode-")) && /var\(--vscode-/.test(value), value);
  assert.deepEqual(contract.colour_forms.filter((form) => holds(block, form)), []);
});

test("a planted #fff in a rule outside the palette blocks is found, and the same colour inside a palette block is not", async (t) => {
  const { style } = await styleAndScript(t);
  assert.equal(holds(outsideThePalettes(`${style}\nmain { color: #fff; }`), "hexadecimal"), true);
  assert.equal(holds(outsideThePalettes(style.replace("body.vscode-dark{", "body.vscode-dark{ --planted:#fff;")), "hexadecimal"), false);
});

for (const form of contract.colour_forms) {
  test(`the style of the document holds no literal colour of the form ${form} outside its two palette blocks`, async (t) => {
    const { style } = await styleAndScript(t);
    assert.ok(style.length > 0);
    assert.equal(holds(outsideThePalettes(style), form), false, outsideThePalettes(style));
  });

  test(`a planted style that holds a colour of the form ${form} is found`, () => {
    assert.equal(holds(plantOf(form), form), true);
  });
}

test("a planted style whose only colours are a theme variable and the three keywords holds no literal colour", () => {
  const style = "body { color: var(--vscode-charts-red); background: transparent; border-color: currentColor; outline-color: inherit; }";
  assert.deepEqual(contract.colour_forms.filter((form) => holds(style, form)), []);
});

test("the style sets the color and the background of body from variables that each palette block defines", async (t) => {
  const { style } = await styleAndScript(t);
  const body = /(?:^|\})\s*body\s*\{([^{}]*)\}/.exec(style)?.[1] ?? "";
  for (const property of ["color", "background"]) {
    const name = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*var\\((--[a-z0-9-]+)\\)\\s*(?:;|$)`).exec(body)?.[1];
    assert.ok(name && !name.startsWith("--vscode-"), property);
    for (const selector of [...PALETTES, HIGH_CONTRAST]) assert.ok(rulesOf(style).find(([each]) => each === selector)![1].includes(`${name}:`), `${selector} defines ${name}`);
  }
});

for (const name of STYLE_SETTERS) {
  test(`the script of the document sets no style: it holds no ${name}`, async (t) => {
    const { script } = await styleAndScript(t);
    assert.ok(script.length > 0);
    assert.equal(script.includes(name), false);
  });
}
