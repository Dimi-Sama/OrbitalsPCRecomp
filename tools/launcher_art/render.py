# Orbitals PC Recomp, a work based on SwitchRecomp by MZ Labs. GNU AGPL v3.0 with the additional terms of NOTICE.txt (LICENSE.txt).
"""Draw the launcher's pictures again (launcher/assets): its icon, logotype and Steam images. Flat colours, the title screen's own.

  python -B tools/launcher_art/render.py --font DelaGothicOne-Regular.ttf [--out launcher/assets]

Needs Pillow, here only: the launcher reads the files. The typeface is Dela Gothic One (SIL Open Font License,
https://github.com/syakuzen/DelaGothic), not included: its letters are drawn into the pictures."""
import argparse
import io
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK, NIGHT, SHADOW = "#f4f1ff", "#090a1c", "#0b1240"
BLUE, BLUE_D, PINK, PINK_D, CYAN, GOLD = "#2e5cff", "#1a2f8f", "#ff4f8b", "#8f1f4d", "#46e6ff", "#ffc94a"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SCALES = {75: 0.75, 100: 1.0, 125: 1.25, 150: 1.5, 200: 2.0}   # the sizes the logotype is drawn at: screen scales, and a narrow window
LEAN = 0.18


def lean(mask, amount=LEAN):
    """Italic: the top to the right."""
    h = mask.height
    return mask.transform((mask.width + int(h * amount), h), Image.AFFINE, (1, amount, -h * amount, 0, 1, 0), Image.BICUBIC)


def lettering(text, font, size, track=0):
    """A leaning mask of a word, cut to its ink."""
    face = ImageFont.truetype(str(font), size)
    widths = [face.getlength(c) for c in text]
    mask = Image.new("L", (int(sum(widths) + track * len(text)) + size, int(size * 1.6)), 0)
    draw, x = ImageDraw.Draw(mask), size * 0.3
    for c, w in zip(text, widths):
        draw.text((x, 0), c, font=face, fill=255)
        x += w + track
    mask = lean(mask)
    return mask.crop(mask.getbbox())


def put(picture, colour, mask, at):
    layer = Image.new("RGBA", picture.size, (0, 0, 0, 0))
    layer.paste(colour, at, mask)
    picture.alpha_composite(layer)


