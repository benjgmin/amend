"""The Amend mark: three lines of text with an amber bar beside the one that changed, the way amended FAA
publications mark revised text in the margin.

One geometry, drawn as SVG for the site and with Pillow for the favicons, the link cards and the iOS app icon.
`python -m amend.brand` rewrites the iOS app icons and docs/brand/ after a change here; the site's icons are
made on every build.
"""
import json
import os

INK = "#11151B"         # the tile
INK_LIFT = "#28303B"    # the tile on dark pages: a shade lighter so it doesn't sink into the background
AMBER = "#F5B040"       # the bar, the same amber the site uses for action items
HI = "#F3F4F6"          # the changed line
LO = "#5E6773"          # the lines that didn't change
TEXT, TEXT_DARK = "#0F1216", "#ECEEF1"    # the wordmark on light and dark pages
ICON_GRADIENT = ("#1B212A", "#0C0F13")    # app and touch icons, top to bottom
# on a 64-unit grid, all multiples of 4 so the mark lands on whole pixels at 16 and 32 px: x0, y0, x1, y1, colour
SHAPES = [(12, 24, 20, 40, AMBER), (24, 12, 52, 20, LO), (24, 28, 52, 36, HI), (24, 44, 40, 52, LO)]
RADIUS = 14             # tile corners on the same grid (favicon, site header, link cards)
ICON_SCALE = 0.9        # the lines inside an app or touch icon, which the OS rounds and which read bigger

FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
WORDMARK_FONT = os.path.join(FONTS, "Geist-SemiBold.ttf")


def svg(tile=INK, radius=RADIUS, tile_class="", size=None):
    """the mark as <svg>: inline in a page (tile_class lets its CSS colour the tile, which the site lifts in dark
    mode) or, with a size, as a file of its own."""
    head = f' width="{size}" height="{size}"' if size else ' aria-hidden="true"'
    cls = f' class="{tile_class}"' if tile_class else ""
    rects = "".join(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="4" fill="{c}"/>'
                    for x0, y0, x1, y1, c in SHAPES)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"{head}>'
            f'<rect{cls} width="64" height="64" rx="{radius}" fill="{tile}"/>{rects}</svg>')


def _rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def draw(size, tile=INK, radius=RADIUS, scale=1.0, gradient=None, colors=None):
    """the mark as a size x size RGBA Pillow image.

    radius=0 fills the square edge to edge (app and touch icons, which the OS rounds itself); scale shrinks
    the lines toward the centre; gradient=(top, bottom) shades the tile; colors swaps SHAPES colours
    (the tinted iOS icon is greyscale)."""
    from PIL import Image, ImageDraw
    ss = 4                                  # drawn 4x and box-filtered down: smooth edges, whole-pixel lines
    big = size * ss
    k = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=radius * k, fill=255)
    if gradient:
        top, bottom = _rgb(gradient[0]), _rgb(gradient[1])
        column = Image.new("RGBA", (1, big))
        for y in range(big):
            t = y / (big - 1)
            column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
        img.paste(column.resize((big, big)), (0, 0), mask)
    elif tile:
        img.paste(Image.new("RGBA", (big, big), _rgb(tile) + (255,)), (0, 0), mask)
    d = ImageDraw.Draw(img)
    for x0, y0, x1, y1, c in SHAPES:
        x0, y0, x1, y1 = (32 + (v - 32) * scale for v in (x0, y0, x1, y1))
        r = min(x1 - x0, y1 - y0) / 2 * k
        d.rounded_rectangle([x0 * k, y0 * k, x1 * k - 1, y1 * k - 1], radius=r,
                            fill=_rgb((colors or {}).get(c, c)))
    return img.resize((size, size), Image.BOX)


def app_icon(size=1024, variant="light"):
    """the iOS / touch icon: edge to edge, the OS rounds it. variant: light (the default icon), dark or tinted."""
    if variant == "tinted":   # iOS tints by brightness: the bar brightest, the changed line next
        return draw(size, tile="#000000", radius=0, scale=ICON_SCALE,
                    colors={AMBER: "#FFFFFF", HI: "#C4C4C4", LO: "#4D4D4D"}).convert("RGB")
    grad = ICON_GRADIENT if variant == "light" else ("#161B22", "#07090C")
    return draw(size, radius=0, scale=ICON_SCALE, gradient=grad).convert("RGB")


