"""The Amend mark: an edit. The old a struck through in magenta with the new a beside it, the way a correction
reads on paper and the way Amend shows every change: the old value, then the new one. Ink on white, with the
magenta the site uses for changes that need action.

One geometry, drawn as SVG for the site and with Pillow for the favicons, the link cards and the iOS app icon.
`python -m amend.brand` rewrites the iOS app icons and docs/brand/ after a change here; the site's icons are
made on every build.
"""
import json
import os

# the tile, its hairline edge, the old a, the strike and the new a, on light and dark backgrounds
LIGHT = {"tile": "#FFFFFF", "line": "#C3CCD7", "old": "#AAB5C3", "strike": "#A3186E", "new": "#0D1B2A"}
DARK = {"tile": "#0E1926", "line": "#2E4460", "old": "#4F627B", "strike": "#E26BB2", "new": "#E6EDF5"}
TEXT, TEXT_DARK = LIGHT["new"], DARK["new"]     # the wordmark on light and dark pages
ICON_GRADIENT = ("#FFFFFF", "#EEF2F6")          # the app and touch icons, top to bottom
ICON_GRADIENT_DARK = ("#132235", "#0A131E")
RADIUS = 14             # the tile's corners on the 64-unit grid (favicon, site header, link cards)
FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
MARK_FONT = os.path.join(FONTS, "IBMPlexSans-SemiBold.ttf")    # both a's, and the wordmark
WORDMARK_FONT = MARK_FONT
# the a in IBM Plex Sans SemiBold, in font units with y up. It's what _a_path() reads from the font (a test checks
# it still is), kept here so the site's SVGs need no font tools.
A_PATH = ("M529 0H458Q429 0 406.5 13.5Q384 27 371.5 53.0Q359 79 359 114V125L391 90H355Q342 40 301.5 14.0Q261 -12 "
          "203 -12Q123 -12 80.0 30.5Q37 73 37 142Q37 196 63.5 231.0Q90 266 140.0 284.0Q190 302 260 302H349V340Q349 "
          "383 326.0 407.5Q303 432 252 432Q207 432 179.5 412.5Q152 393 133 366L57 434Q86 479 134.0 506.5Q182 534 261 "
          "534Q366 534 421.5 485.5Q477 437 477 348V102H529ZM349 225H267Q217 225 192.0 208.5Q167 192 167 161V144Q167 "
          "113 188.0 97.0Q209 81 246 81Q275 81 298.0 89.5Q321 98 335.0 115.0Q349 132 349 156Z")
# each a's pen position, baseline and scale (grid units per font unit). The new a stands 26 units tall; the old one
# is 78% of that and 4 units to its left, and the pair is centred on the tile.
OLD = (7.275, 44.708, 0.03798)
NEW = (29.563, 44.708, 0.04869)
STRIKE = (6, 32, 30, 36)    # x0, y0, x1, y1: across the old a's middle, one whole pixel thick at 16 px
ICON_SCALE = 0.86           # the pair inside an app or touch icon, which the OS rounds and which reads bigger
MASKABLE_SCALE = 0.72       # Android crops maskable icons to a circle: the pair stays inside it


def _a_path(font=MARK_FONT):
    """the a's outline as SVG path data in font units, read from the font (needs fontTools)."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.ttLib import TTFont
    glyphs = TTFont(font).getGlyphSet()
    pen = SVGPathPen(glyphs)
    glyphs["a"].draw(pen)
    return pen.getCommands()


def _inner(colors, classes=False):
    """the tile, the old a, the strike and the new a as SVG elements. classes names each part (mk, mo, ms, mn) so
    CSS can recolour it for dark mode."""
    cl = (lambda n: f' class="{n}"') if classes else (lambda n: "")
    a = lambda x, base, s, part: (f'<path{cl(part)} fill="{colors[dict(mo="old", mn="new")[part]]}" '
                                  f'transform="translate({x} {base}) scale({s} -{s})" d="{A_PATH}"/>')
    x0, y0, x1, y1 = STRIKE
    return (f'<rect{cl("mk")} x=".75" y=".75" width="62.5" height="62.5" rx="{RADIUS - .75}" fill="{colors["tile"]}" '
            f'stroke="{colors["line"]}" stroke-width="1.5"/>'
            + a(*OLD, "mo")
            + f'<rect{cl("ms")} x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="{(y1 - y0) / 2:g}" '
              f'fill="{colors["strike"]}"/>'
            + a(*NEW, "mn"))


def svg(colors=LIGHT, size=None, classes=False, adaptive=False):
    """the mark as <svg>: inline in a page (classes lets the page's CSS recolour it) or, with a size, as a file of
    its own. adaptive switches a file to the dark colours when the viewer's system is in dark mode."""
    head = f' width="{size}" height="{size}"' if size else ' aria-hidden="true"'
    style = ""
    if adaptive:
        style = ("<style>@media (prefers-color-scheme:dark){"
                 f".mk{{fill:{DARK['tile']};stroke:{DARK['line']}}}.mo{{fill:{DARK['old']}}}"
                 f".ms{{fill:{DARK['strike']}}}.mn{{fill:{DARK['new']}}}}}</style>")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"{head}>{style}'
            f'{_inner(colors, classes or adaptive)}</svg>')


