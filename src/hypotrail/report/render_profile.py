"""The Data profile section of a Bike Study's page: the profile the command hands over, drawn as SVG of rects beside its numbers.

The numbers are the read's (`hypotrail.ml.profile`, through the CLI): this module computes only where a rect lies and how long
it is. Each `svg` holds `rect` elements only, with no text and no style attribute; its shades are classes of the page's style.
Every number of a table carries the key path of the read it is taken from (`data-path`). A refusal of the read is handed over as
its code, and the section then holds one sentence with it and no figure.
"""

import datetime

from hypotrail.report.markup import Safe, cell, join, number, paragraph, sub, table, tag

DIFFERS_SENTENCE = "The Workload as declared now no longer gives this Study's Protocol; the profile is read from the Study's own data."
NOT_AVAILABLE = "not available at prediction time"
# The classes a matrix cell is shaded by, from its |value|: the upper bounds of the first four, the last for the rest.
SHADES = (0.2, 0.4, 0.6, 0.8)
STYLE = """
svg.pf{display:block;width:100%;max-width:720px;height:auto;margin:14px 0 0;background:var(--paper);border:1px solid var(--line2)}
svg.pf rect{fill:var(--teal)}
svg.pf rect.band{fill:var(--bg2)}
svg.pf rect.band.train{fill:color-mix(in srgb,var(--gold) 30%,var(--bg2))}
svg.pf rect.box{fill:color-mix(in srgb,var(--teal) 45%,transparent)}
svg.pf rect.none{fill:var(--line)}
svg.pf rect.s0{fill:color-mix(in srgb,var(--violet) 8%,var(--paper))}
svg.pf rect.s1{fill:color-mix(in srgb,var(--violet) 28%,var(--paper))}
svg.pf rect.s2{fill:color-mix(in srgb,var(--violet) 48%,var(--paper))}
svg.pf rect.s3{fill:color-mix(in srgb,var(--violet) 70%,var(--paper))}
svg.pf rect.s4{fill:var(--pink)}
svg.pf.matrix{max-width:420px}
.pfrow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;align-items:start}
.pfrow svg.pf{margin-top:14px}
@media (max-width:860px){.pfrow{grid-template-columns:minmax(0,1fr)}}
"""
WIDTH, HEIGHT = 720, 180


def _n(value) -> str:
    """A coordinate, short and exact enough for a drawing."""
    return format(round(value, 3), "g")


def _rect(x, y, width, height, **attributes) -> Safe:
    return tag("rect", "", x=_n(x), y=_n(y), width=_n(max(width, 0)), height=_n(max(height, 0)), **attributes)


def _svg(rects, width=WIDTH, height=HEIGHT, **attributes) -> Safe:
    classes = " ".join(["pf", attributes.pop("class_", "")]).strip()
    return tag("svg", join(rects), viewBox=f"0 0 {width} {height}", preserveAspectRatio="none", aria_hidden="true", class_=classes, **attributes)


def _at(path, value) -> Safe:
    """A number of the read, with the key path it is taken from."""
    return tag("span", number(value), data_path=path)


def _code_at(path, value) -> Safe:
    return tag("code", value, data_path=path)


def _text_at(path, value) -> Safe:
    return tag("span", value, data_path=path)


def _day(text: str) -> int:
    return datetime.date.fromisoformat(text).toordinal()


def _scale(low, high):
    span = (high - low) or 1
    return lambda v: (v - low) / span


# --- the four figures -------------------------------------------------------------------------------------------------------------


def _target(read) -> list:
    band, series = read["band"], read["target"]["series"]
    first, last = min(_day(p["first"]) for p in band), max(_day(p["last"]) for p in band)
    days = last - first + 1
    unit = WIDTH / days
    top = max((point["value"] for point in series), default=0) or 1
    plot = HEIGHT - 24
    rects = [_rect((_day(p["first"]) - first) * unit, plot + 6, (_day(p["last"]) - _day(p["first"]) + 1) * unit, 18, class_=f"band {p['name']}") for p in band]
    rects += [
        _rect((_day(point["date"]) - first) * unit, plot - plot * point["value"] / top, unit, plot * point["value"] / top, data_date=point["date"])
        for point in series
    ]
    target = read["target"]
    quartiles = target["figures"]["quartiles"] or {}
    return [
        sub(f"The target, {target['column']} ({target['unit']}), over train"),
        _svg(rects, id="profile-target"),
        paragraph("Under the days, the Partition band, from left to right: " + ", ".join(p["name"] for p in band) + ". Only the train days carry a value."),
        tag("div", join([tag("div", table(
            "profile-band",
            ["Partition", "First day", "Last day"],
            [[_text_at(f"band[{i}].name", p["name"]), _text_at(f"band[{i}].first", p["first"]), _text_at(f"band[{i}].last", p["last"])] for i, p in enumerate(band)],
        )), tag("div", table(
            "profile-target-figures",
            ["Days", *quartiles],
            [[number(len(series)), *(_at(f"target.figures.quartiles.{name}", value) for name, value in quartiles.items())]],
            numeric=tuple(range(len(quartiles) + 1)),
        ))]), class_="pfrow"),
    ]


