"""Code-drawn explainer diagrams (pure logic, no network, stdlib only).

Where the AI image endpoint guesses, this module *knows*: every box, arrow and
label is placed deliberately, so the wiring is always correct and Vietnamese
text renders exactly (no diacritic garbage, no stray lettering). It backs the
``diagram`` image style — mechanism posts where correctness beats mood.

Renderers here produce SVG, which browsers display inline on /review. SVG text
is rendered by the *viewer*, so no font ships server-side and the container
needs no new dependency. Graph only accepts raster, so ``render_diagrams``
also screenshots the twin HTML plate (``diagram_html``) to PNG through the
host's Chromium (``browser_shot``) — the draft points at the PNG, the SVG
stays beside it as the re-renderable source.
"""

from __future__ import annotations

import html
import math

from social_bot import iso as iso_module

# Portrait 1080x1350: the same feed real estate as generated photos.
WIDTH = 1080
HEIGHT = 1350

# Brand palette, matching the operator UI tokens (ui._CSS): warm paper, ink,
# one petrol-teal accent. This is an image asset, not page markup, so the
# colours live here rather than in the stylesheet.
_PAPER = "#f6f3ed"
_INK = "#171a19"
_MUTED = "#616963"
_ACCENT = "#0e6b64"
_ACCENT_SOFT = "#dcece9"
_LINE = "#cbc2b1"

_FONT = (
    'font-family=\'FreeSans, "DejaVu Sans", "Noto Sans", "Segoe UI", '
    "Roboto, -apple-system, sans-serif'"
)

# Soft drop shadow: the one depth cue under the solids and their plinths.
_SHADOW = (
    "<filter id='soft' x='-20%' y='-20%' width='140%' height='140%'>"
    "<feDropShadow dx='0' dy='3' stdDeviation='6' flood-color='#171a19' "
    "flood-opacity='0.14'/></filter>"
    "<filter id='soft-sm' x='-20%' y='-20%' width='140%' height='140%'>"
    "<feDropShadow dx='0' dy='2' stdDeviation='4' flood-color='#171a19' "
    "flood-opacity='0.16'/></filter>"
)


def _text(
    x: float,
    y: float,
    size: int,
    content: str,
    *,
    fill: str = _INK,
    anchor: str = "middle",
    bold: bool = False,
    spacing: int = 0,
) -> str:
    weight = " font-weight='700'" if bold else ""
    track = f" letter-spacing='{spacing}'" if spacing else ""
    return (
        f"<text x='{x:g}' y='{y:g}' font-size='{size}' fill='{fill}' "
        f"text-anchor='{anchor}' {_FONT}{weight}{track}>{html.escape(content)}</text>"
    )


def _plate_header(title: str, *, kicker: str = "", subtitle: str = "") -> list[str]:
    """The shared plate chrome: canvas, paper, dotted texture, frame, title.

    Both renderers open the same way, so the two plates read as one family.
    ``kicker`` sits above the title and ``subtitle`` below the accent rule; the
    base plate (neither) keeps the title and rule exactly where they always were.
    """
    title_y = 158 if kicker else 168
    rule_y = 198 if kicker else 208
    parts = [
        (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{WIDTH}' height='{HEIGHT}' "
            f"viewBox='0 0 {WIDTH} {HEIGHT}'>"
        ),
        f"<defs>{_SHADOW}</defs>",
        f"<rect width='{WIDTH}' height='{HEIGHT}' fill='{_PAPER}'/>",
        # Faint dotted paper texture: two offset dot grids, barely visible.
        "<g fill='#cbc2b1' opacity='0.35'>",
        "".join(
            f"<circle cx='{x:g}' cy='{y:g}' r='1.6'/>"
            for y in range(70, HEIGHT - 50, 56)
            for x in range(70, WIDTH - 50, 56)
        ),
        "</g>",
        f"<rect x='28' y='28' width='{WIDTH - 56}' height='{HEIGHT - 56}' rx='24' fill='none' "
        f"stroke='{_LINE}' stroke-width='2'/>",
    ]
    if kicker:
        parts.append(_text(WIDTH / 2, 92, 23, kicker, fill=_MUTED, spacing=4))
    parts.append(_text(WIDTH / 2, title_y, 60, title, bold=True, spacing=2))
    # Accent rule with a centre diamond under the title — no payoff line: the
    # caption tells the story, the image only shows the mechanism.
    parts.append(
        f"<line x1='462' y1='{rule_y:g}' x2='618' y2='{rule_y:g}' stroke='{_ACCENT}' "
        "stroke-width='3' stroke-linecap='round'/>"
    )
    parts.append(
        f"<rect x='532' y='{rule_y - 8:g}' width='16' height='16' rx='3' fill='{_ACCENT}' "
        f"transform='rotate(45 540 {rule_y:g})'/>"
    )
    if subtitle:
        parts.append(_text(WIDTH / 2, rule_y + 44, 26, subtitle, fill=_MUTED))
    return parts