def _rgb(hex_):
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def draw(size, colors=LIGHT, radius=RADIUS, scale=1.0, gradient=None, outline=True):
    """the mark as a size x size RGBA Pillow image.

    radius=0 fills the square edge to edge (app and touch icons, which the OS rounds itself) and outline=False
    leaves off the hairline; scale shrinks the pair toward the centre; gradient=(top, bottom) shades the tile."""
    from PIL import Image, ImageDraw, ImageFont
    ss = 4                                  # drawn 4x and box-filtered down: smooth curves, a crisp strike
    big = size * ss
    k = big / 64
    px = lambda v: (32 + (v - 32) * scale) * k     # grid units to pixels, pulled toward the centre by scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))

    def paint(fill, shape):
        mask = Image.new("L", (big, big), 0)
        shape(ImageDraw.Draw(mask))
        img.paste(Image.new("RGBA", (big, big), _rgb(fill) + (255,)), (0, 0), mask)

    tile = lambda d: d.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius * k, fill=255)
    if gradient:
        top, bottom = _rgb(gradient[0]), _rgb(gradient[1])
        column = Image.new("RGBA", (1, big))
        for y in range(big):
            t = y / (big - 1)
            column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
        mask = Image.new("L", (big, big), 0)
        tile(ImageDraw.Draw(mask))
        img.paste(column.resize((big, big)), (0, 0), mask)
    else:
        paint(colors["tile"], tile)
    if outline:
        paint(colors["line"], lambda d: d.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius * k,
                                                            outline=255, width=max(1, round(1.5 * k))))

    def letter(x, base, s):
        font = ImageFont.truetype(MARK_FONT, 1000 * s * scale * k)     # 1000 font units to the em
        return lambda d: d.text((px(x), px(base)), "a", font=font, fill=255, anchor="ls")

    x0, y0, x1, y1 = STRIKE
    paint(colors["old"], letter(*OLD))
    paint(colors["strike"], lambda d: d.rounded_rectangle([px(x0), px(y0), px(x1) - 1, px(y1) - 1],
                                                          radius=(y1 - y0) / 2 * scale * k, fill=255))
    paint(colors["new"], letter(*NEW))
    return img.resize((size, size), Image.BOX)


def app_icon(size=1024, variant="light", scale=ICON_SCALE):
    """the iOS / touch icon: edge to edge, the OS rounds it. variant: light (the default icon), dark or tinted."""
    if variant == "tinted":   # iOS tints by brightness: the new a brightest, then the strike, the old a faint
        grey = {"tile": "#000000", "old": "#4D4D4D", "strike": "#BDBDBD", "new": "#FFFFFF"}
        return draw(size, grey, radius=0, scale=scale, outline=False).convert("RGB")
    colors, gradient = (LIGHT, ICON_GRADIENT) if variant == "light" else (DARK, ICON_GRADIENT_DARK)
    return draw(size, colors, radius=0, scale=scale, gradient=gradient, outline=False).convert("RGB")


def write_site_icons(site):
    """favicon.ico and site.webmanifest at the site root, the rest in assets/. The SVG needs no Pillow; the
    PNGs and the .ico are skipped without it (browsers then use the SVG)."""
    assets = os.path.join(site, "assets")
    os.makedirs(assets, exist_ok=True)
    with open(os.path.join(assets, "icon.svg"), "w") as f:
        f.write(svg(size=64, adaptive=True))
    manifest = {"name": "Amend", "short_name": "Amend",
                "description": "What changed at your airport, every FAA cycle.",
                "start_url": "/", "scope": "/", "display": "minimal-ui",
                "background_color": "#F6F8FA", "theme_color": "#F6F8FA",
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
    # maskable: Android crops to a circle or squircle, so the pair sits inside the safe zone
    app_icon(512, scale=MASKABLE_SCALE).save(os.path.join(assets, "icon-maskable-512.png"), optimize=True)
    return True


def wordmark_path(font=WORDMARK_FONT, tracking=-12):
    """'amend' in IBM Plex Sans SemiBold as SVG path data (y down, baseline at 0), and its advance width, in font
    units. Outlines, so the logo looks the same where the font isn't installed (GitHub, image viewers)."""
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
    """mark + wordmark, laid out like the site header (24 px mark, 17 px type, 8 px gap)."""
    path, width, upm = wordmark_path()
    fs = 64 * 17 / 24                      # type size on the mark's 64-unit grid
    s = fs / upm
    gap = 64 * 8 / 24
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont
    f = TTFont(WORDMARK_FONT)
    glyphs, cmap = f.getGlyphSet(), f.getBestCmap()
    top = 0
    for ch in "amend":                     # tallest ink above the baseline (the d), to centre the word
        bp = BoundsPen(glyphs)
        glyphs[cmap[ord(ch)]].draw(bp)
        top = max(top, bp.bounds[3])
    baseline = 32 + top * s / 2
    w = 64 + gap + width * s
    colors, text = (DARK, TEXT_DARK) if dark else (LIGHT, TEXT)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.1f} 64" width="{w * 56 / 64:.0f}" '
            f'height="56" role="img" aria-label="amend">{_inner(colors)}'
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
        f.write(svg(DARK, size=64))
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
        f.write(svg(size=64, adaptive=True))
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
