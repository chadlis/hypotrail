"""Properties of the block reader of `text_facts_v1` (#271), each over the four identifier kinds, with a fixed seed."""

import json
import random
import re

import pytest
from _study_helpers import EXAMPLES

from hypotrail.core import text_facts

CONFIG = json.loads((EXAMPLES / "chinook_prose" / "scoring" / "text-facts.json").read_text(encoding="utf-8"))
KINDS = tuple(CONFIG["identifier_kinds"])
TRIALS = 60
MARKERS = ("-", "*", "+", "1.", "1)")
JOINERS = (",", ";", "&", "and", "or", ", and", ", or")
DELIMITERS = ("*", "**", "_", "__")


def reading(text: str) -> tuple:
    return text_facts.identifiers_in(text, CONFIG), set(text_facts.fact_numbers(text, CONFIG))


def rng(kind: str, name: str) -> random.Random:
    return random.Random(f"{name}:{kind}")


def values(r: random.Random, n: int, low=1, high=9999) -> list:
    return [str(v) for v in r.sample(range(low, high), n)]


def lead_in(kind: str) -> str:
    return f"{kind.capitalize()}s:"


def listed(items: list, marker: str, start: int = 1, loose: bool = False) -> str:
    """The items as a Markdown list; an ordered marker ("1." or "1)") is numbered from `start`."""
    lines = []
    for index, item in enumerate(items):
        mark = f"{start + index}{marker[-1]}" if marker[0].isdigit() else marker
        lines.append(f"{mark} {item}")
    return ("\n\n" if loose else "\n").join(lines)


def ids(kind: str, items) -> set:
    return {(kind, v) for v in items}


@pytest.mark.parametrize("kind", KINDS)
def test_p1_changing_or_renumbering_the_markers_of_a_list_after_a_lead_in_changes_nothing_read(kind):
    r = rng(kind, "P1")
    for _ in range(TRIALS):
        items = values(r, r.randint(1, 6))
        baseline = reading(f"{lead_in(kind)}\n{listed(items, '-')}")
        assert baseline[0] == ids(kind, items)
        for marker in MARKERS:
            text = f"{lead_in(kind)}\n{listed(items, marker, start=r.randint(1, 500))}"
            assert reading(text) == baseline, text


@pytest.mark.parametrize("kind", KINDS)
def test_p2_a_marker_number_is_never_a_fact_number(kind):
    r = rng(kind, "P2")
    for _ in range(TRIALS):
        start = r.randint(1, 900)
        items = values(r, r.randint(1, 6), 1000, 9999)
        for body in ([f"{kind} {v}" for v in items], [f"paid ${v}.50" for v in items], items):
            for prefix in ("", f"{lead_in(kind)}\n", "Some text:\n"):
                for marker in ("1.", "1)"):
                    text = prefix + listed(body, marker, start=start)
                    markers = {float(start + i) for i in range(len(body))}
                    assert markers.isdisjoint(reading(text)[1]), text


@pytest.mark.parametrize("kind", KINDS)
def test_p3_a_tight_list_and_a_loose_list_read_the_same(kind):
    r = rng(kind, "P3")
    for _ in range(TRIALS):
        items = values(r, r.randint(1, 6))
        body = r.choice([items, [f"{kind} {v}" for v in items], [f"{v} (${v}.99)" for v in items]])
        prefix = r.choice(["", f"{lead_in(kind)}\n", "Here they are:\n"])
        marker = r.choice(MARKERS)
        assert reading(prefix + listed(body, marker, loose=True)) == reading(prefix + listed(body, marker)), body


def sentence(r: random.Random, kind: str) -> str:
    a, b, c = values(r, 3)
    return r.choice(
        [
            f"See {kind} {a}.",
            f"{kind.capitalize()}s {a}, {b} and {c} are due.",
            f"It cost ${a}.{int(b) % 100:02d} on 2010-03-11.",
            f"The total is {a}, for {kind} #{b}.",
            f"Number of {kind}s: {a}",
            f"We saw {a} {kind}s and {b} others.",
            f"- {kind} {a}\n- {kind} {b}",
            f"| {kind} {a} | {b} |\n|---|---|\n| {c} | x |",
            f"## {kind.capitalize()} {a}",
        ]
    )


@pytest.mark.parametrize("kind", KINDS)
def test_p4_two_blocks_joined_by_a_blank_line_read_as_the_union_of_their_readings(kind):
    r = rng(kind, "P4")
    for _ in range(TRIALS * 3):
        a, b = values(r, 2)
        first = r.choice([sentence(r, kind), f"See {kind}s {a}, {b}", f"Number of {kind}s", f"The {kind}s are {a} and"])
        second = r.choice([sentence(r, r.choice(KINDS)), f"{a} more are pending", f"and {b} for {kind} {a}", f", {a} and {b}", f"is {b}.", f"- {a}\n- {b}"])
        assert not first.endswith(":")
        (ids_a, numbers_a), (ids_b, numbers_b) = reading(first), reading(second)
        assert reading(f"{first}\n\n{second}") == (ids_a | ids_b, numbers_a | numbers_b), (first, second)