BAR_HEIGHT = 120


def _bars(counts) -> Safe:
    """One bar per element of `counts`, each a dict with its `count`, side by side."""
    top = max((c["count"] for c in counts), default=0) or 1
    width = WIDTH / max(len(counts), 1)
    return _svg([_rect(i * width + 1, BAR_HEIGHT * (1 - c["count"] / top), width - 2, BAR_HEIGHT * c["count"] / top) for i, c in enumerate(counts)], height=BAR_HEIGHT)


def _beside(figure, numbers) -> Safe:
    """A figure and the table of the numbers it is drawn from, side by side on a wide page."""
    return tag("div", join([tag("div", figure), tag("div", numbers)]), class_="pfrow")


def _distribution(index, column) -> list:
    path = f"columns[{index}]"
    title = f"{column['name']}, {column['kind']}" + ("" if column["available"] else f", {NOT_AVAILABLE}")
    distribution = column["distribution"]
    out = [sub(title)]
    if distribution["counts"] is not None:
        counts = distribution["counts"]
        out.append(_beside(
            _bars(counts),
            table(
                f"profile-column-{index}",
                ["Value", "Train days"],
                [[_text_at(f"{path}.distribution.counts[{i}].value", c["value"]), _at(f"{path}.distribution.counts[{i}].count", c["count"])] for i, c in enumerate(counts)],
                numeric=(1,),
            ),
        ))
    elif distribution["histogram"] is not None:
        bins = distribution["histogram"]
        out.append(_beside(
            _bars(bins),
            table(
                f"profile-column-{index}",
                ["Low", "High", "Train days"],
                [[_at(f"{path}.distribution.histogram[{i}].{key}", b[key]) for key in ("low", "high", "count")] for i, b in enumerate(bins)],
                numeric=(0, 1, 2),
            ),
        ))
    else:
        out.append(paragraph(f"No distribution: {distribution['unavailable']}."))
    return out


def _shade(value) -> str:
    if value is None:
        return "none"
    return f"s{sum(abs(value) >= bound for bound in SHADES)}"


def _matrix(read) -> list:
    associations = read["associations"]
    order, level = associations["order"], associations["level"]
    position = {name: i for i, name in enumerate(order)}
    available = {c["name"]: c["available"] for c in read["columns"]}
    size = 20
    rects = []
    for pair in associations["pairs"]:
        row, col = sorted((position[pair["a"]], position[pair["b"]]))
        rects.append(_rect(col * size, row * size, size - 1, size - 1, class_=_shade(pair["value"])))
    side = size * len(order)
    rows = [
        [number(i + 1), _text_at(f"associations.order[{i}]", name), "" if available[name] else NOT_AVAILABLE]
        for i, name in enumerate(order)
    ]
    pairs = [
        [
            _text_at(f"associations.pairs[{i}].a", p["a"]),
            _text_at(f"associations.pairs[{i}].b", p["b"]),
            _text_at(f"associations.pairs[{i}].measure", p["measure"]),
            _at(f"associations.pairs[{i}].value", p["value"]),
            _at(f"associations.pairs[{i}].rows", p["rows"]),
            join(["flagged: ", _at(f"associations.pairs[{i}].value", p["value"]), " reaches the level ", _at("associations.level", level)]) if p["flagged"] else "",
            "" if p["reason"] is None else _text_at(f"associations.pairs[{i}].reason", p["reason"]),
        ]
        for i, p in enumerate(associations["pairs"])
    ]
    return [
        sub("The association matrix of the columns, without the target"),
        paragraph(
            "One cell per pair above the diagonal, the columns in the clustering order of the table beside; the darker the "
            f"cell, the larger the absolute value, and a pair with no value is pale grey. A pair whose absolute value reaches {number(level)} is flagged."
        ),
        _beside(_svg(rects, width=side, height=side, class_="matrix", id="profile-matrix"), table("profile-order", ["Position", "Column", "Availability"], rows, numeric=(0,))),
        table("profile-pairs", ["A", "B", "Measure", "Value", "Rows", "Flagged", "Reason"], pairs, numeric=(3, 4)),
        table(
            "profile-measures",
            ["Measure", "What it is"],
            [[name, _text_at(f"associations.measures.{name}", text)] for name, text in associations["measures"].items()],
        ),
    ]