def write_site_icons(site):
    """favicon.ico and site.webmanifest at the site root, the rest in assets/. The SVG needs no Pillow; the
    PNGs and the .ico are skipped without it (browsers then use the SVG)."""
    assets = os.path.join(site, "assets")
    os.makedirs(assets, exist_ok=True)
    with open(os.path.join(assets, "icon.svg"), "w") as f:
        f.write(svg(size=64))
    manifest = {"name": "Amend", "short_name": "Amend",
                "description": "What changed at your airport, every FAA cycle.",
                "start_url": "/", "scope": "/", "display": "minimal-ui",
                "background_color": "#F6F7F9", "theme_color": "#F6F7F9",
                "icons": [{"src": "/assets/icon.svg", "sizes": "any", "type": "image/svg+xml"},
                          {"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                          {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png"},
                          {"src": "/assets/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                           "purpose": "maskable"}]}
    with open(os.path.join(site, "site.webmanifest"), "w") as f:
        json.dump(manifest, f, indent=1)
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    small = [draw(s) for s in (16, 32, 48)]
    small[-1].save(os.path.join(site, "favicon.ico"), format="ICO", sizes=[(16, 16), (32, 32), (48, 48)],
                   append_images=small[:-1])
    app_icon(180).save(os.path.join(assets, "apple-touch-icon.png"), optimize=True)
    for s in (192, 512):
        draw(s).save(os.path.join(assets, f"icon-{s}.png"), optimize=True)
    # maskable: Android crops to a circle or squircle, so the lines sit well inside the safe zone
    app_icon(512).save(os.path.join(assets, "icon-maskable-512.png"), optimize=True)
    return True


def wordmark_path(font=WORDMARK_FONT, tracking=-20):
    """'amend' in Geist SemiBold as SVG path data (y down, baseline at 0), and its advance width, in font
    units. Outlines, so the logo looks the same where Geist isn't installed (GitHub, image viewers)."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont
    f = TTFont(font)
    glyphs, cmap = f.getGlyphSet(), f.getBestCmap()
    x, parts = 0, []
    for ch in "amend":
        g = glyphs[cmap[ord(ch)]]
        pen = SVGPathPen(glyphs)
        g.draw(TransformPen(pen, (1, 0, 0, -1, x, 0)))
        parts.append(pen.getCommands())
        x += g.width + tracking
    return " ".join(parts), x - tracking, f["head"].unitsPerEm


def lockup_svg(dark=False):
    """mark + wordmark, laid out like the site header (22 px mark, 17 px type, 8 px gap)."""
    path, width, upm = wordmark_path()
    fs = 64 * 17 / 22                      # type size on the mark's 64-unit grid
    s = fs / upm
    gap = 64 * 8 / 22
    from fontTools.ttLib import TTFont
    f = TTFont(WORDMARK_FONT)
    glyphs, cmap = f.getGlyphSet(), f.getBestCmap()
    from fontTools.pens.boundsPen import BoundsPen
    top = 0
    for ch in "amend":                     # tallest ink above the baseline (the d), to centre the word
        bp = BoundsPen(glyphs)
        glyphs[cmap[ord(ch)]].draw(bp)
        top = max(top, bp.bounds[3])
    baseline = 32 + top * s / 2
    w = 64 + gap + width * s
    tile, text = (INK_LIFT, TEXT_DARK) if dark else (INK, TEXT)
    mark = svg(tile=tile, size=64).split(">", 1)[1].rsplit("</svg>", 1)[0]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.1f} 64" width="{w * 56 / 64:.0f}" '
            f'height="56" role="img" aria-label="amend">{mark}'
            f'<path transform="translate({64 + gap:.2f} {baseline:.2f}) scale({s:.5f})" fill="{text}" '
            f'd="{path}"/></svg>')


def write_ios(appiconset, logoset):
    """the app icon (default, dark, tinted) and the in-app logo (vector, with a dark variant)."""
    names = {"light": "AppIcon.png", "dark": "AppIcon-dark.png", "tinted": "AppIcon-tinted.png"}
    for old in os.listdir(appiconset):
        if old.endswith(".png") and old not in names.values():
            os.remove(os.path.join(appiconset, old))
    images = []
    for variant, name in names.items():
        app_icon(1024, variant).save(os.path.join(appiconset, name), optimize=True)
        img = {"filename": name, "idiom": "universal", "platform": "ios", "size": "1024x1024"}
        if variant != "light":
            img = {"appearances": [{"appearance": "luminosity", "value": variant}], **img}
        images.append(img)
    with open(os.path.join(appiconset, "Contents.json"), "w") as f:
        json.dump({"images": images, "info": {"author": "xcode", "version": 1}}, f, indent=2)
        f.write("\n")
    os.makedirs(logoset, exist_ok=True)
    with open(os.path.join(logoset, "Logo.svg"), "w") as f:
        f.write(svg(size=64))
    with open(os.path.join(logoset, "Logo-dark.svg"), "w") as f:
        f.write(svg(tile=INK_LIFT, size=64))
    with open(os.path.join(logoset, "Contents.json"), "w") as f:
        json.dump({"images": [{"filename": "Logo.svg", "idiom": "universal"},
                              {"appearances": [{"appearance": "luminosity", "value": "dark"}],
                               "filename": "Logo-dark.svg", "idiom": "universal"}],
                   "info": {"author": "xcode", "version": 1},
                   "properties": {"preserves-vector-representation": True}}, f, indent=2)
        f.write("\n")


def write_docs(folder):
    """docs/brand/: the mark, the lockups the README shows, and a 1024 px icon for anywhere else."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "mark.svg"), "w") as f:
        f.write(svg(size=64))
    for dark in (False, True):
        with open(os.path.join(folder, f"lockup-{'dark' if dark else 'light'}.svg"), "w") as f:
            f.write(lockup_svg(dark))
    app_icon(1024).save(os.path.join(folder, "app-icon.png"), optimize=True)


if __name__ == "__main__":   # python -m amend.brand, from the repo root (needs Pillow and fontTools)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(root, "ios", "Amend", "Assets.xcassets")
    write_ios(os.path.join(assets, "AppIcon.appiconset"), os.path.join(assets, "Logo.imageset"))
    write_docs(os.path.join(root, "docs", "brand"))
    print("wrote ios/Amend/Assets.xcassets (AppIcon, Logo) and docs/brand/")