@pytest.mark.parametrize("kind", KINDS)
def test_p5_adding_a_fenced_block_changes_nothing_read_whatever_it_holds(kind):
    r = rng(kind, "P5")
    for _ in range(TRIALS):
        text = sentence(r, kind)
        a, b = values(r, 2)
        content = r.choice([f"invoice 7\n{kind} {a}", f"SELECT {a} FROM t WHERE x = {b};", f"{kind}s:\n- {a}\n- {b}", f"${a}.50 on 2009-05-23"])
        fence = r.choice(["```", "~~~", "```sql"])
        closing = fence[:3]
        block = f"{fence}\n{content}\n{closing}"
        assert reading(f"{block}\n\n{text}") == reading(text), (block, text)
        assert reading(f"{text}\n\n{block}") == reading(text), (block, text)


def wrapped(r: random.Random, token: str) -> str:
    delimiter = r.choice(DELIMITERS)
    return f"{delimiter}{token}{delimiter}"


@pytest.mark.parametrize("kind", KINDS)
def test_p6_wrapping_a_label_an_identifier_or_a_number_in_emphasis_changes_nothing_read(kind):
    r = rng(kind, "P6")
    for _ in range(TRIALS):
        a, b, c = values(r, 3)
        forms = [
            (f"{lead_in(kind)}\n- {a}\n- {b}", lead_in(kind)),
            (f"See {kind} {a} for {c} items.", a),
            (f"See {kind} {a} for {c} items.", c),
            (f"See {kind} {a} for {c} items.", f"{kind} {a}"),
            (f"{kind.capitalize()}s {a}, {b} and {c}.", b),
            (f"It cost ${a}.50 in total.", f"${a}.50"),
        ]
        text, token = r.choice(forms)
        emphasised = re.sub(rf"(?<![\w.]){re.escape(token)}(?![\w.])", lambda _: wrapped(r, token), text, count=1)
        assert emphasised != text
        assert reading(emphasised) == reading(text), (text, token)
    assert reading(f"{kind} 1_2")[0] == {(kind, "12")}
    assert reading(f"The {kind}_id 34 row.") == (set(), {34.0})


def chain(r: random.Random, items: list) -> str:
    text = items[0]
    for item in items[1:]:
        joiner = r.choice(JOINERS)
        before = r.choice(["", " ", "\n"]) if joiner[0] in ",;&" else r.choice([" ", "\n", " \n"])
        after = r.choice([" ", "\n", " \n  "])
        text += f"{before}{joiner}{after}{r.choice(['', '#'])}{item}"
    return text


@pytest.mark.parametrize("kind", KINDS)
def test_p7_a_chain_of_one_to_ten_items_with_any_mix_of_joiners_reads_every_item(kind):
    r = rng(kind, "P7")
    for n in range(1, 11):
        for _ in range(TRIALS // 2):
            items = values(r, n)
            text = f"See {kind}s {chain(r, items)}."
            assert reading(text) == (ids(kind, items), set()), text


@pytest.mark.parametrize("kind", KINDS)
def test_p8_a_bare_space_or_a_newline_between_two_numbers_never_joins_them(kind):
    r = rng(kind, "P8")
    for _ in range(TRIALS):
        a, b = values(r, 2)
        separator = r.choice([" ", "  ", "\n", " \n", "\t"])
        text = f"{kind}s {a}{separator}{b}"
        assert reading(text) == ({(kind, a)}, {float(b)}), text


ANNOTATIONS = ("($0.99)", "— $1.98", "— 2009-05-23", "2010-03-11 00:00:00", "— 2011-10-04T08:30:00 — $13.86", "paid", "(refunded)", "for £3.50")


@pytest.mark.parametrize("kind", KINDS)
def test_p9_an_annotation_after_a_labelled_items_leading_number_keeps_its_identifier(kind):
    r = rng(kind, "P9")
    for _ in range(TRIALS):
        items = values(r, r.randint(1, 5))
        body = [f"{v} {r.choice(ANNOTATIONS)}" for v in items]
        text = f"{lead_in(kind)}\n{listed(body, r.choice(MARKERS), start=r.randint(1, 50))}"
        assert reading(text)[0] == ids(kind, items), text


@pytest.mark.parametrize("kind", KINDS)
def test_p10_crlf_and_lf_line_ends_read_the_same(kind):
    r = rng(kind, "P10")
    for _ in range(TRIALS):
        items = values(r, r.randint(1, 5))
        text = r.choice(
            [
                f"{lead_in(kind)}\n{listed(items, r.choice(MARKERS), loose=r.random() < 0.5)}\n\nTotal: ${items[0]}.50",
                f"{kind.capitalize()}s {items[0]},\n{' and '.join(items[1:]) or items[0]}.",
                f"| {kind} | n |\n|---|---|\n| {kind} {items[0]} | 3 |\n\n```\n{kind} 7\n```",
                sentence(r, kind),
            ]
        )
        assert reading(text.replace("\n", "\r\n")) == reading(text), text
