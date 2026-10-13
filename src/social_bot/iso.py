"""A tiny isometric kit (pure logic, stdlib only).

The plates draw *objects*, not boxes-and-arrows: a scene is built from solid
cuboids projected isometrically, every face filled with its own tone and
painted back to front, so nearer parts hide farther ones. Three tones per
material (top, right, left) plus a soft ground shadow give the volume; nothing
here is a wireframe and nothing is see-through.

World axes: x runs to the lower-right of the page, y to the lower-left, z
straight up — so ``x + y + z`` grows toward the viewer. A scene is therefore
painted in ascending depth, and ``fit`` centres a known world box in a target
rectangle at whatever scale it takes.
"""

from __future__ import annotations

import math

COS30 = math.cos(math.radians(30.0))

# Materials: (top, right, left) face tones plus the edge ink they are drawn
# with. Warm paper under a single petrol-teal light, like the rest of the brand.
CREAM = ("#fdfbf6", "#e9e2d3", "#d7ceb9", "#c3b9a3")
SHELL = ("#ffffff", "#f0eade", "#e1d8c7", "#cdc3b0")
TEAL = ("#3ba197", "#0e6b64", "#094b46", "#063a36")
INK = ("#3b423e", "#181c1a", "#0b0e0d", "#000000")
WOOD = ("#e8dabd", "#ccb794", "#b29a74", "#9c8763")
RUST = ("#d67a5c", "#b0503a", "#8a3b27", "#7a3322")
STONE = ("#ece8df", "#d5cfc0", "#beb7a5", "#a8a18f")
GOLD = ("#e6c98a", "#c9a558", "#a5833c", "#8f6f2f")


class Iso:
    """Projects world (x, y, z) onto the page and draws solid cuboids."""

    def __init__(self, ox: float, oy: float, scale: float = 1.0) -> None:
        self.ox, self.oy, self.scale = ox, oy, scale

    def p(self, x: float, y: float, z: float = 0.0) -> tuple[float, float]:
        s = self.scale
        return (self.ox + (x - y) * COS30 * s, self.oy + (x + y) * 0.5 * s - z * s)

    @staticmethod
    def depth(x: float, y: float, z: float = 0.0) -> float:
        return x + y + z

    def poly(
        self,
        pts: list[tuple[float, float]],
        fill: str,
        *,
        edge: str | None = None,
        width: float = 1.5,
        dash: str | None = None,
        opacity: float = 1.0,
    ) -> str:
        d = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        e = f" stroke='{edge}' stroke-width='{width:g}' stroke-linejoin='round'" if edge else ""
        da = f" stroke-dasharray='{dash}'" if dash else ""
        o = f" opacity='{opacity:.2f}'" if opacity < 1 else ""
        return f"<polygon points='{d}' fill='{fill}'{e}{da}{o}/>"

    def quad(self, pts: list[tuple[float, float, float]], fill: str, **kw) -> str:
        return self.poly([self.p(*pt) for pt in pts], fill, **kw)

    def box(
        self,
        x: float,
        y: float,
        z: float,
        w: float,
        d: float,
        h: float,
        mat: tuple[str, str, str, str],
        *,
        edge: bool = True,
        width: float = 1.5,
    ) -> str:
        """A solid cuboid: left and right walls, then the lit top."""
        X, Y, Z = x + w, y + d, z + h
        e = mat[3] if edge else None
        left = [(x, Y, z), (X, Y, z), (X, Y, Z), (x, Y, Z)]
        right = [(X, y, z), (X, Y, z), (X, Y, Z), (X, y, Z)]
        top = [(x, y, Z), (X, y, Z), (X, Y, Z), (x, Y, Z)]
        return (
            self.quad(left, mat[2], edge=e, width=width)
            + self.quad(right, mat[1], edge=e, width=width)
            + self.quad(top, mat[0], edge=e, width=width)
        )

    def shadow(self, x: float, y: float, w: float, d: float, *, spread: float = 0.5) -> str:
        """A soft halo on the ground under a solid (drawn before the solid)."""
        cx, cy = self.p(x + w / 2, y + d / 2, 0.0)
        rx = (w + d) * COS30 * self.scale * spread
        ry = (w + d) * 0.5 * self.scale * spread
        return (
            f"<ellipse cx='{cx:.1f}' cy='{cy:.1f}' rx='{rx:.1f}' ry='{ry:.1f}' "
            f"fill='#171a19' opacity='0.15' filter='url(#soft)'/>"
        )

    def line(
        self,
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        color: str,
        *,
        width: float = 3.0,
        dash: str | None = None,
        cap: str = "round",
    ) -> str:
        x1, y1 = self.p(*a)
        x2, y2 = self.p(*b)
        da = f" stroke-dasharray='{dash}'" if dash else ""
        return (
            f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
            f"stroke='{color}' stroke-width='{width:g}' stroke-linecap='{cap}'{da}/>"
        )


def fit(
    bounds: tuple[float, float, float, float, float, float],
    *,
    left: float,
    top: float,
    width: float,
    height: float,
) -> Iso:
    """An ``Iso`` that centres world ``bounds`` (minx,miny,minz,maxx,maxy,maxz)."""
    minx, miny, minz, maxx, maxy, maxz = bounds
    sx_min = (minx - maxy) * COS30
    sx_max = (maxx - miny) * COS30
    sy_min = (minx + miny) * 0.5 - maxz
    sy_max = (maxx + maxy) * 0.5 - minz
    span_x = max(sx_max - sx_min, 1e-6)
    span_y = max(sy_max - sy_min, 1e-6)
    scale = min(width / span_x, height / span_y)
    cx = (sx_min + sx_max) / 2
    cy = (sy_min + sy_max) / 2
    return Iso(left + width / 2 - cx * scale, top + height / 2 - cy * scale, scale)


__all__ = [
    "COS30",
    "CREAM",
    "GOLD",
    "INK",
    "Iso",
    "RUST",
    "SHELL",
    "STONE",
    "TEAL",
    "WOOD",
    "fit",
]
