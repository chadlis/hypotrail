// The panel's style sets no literal colour, and its script sets no style: every colour comes from VS Code's theme.
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

for (const form of contract.colour_forms) {
  test(`the style of the document holds no literal colour of the form ${form}`, async (t) => {
    const { style } = await styleAndScript(t);
    assert.ok(style.length > 0);
    assert.equal(holds(style, form), false, style);
  });

  test(`a planted style that holds a colour of the form ${form} is found`, () => {
    assert.equal(holds(plantOf(form), form), true);
  });
}

test("a planted style whose only colours are a theme variable and the three keywords holds no literal colour", () => {
  const style = "body { color: var(--vscode-charts-red); background: transparent; border-color: currentColor; outline-color: inherit; }";
  assert.deepEqual(contract.colour_forms.filter((form) => holds(style, form)), []);
});

test("the style sets the color and the background of body from theme variables of VS Code", async (t) => {
  const { style } = await styleAndScript(t);
  const body = /(?:^|\})\s*body\s*\{([^{}]*)\}/.exec(style)?.[1] ?? "";
  for (const property of ["color", "background"]) assert.match(body, new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*var\\(--vscode-[a-z0-9-]+\\)\\s*(?:;|$)`), property);
});

for (const name of STYLE_SETTERS) {
  test(`the script of the document sets no style: it holds no ${name}`, async (t) => {
    const { script } = await styleAndScript(t);
    assert.ok(script.length > 0);
    assert.equal(script.includes(name), false);
  });
}