def logotype(font, scale, k=6):
    """ORBITALS with its hard shadow, the kana above it."""
    u = scale * k
    word = lettering("ORBITALS", font, int(72 * u), track=-2.2 * u)
    kana = lettering("オービタルズ", font, int(21 * u), track=3.2 * u)
    off = int(5 * u)
    w, h = word.width + off + int(4 * u), word.height + kana.height + int(16 * u) + off + int(4 * u)
    picture = Image.new("RGBA", (w + (-w % k), h + (-h % k)), (0, 0, 0, 0))
    put(picture, CYAN, kana, (int(16 * u), 0))
    top = kana.height + int(16 * u)
    for step in range(off + 1):   # a solid shadow, not a copy set aside
        put(picture, SHADOW, word, (step, top + step))
    put(picture, INK, word, (0, top))
    return picture.resize((picture.width // k, picture.height // k), Image.LANCZOS)


def icon(font, size):
    """The tile: the title screen's two panels and its diagonal, the O as a world, a ring around it."""
    k = max(4, 1024 // size)
    n = size * k
    small = size < 32   # an O and its light alone
    tile = Image.new("RGBA", (n, n), PINK_D)
    draw = ImageDraw.Draw(tile)
    def at(y, shift=0.0):
        return (0.66 - 0.32 * y / n) * n + shift * n
    draw.polygon([(0, 0), (at(0), 0), (at(n), n), (0, n)], fill=BLUE)
    if not small:
        draw.polygon([(at(0, -0.07), 0), (at(0), 0), (at(n), n), (at(n, -0.07), n)], fill=BLUE_D)
    line = 0.030 if not small else 0.05
    draw.polygon([(at(0), 0), (at(0, line), 0), (at(n, line), n), (at(n), n)], fill=INK)
    draw.polygon([(at(0, line), 0), (at(0, line * 2.3), 0), (at(n, line * 2.3), n), (at(n, line), n)], fill=NIGHT)
    if not small:
        draw.polygon([(at(0, line * 2.3), 0), (at(0, line * 2.9), 0), (at(n, line * 2.9), n), (at(n, line * 2.3), n)], fill=GOLD)

    # the O: a heavy leaning ring
    letter = lettering("O", font, int(n * (0.92 if small else 0.60)))
    off = int(n * (0.045 if not small else 0.07))
    ox, oy = (n - letter.width - off) // 2, (n - letter.height - off) // 2 + int(n * (0.03 if small else 0))

    def orbit(front):
        """Half of the ring, with its outline."""
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rx, ry, tilt = 0.425 * n, 0.135 * n, math.radians(-24)
        width, outline = n * (0.056 if size >= 64 else 0.070), n * (0.021 if size >= 64 else 0.028)
        for w, colour, past in ((width + 2 * outline, NIGHT, -7 if front else 0), (width, GOLD, 5)):   # (its halves join without a seam)
            points = []
            for i in range(-past, 181 + past):
                a = math.radians(i if front else 180 + i)
                x, y = rx * math.cos(a), ry * math.sin(a)
                points.append((n / 2 + x * math.cos(tilt) - y * math.sin(tilt), n / 2 + x * math.sin(tilt) + y * math.cos(tilt)))
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                d.line([(x0, y0), (x1, y1)], fill=colour, width=int(w))
            for x, y in points:
                d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=colour)
        return layer

    if not small:
        tile.alpha_composite(orbit(False))
    for step in range(0, off + 1, max(1, k // 2)):
        put(tile, SHADOW, letter, (ox + step, oy + step))
    put(tile, INK, letter, (ox, oy))
    d = ImageDraw.Draw(tile)
    if small:
        spots = ((0.80, 0.21, (0.185, 0.135) if size >= 20 else (0.20, 0.15)),)
    else:
        tile.alpha_composite(orbit(True))
        a, rx, ry, tilt = math.radians(8), 0.425 * n, 0.135 * n, math.radians(-24)
        spots = ((0.5 + (rx * math.cos(a) * math.cos(tilt) - ry * math.sin(a) * math.sin(tilt)) / n,
                  0.5 + (rx * math.cos(a) * math.sin(tilt) + ry * math.sin(a) * math.cos(tilt)) / n, (0.088, 0.067)),)
    for x, y, (outer, inner) in spots:   # the light on the ring
        for r, colour in ((outer, NIGHT), (inner, GOLD if small else CYAN)):
            d.ellipse([(x - r) * n, (y - r) * n, (x + r) * n, (y + r) * n], fill=colour)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * (0.20 if size >= 24 else 0.16)), fill=255)
    out = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    out.paste(tile, (0, 0), mask)
    return out.resize((size, size), Image.LANCZOS)


def title_card(font, w, h, scale=None, at=(0.5, 0.40), k=2, split=(0.74, 0.46)):
    """The title screen as a picture: rays, screentone, the diagonal and, with a scale, the logotype."""
    n, m = w * k, h * k
    card = Image.new("RGBA", (n, m), BLUE)
    draw = ImageDraw.Draw(card)
    at_y = lambda y, shift=0.0: n * (split[0] + (split[1] - split[0]) * y / m) + shift * k
    cx, cy, far = n * (at[0] if scale else 0.28), m * at[1], math.hypot(n, m)
    for i in range(16):
        a, b = (i + 0.12) / 16 * math.tau, (i + 0.50) / 16 * math.tau
        draw.polygon([(cx, cy), (cx + math.cos(a) * far, cy + math.sin(a) * far), (cx + math.cos(b) * far, cy + math.sin(b) * far)], fill="#3a65ff")
    u = min(w, h) / 430   # the size of what is drawn
    pitch, reach, edge = 12 * u * k, 120 * u * k, 28 * u * k

    def dots(size_at, colour, step):
        row, y = 0, 0.0
        while y < m + step:
            x = step / 2 * (row % 2)
            while x < n + step:
                r = size_at(x, y) * step / 2
                if r > 0.6:
                    draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)
                x += step
            y += step / 2
            row += 1

    dots(lambda x, y: 0 if at_y(y) - edge - x < -step_of(pitch) else max(0.0, 1 - (at_y(y) - edge - x) / reach) * 0.96, BLUE_D, pitch)
    for start, end, colour in ((-edge, 0, BLUE_D), (0, 4 * u * k, INK), (4 * u * k, 14 * u * k, NIGHT), (14 * u * k, 17 * u * k, GOLD)):
        draw.polygon([(at_y(0) + start, 0), (at_y(0) + end, 0), (at_y(m) + end, m), (at_y(m) + start, m)], fill=colour)
    last = 17 * u * k
    draw.polygon([(at_y(0) + last, 0), (n, 0), (n, m), (at_y(m) + last, m)], fill=PINK_D)
    dots(lambda x, y: max(0.0, (x / n - 0.70) + (y / m - 0.66) * 1.5) * 0.8 if x > at_y(y) + last + pitch / 2 else 0, "#7b1841", pitch * 1.1)
    for fx, fy, size in ((0.93, 0.12, 22), (0.86, 0.19, 9), (0.94, 0.86, 14), (0.10, 0.84, 18), (0.16, 0.90, 8)):
        x, y, r = fx * n, fy * m, size * u * k
        points = []
        for q in range(4):
            a0 = q * math.pi / 2 - math.pi / 2
            points += [(x + math.cos(a0) * r, y + math.sin(a0) * r), (x + math.cos(a0 + math.pi / 4) * r * 0.24, y + math.sin(a0 + math.pi / 4) * r * 0.24)]
        draw.polygon(points, fill="#fff6d8")
    if scale:
        word = logotype(font, scale * k, 3)
        card.alpha_composite(word, (int(n * at[0] - word.width / 2), int(m * at[1] - word.height / 2)))
    return card.resize((w, h), Image.LANCZOS).convert("RGB")


def step_of(pitch):
    return pitch * 0.6


def ico(path, font):
    """A Windows icon: each size drawn for itself, all as PNG."""
    pictures = []
    for size in ICON_SIZES:
        out = io.BytesIO()
        icon(font, size).save(out, format="PNG", optimize=True)
        pictures.append((size, out.getvalue()))
    offset = 6 + 16 * len(pictures)
    head = struct.pack("<HHH", 0, 1, len(pictures))
    for size, data in pictures:
        head += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.write_bytes(head + b"".join(data for _, data in pictures))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "launcher" / "assets")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    ico(args.out / "orbitals.ico", args.font)
    icon(args.font, 256).save(args.out / "orbitals-icon.png", optimize=True)
    for name, scale in SCALES.items():
        logotype(args.font, scale).save(args.out / f"logotype-{name}.png", optimize=True)
    steam = args.out / "steam"
    steam.mkdir(exist_ok=True)
    title_card(args.font, 600, 900, 1.06, (0.5, 0.36), split=(0.98, 0.34)).save(steam / "capsule.png", optimize=True)
    title_card(args.font, 920, 430, 1.10, (0.39, 0.46), split=(0.86, 0.64)).save(steam / "wide.png", optimize=True)
    title_card(args.font, 1920, 620, split=(0.64, 0.50)).save(steam / "hero.png", optimize=True)
    logotype(args.font, 2.0).save(steam / "logo.png", optimize=True)
    for path in sorted((*args.out.glob("*.*"), *steam.iterdir())):
        print(f"  {path.name}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