# --- the sparse-index scene --------------------------------------------------
# One chest of drawers per policy, the same chest both times: the index is the
# drawer labels, the data is the drawers. Dense index labels every thin drawer;
# the sparse index labels two deep ones. Same cabinet, fewer cards.

_CHEST_W, _CHEST_D, _CHEST_H = 200.0, 110.0, 184.0
_SBENCH = (-20.0, -10.0, 270.0, 150.0)
_SBOUNDS = (-20.0, -10.0, -18.0, 250.0, 140.0, 184.0)


def _cards(cx: float, cy: float, s: float, n: int, color: str) -> str:
    """A little fan of index cards — how many entries the policy needs."""
    out = []
    for i in range(n):
        x = cx + (i - (n - 1) / 2) * s * 0.6
        out.append(
            f"<rect x='{x - s * 0.3:.1f}' y='{cy - s * 0.62:.1f}' width='{s * 0.6:.1f}' "
            f"height='{s * 1.24:.1f}' rx='{s * 0.1:.1f}' fill='{_PAPER}' stroke='{color}' "
            f"stroke-width='{max(1.8, s * 0.11):.1f}'/>"
        )
    return "".join(out)


def _index_chest(iso_: iso_module.Iso, x: float, y: float, *, drawers: int, hot: bool) -> str:
    """A card-index chest: one drawer front, one index card.

    ``drawers`` thins or deepens the drawers without changing the cabinet, so
    ``1 : 1`` shows six entries and ``1 → 8192`` shows two for the same chest —
    the index shrinks, the data does not. A deep drawer also shows the rows it
    swallows as ruled lines under its card.
    """
    w, d, h = _CHEST_W, _CHEST_D, _CHEST_H
    Y = y + d + 0.4
    parts = [iso_.shadow(x, y, w, d, spread=0.16), iso_.box(x, y, 0, w, d, h, iso_module.WOOD)]
    parts.append(
        iso_.quad(
            [(x + 12, Y, 10), (x + w - 12, Y, 10), (x + w - 12, Y, h - 10), (x + 12, Y, h - 10)],
            "#3a2f22",
        )
    )
    z0, z1 = 14.0, h - 14.0
    dh = (z1 - z0) / drawers
    mark = iso_module.TEAL[1] if hot else "#7b8a84"
    for i in range(drawers):
        dz0, dz1 = z0 + i * dh + 3, z0 + (i + 1) * dh - 3
        parts.append(
            iso_.quad(
                [(x + 15, Y, dz0), (x + w - 15, Y, dz0), (x + w - 15, Y, dz1), (x + 15, Y, dz1)],
                "#ffffff",
                edge="#cdc3b0",
                width=1.3,
            )
        )
        ch = min(dh * 0.44, 16.0)
        cz = dz1 - 6 - ch / 2
        parts.append(
            iso_.quad(
                [
                    (x + 26, Y, cz - ch / 2),
                    (x + 88, Y, cz - ch / 2),
                    (x + 88, Y, cz + ch / 2),
                    (x + 26, Y, cz + ch / 2),
                ],
                "#ffffff",
                edge=mark,
                width=1.5,
            )
        )
        parts.append(iso_.line((x + 30, Y, cz), (x + 84, Y, cz), mark, width=2.2))
        parts.append(iso_.line((x + w - 42, Y, cz), (x + w - 26, Y, cz), "#9a8f7c", width=3.0))
        span = (cz - ch / 2 - 6) - (dz0 + 6)
        rows = max(0, int(span // 13))
        for r in range(rows):
            lz = dz0 + 6 + (r + 0.5) * span / rows
            parts.append(iso_.line((x + 30, Y, lz), (x + w - 62, Y, lz), "#d3cbbb", width=2.2))
    parts.append(
        iso_.line((x + 10, Y, h - 6), (x + w - 10, Y, h - 6), iso_module.WOOD[3], width=2.0)
    )
    parts.append(
        iso_.quad(
            [
                (x + 16, y + 14, h + 0.4),
                (x + w - 16, y + 14, h + 0.4),
                (x + w - 16, y + d - 14, h + 0.4),
                (x + 16, y + d - 14, h + 0.4),
            ],
            iso_module.WOOD[0],
            edge=iso_module.WOOD[3],
            width=1.6,
        )
    )
    return "".join(parts)


def _index_scene(iso_: iso_module.Iso, *, drawers: int, hot: bool) -> str:
    """One policy's bench: a single index chest, painted on its plinth."""
    bx, by, bw, bd = _SBENCH
    parts = [
        iso_.shadow(bx, by, bw, bd, spread=0.16),
        iso_.box(bx, by, -18, bw, bd, 18, iso_module.WOOD),
    ]
    parts.append(_index_chest(iso_, 30.0, 8.0, drawers=drawers, hot=hot))
    return "".join(parts)


def render_sparse_index(
    *,
    title: str = "SPARSE INDEX",
    kicker: str = "CLICKHOUSE",
    subtitle: str = "Mỗi mục chỉ mục phủ bao nhiêu dòng?",
    left_label: str = "DENSE INDEX",
    left_name: str = "1 : 1",
    left_verdict: str = "tốn RAM hơn",
    right_label: str = "CLICKHOUSE",
    right_name: str = "1 → 8192",
    right_verdict: str = "nhẹ RAM hơn",
) -> str:
    """The sparse-index explainer, drawn as a chest of drawers on a bench.

    The chest is the same in both rows — the data never changes. The dense
    index puts a card on every thin drawer (six entries); the ClickHouse sparse
    index puts one card on each of two deep drawers (two entries), and each deep
    drawer shows the rows it swallows. Two colours, no words inside the drawing;
    the label, the ratio and the RAM verdict sit in the margins.
    """
    parts = _plate_header(title, kicker=kicker, subtitle=subtitle)

    rows = (
        {
            "label": left_label,
            "name": left_name,
            "verdict": left_verdict,
            "drawers": 6,
            "hot": False,
            "cards": 3,
            "color": _MUTED,
        },
        {
            "label": right_label,
            "name": right_name,
            "verdict": right_verdict,
            "drawers": 2,
            "hot": True,
            "cards": 1,
            "color": _ACCENT,
        },
    )

    for row, top in zip(rows, (296.0, 762.0), strict=True):
        rect_h = 450.0
        scene = iso_module.fit(_SBOUNDS, left=190, top=top, width=700, height=rect_h)
        center = top + rect_h / 2
        parts.append(_index_scene(scene, drawers=row["drawers"], hot=row["hot"]))
        parts.append(_text(126, center - 8, 27, row["label"], bold=True))
        parts.append(_text(126, center + 24, 19, row["name"], fill=_MUTED, spacing=1))
        parts.append(_cards(936, center - 26, 20, row["cards"], row["color"]))
        parts.append(_text(936, center + 26, 25, row["verdict"], fill=row["color"], bold=True))

    parts.append("</svg>")
    return "".join(parts)


# --- the write-concern scene -------------------------------------------------
# One bench per policy: a console on the left, three cabinets along it, a cable
# running console -> cabinets. A cabinet shows the record as a lit card, or an
# empty bay; a hazard hangs over the first cabinet. Every word lives outside the
# drawing, in the margins — the scene itself is only objects.

_UNIT_W, _UNIT_D, _UNIT_H = 100.0, 84.0, 96.0
_UNIT_X = (56.0, 206.0, 356.0)
_BENCH = (-172.0, -20.0, 638.0, 112.0)
_TERM = (-150.0, 6.0, 92.0, 66.0, 60.0)
_BOUNDS = (-172.0, -20.0, -18.0, 466.0, 92.0, 96.0)


def _bolt(cx: float, cy: float, s: float, color: str) -> str:
    pts = [(0.30, -1.0), (-0.52, 0.06), (-0.06, 0.06), (-0.34, 1.0), (0.52, -0.08), (0.04, -0.08)]
    d = " ".join(f"{cx + px * s:.1f},{cy + py * s:.1f}" for px, py in pts)
    return (
        f"<polygon points='{d}' fill='{color}' stroke='{_PAPER}' "
        f"stroke-width='{max(2.0, s * 0.14):.1f}' stroke-linejoin='round'/>"
    )


def _shield(cx: float, cy: float, s: float, color: str) -> str:
    pts = [(0.0, -1.0), (0.92, -0.58), (0.92, 0.26), (0.0, 1.0), (-0.92, 0.26), (-0.92, -0.58)]
    d = " ".join(f"{cx + px * s:.1f},{cy + py * s:.1f}" for px, py in pts)
    tick = " ".join(
        f"{cx + px * s * 0.6:.1f},{cy + py * s * 0.6:.1f}"
        for px, py in [(-0.5, 0.04), (-0.12, 0.4), (0.56, -0.36)]
    )
    return (
        f"<polygon points='{d}' fill='{color}'/>"
        f"<polyline points='{tick}' fill='none' stroke='{_PAPER}' "
        f"stroke-width='{max(2.0, s * 0.15):.1f}' stroke-linecap='round' stroke-linejoin='round'/>"
    )


def _flat_ring(
    iso_: iso_module.Iso,
    cx: float,
    cy: float,
    z: float,
    r: float,
    color: str,
    *,
    width: float = 3.0,
) -> str:
    n = 30
    pts = [
        iso_.p(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z)
        for i in range(n)
    ]
    d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    return f"<polygon points='{d}' fill='none' stroke='{color}' stroke-width='{width:g}'/>"


def _flat_check(
    iso_: iso_module.Iso,
    cx: float,
    cy: float,
    z: float,
    s: float,
    color: str,
    *,
    width: float = 5.0,
) -> str:
    pts = [(-0.5, 0.05), (-0.14, 0.4), (0.55, -0.42)]
    d = " ".join(
        f"{px:.1f},{py:.1f}" for px, py in (iso_.p(cx + dx * s, cy + dy * s, z) for dx, dy in pts)
    )
    return (
        f"<polyline points='{d}' fill='none' stroke='{color}' stroke-width='{width:g}' "
        "stroke-linecap='round' stroke-linejoin='round'/>"
    )


def _flat_clock(iso_: iso_module.Iso, cx: float, cy: float, z: float, r: float, color: str) -> str:
    hand = " ".join(
        f"{px:.1f},{py:.1f}" for px, py in (iso_.p(cx, cy, z), iso_.p(cx, cy - r * 0.62, z))
    )
    hand2 = " ".join(
        f"{px:.1f},{py:.1f}" for px, py in (iso_.p(cx, cy, z), iso_.p(cx + r * 0.5, cy, z))
    )
    return (
        _flat_ring(iso_, cx, cy, z, r, color, width=3.4)
        + f"<polyline points='{hand}' fill='none' stroke='{color}' stroke-width='3.4' stroke-linecap='round'/>"
        + f"<polyline points='{hand2}' fill='none' stroke='{color}' stroke-width='3.4' stroke-linecap='round'/>"
    )


def _console(iso_: iso_module.Iso, *, ack: str) -> str:
    """The client: a dark little counter with a screen and the ack on its top."""
    x, y, w, d, h = _TERM
    Y = y + d + 0.4
    parts = [iso_.shadow(x, y, w, d, spread=0.16), iso_.box(x, y, 0, w, d, h, iso_module.INK)]
    parts.append(
        iso_.quad(
            [(x + 16, Y, 10), (x + w - 16, Y, 10), (x + w - 16, Y, h - 10), (x + 16, Y, h - 10)],
            "#2f3833",
        )
    )
    parts.append(
        iso_.quad(
            [
                (x + 12, y + 10, h + 0.5),
                (x + w - 12, y + 10, h + 0.5),
                (x + w - 12, y + d - 10, h + 0.5),
                (x + 12, y + d - 10, h + 0.5),
            ],
            "#ffffff",
            edge="#cdc3b0",
            width=1.5,
        )
    )
    cx, cy = x + w / 2, y + d / 2
    if ack == "fast":
        parts.append(_flat_check(iso_, cx, cy, h + 1.0, 20, iso_module.TEAL[1]))
    else:
        parts.append(_flat_clock(iso_, cx, cy, h + 1.0, 14, iso_module.TEAL[1]))
    return "".join(parts)


def _cabinet(iso_: iso_module.Iso, x: float, y: float, *, holds: bool) -> str:
    """A node: a cabinet whose bay holds the record — or stands empty.

    The bay opens on the front-left wall, the one face a neighbour never hides,
    so no cabinet in the row is covered up. One that holds the record is lit
    teal with a bright card inside; an empty one is pale with a dashed bay, so
    the count reads at a glance and the scene stays two colours.
    """
    w, d, h = _UNIT_W, _UNIT_D, _UNIT_H
    Y = y + d + 0.4
    mat = iso_module.TEAL if holds else iso_module.SHELL
    parts = [iso_.shadow(x, y, w, d, spread=0.16), iso_.box(x, y, 0, w, d, h, mat)]
    bay = [(x + 18, Y, 24), (x + w - 18, Y, 24), (x + w - 18, Y, h - 16), (x + 18, Y, h - 16)]
    parts.append(iso_.quad(bay, "#0a3b37" if holds else "#232a2d"))
    inner = [(x + 25, Y, 32), (x + w - 25, Y, 32), (x + w - 25, Y, h - 24), (x + 25, Y, h - 24)]
    if holds:
        parts.append(iso_.quad(inner, "#ffffff", edge=iso_module.TEAL[0], width=1.6))
        parts.append(iso_.line((x + 33, Y, 50), (x + w - 33, Y, 50), iso_module.TEAL[1], width=3.0))
        parts.append(iso_.line((x + 33, Y, 66), (x + w - 52, Y, 66), "#c9c1ae", width=2.6))
    else:
        parts.append(iso_.quad(inner, "none", edge="#8b968e", width=2.0, dash="8 7"))
    led = "#ffffff" if holds else "#b9b2a2"
    parts.append(
        iso_.quad(
            [
                (x + 12, Y - 26, h + 0.5),
                (x + 12, Y - 10, h + 0.5),
                (x + 26, Y - 10, h + 0.5),
                (x + 26, Y - 26, h + 0.5),
            ],
            led,
        )
    )
    vent = iso_module.TEAL[0] if holds else "#d3c9b5"
    parts.append(
        iso_.line((x + w + 0.4, y + 14, 16), (x + w + 0.4, y + d - 14, 16), vent, width=2.4)
    )
    return "".join(parts)


def _cluster(iso_: iso_module.Iso, *, holds: tuple[bool, bool, bool], ack: str) -> str:
    """One policy's bench, painted back to front."""
    bx, by, bw, bd = _BENCH
    parts = [
        iso_.shadow(bx, by, bw, bd, spread=0.16),
        iso_.box(bx, by, -18, bw, bd, 18, iso_module.WOOD),
    ]

    route_y, cz = by + bd - 2, 5.0
    centers = [x + _UNIT_W / 2 for x in _UNIT_X]
    tx = _TERM[0] + _TERM[2] / 2
    parts.append(
        iso_.line((tx, route_y, cz), (centers[0], route_y, cz), iso_module.TEAL[2], width=3.0)
    )
    for i in range(2):
        live = holds[i + 1]
        parts.append(
            iso_.line(
                (centers[i], route_y, cz),
                (centers[i + 1], route_y, cz),
                iso_module.TEAL[2] if live else "#b9b2a2",
                width=3.0,
                dash=None if live else "7 8",
            )
        )

    parts.append(_console(iso_, ack=ack))
    for x, state in zip(_UNIT_X, holds, strict=True):
        parts.append(_cabinet(iso_, x, 0.0, holds=state))
    hx, hy = iso_.p(_UNIT_X[0] + _UNIT_W / 2, 20.0, _UNIT_H + 26.0)
    parts.append(_bolt(hx, hy, 36 * iso_.scale, iso_module.RUST[1]))
    return "".join(parts)


def render_write_concern(
    *,
    title: str = "WRITE CONCERN",
    kicker: str = "MONGODB REPLICA SET",
    subtitle: str = "Chờ bao nhiêu node mới báo OK?",
    left_label: str = "w:1",
    left_name: str = "ACK NGAY",
    left_verdict: str = "mất nếu sập",
    right_label: str = "w:majority",
    right_name: str = "CHỜ ĐA SỐ",
    right_verdict: str = "còn khi sập",
) -> str:
    """The ``writeConcern`` explainer, drawn as two little benches of cabinets.

    Each row is one policy: a console (the client) cables into three cabinets
    (the replica set), and a cabinet shows the record as a lit card or shows an
    empty bay. Left (``w:1``) one cabinet holds it and a hazard hangs over that
    very one, so a crash loses it; right (``w:majority``) two hold it, so the
    hazard claims only a copy. Words stay out of the drawing — the label, the
    ack name and the verdict sit in the margins.
    """
    parts = _plate_header(title, kicker=kicker, subtitle=subtitle)

    rows = (
        {
            "label": left_label,
            "name": left_name,
            "holds": (True, False, False),
            "ack": "fast",
            "icon": "bolt",
            "verdict": left_verdict,
            "color": iso_module.RUST[1],
        },
        {
            "label": right_label,
            "name": right_name,
            "holds": (True, True, False),
            "ack": "wait",
            "icon": "shield",
            "verdict": right_verdict,
            "color": iso_module.TEAL[1],
        },
    )

    for row, top in zip(rows, (296.0, 762.0), strict=True):
        rect_h = 450.0
        scene = iso_module.fit(_BOUNDS, left=190, top=top, width=700, height=rect_h)
        center = top + rect_h / 2
        parts.append(_cluster(scene, holds=row["holds"], ack=row["ack"]))
        # left margin: which policy this bench is
        parts.append(_text(126, center - 8, 27, row["label"], bold=True))
        parts.append(_text(126, center + 24, 19, row["name"], fill=_MUTED, spacing=1))
        # right margin: what the policy costs when a node dies
        if row["icon"] == "bolt":
            parts.append(_bolt(936, center - 26, 21, iso_module.RUST[1]))
        else:
            parts.append(_shield(936, center - 26, 20, iso_module.TEAL[1]))
        parts.append(_text(936, center + 26, 25, row["verdict"], fill=row["color"], bold=True))

    parts.append("</svg>")
    return "".join(parts)


def diagram_kind(draft) -> str:
    """Which plate a draft should get, from the system it is about ('' = none).

    The matcher keys on the draft's own words (topic, title, excerpt), not on a
    list of ids, so a new system is a new branch here plus a renderer. An
    unrecognised draft renders nothing rather than borrowing another system's
    plate — a wrong figure is worse than no figure.
    """
    blob = " ".join(
        str(getattr(draft, field, "") or "") for field in ("topic", "title", "excerpt")
    ).lower()
    if "mongo" in blob:
        return "write_concern"
    if "clickhouse" in blob or "sparse" in blob:
        return "sparse_index"
    return ""


def render_for_draft(draft) -> str:
    """The SVG for a draft, or '' when no plate matches it.

    A draft must be a diagram draft (``image_style == "diagram"``) *and* name a
    system a renderer knows; anything else keeps its source image. A new
    template is a new renderer plus a branch in ``diagram_kind``.
    """
    if draft is None or getattr(draft, "image_style", "") != "diagram":
        return ""
    kind = diagram_kind(draft)
    if kind == "write_concern":
        return render_write_concern()
    if kind == "sparse_index":
        return render_sparse_index()
    return ""


__all__ = [
    "HEIGHT",
    "WIDTH",
    "diagram_kind",
    "render_for_draft",
    "render_sparse_index",
    "render_write_concern",
]