def _scatter(entry) -> Safe:
    points = entry["points"]
    xs, ys = [p["feature"] for p in points], [p["target"] for p in points]
    fx, fy = _scale(min(xs), max(xs)), _scale(min(ys), max(ys))
    dot = 4
    return _svg([_rect(fx(x) * (WIDTH - dot), (1 - fy(y)) * (HEIGHT - dot), dot, dot) for x, y in zip(xs, ys)])


def _per_value(index, entry) -> list:
    values = entry["values"]
    known = [v["figures"]["quartiles"] for v in values if v["figures"]["quartiles"]]
    low, high = min((q["min"] for q in known), default=0), max((q["max"] for q in known), default=1)
    fy = _scale(low, high)
    width = WIDTH / max(len(values), 1)
    rects = []
    for i, v in enumerate(values):
        q = v["figures"]["quartiles"]
        if not q:
            continue
        x = i * width
        rects.append(_rect(x + width / 2 - 1, (1 - fy(q["max"])) * HEIGHT, 2, (fy(q["max"]) - fy(q["min"])) * HEIGHT))
        rects.append(_rect(x + width * 0.2, (1 - fy(q["q3"])) * HEIGHT, width * 0.6, (fy(q["q3"]) - fy(q["q1"])) * HEIGHT, class_="box"))
        rects.append(_rect(x + width * 0.2, (1 - fy(q["median"])) * HEIGHT - 1, width * 0.6, 2))
    path = f"against_target[{index}].values"
    rows = [
        [_text_at(f"{path}[{i}].value", v["value"]), _at(f"{path}[{i}].count", v["count"]),
         *(_at(f"{path}[{i}].figures.quartiles.{k}", (v["figures"]["quartiles"] or {}).get(k)) for k in ("min", "q1", "median", "q3", "max"))]
        for i, v in enumerate(values)
    ]
    return [_beside(_svg(rects), table(f"profile-against-{index}", ["Value", "Train days", "min", "q1", "median", "q3", "max"], rows, numeric=(1, 2, 3, 4, 5, 6)))]


def _against(read) -> list:
    out = [sub("The target against each allowed feature")]
    for i, entry in enumerate(read["against_target"]):
        heading = join([
            tag("b", entry["name"]), f" ({entry['kind']}): ", _text_at(f"against_target[{i}].measure", entry["measure"]), " ",
            _at(f"against_target[{i}].value", entry["value"]), " over ", _at(f"against_target[{i}].rows", entry["rows"]), " train days",
            "" if entry["reason"] is None else join([", no value: ", _text_at(f"against_target[{i}].reason", entry["reason"])]),
        ])
        out.append(paragraph(heading))
        if entry["points"] is not None:
            out.append(_scatter(entry) if entry["points"] else paragraph("No point."))
        else:
            out.extend(_per_value(i, entry))
    return out


def section(profile) -> list:
    """The body of the Data profile section, from what the command handed over: the read (`ok` true), or its refusal's code."""
    if profile is None:
        return [paragraph("No data profile was handed to this page.")]
    if not profile["ok"]:
        return [paragraph(join(["The data profile could not be read: ", tag("code", profile["code"]), "."]))]
    # The Partitions the read leaves out are the band's others: the role names stay with the Track (`hypotrail.ml.partitions`).
    others = [tag("code", p["name"]) for p in profile["band"] if p["name"] != profile["partition"]]
    out = [
        paragraph(
            join([
                "Read from the ", _at("items", profile["items"]), " ", _code_at("partition", profile["partition"]), " days of the data. No ",
                join([others[0], *(join([" or ", other]) for other in others[1:])]) if others else "other",
                " value is read. An association between two predictors is not an effect on the target.",
            ]),
        )
    ]
    if profile["workload_protocol"] == "differs":
        out.append(paragraph(DIFFERS_SENTENCE))
    out += _target(profile)
    out.append(sub("One distribution per column, over train"))
    for i, column in enumerate(profile["columns"]):
        out += _distribution(i, column)
    out += _matrix(profile)
    out += _against(profile)
    return [cell(fragment) for fragment in out]
