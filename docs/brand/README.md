# Amend logo

Three lines of text with an amber bar beside the one that changed, the way amended FAA publications mark revised
text in the margin. The wordmark is lowercase **amend** in Geist SemiBold; in running text the name is "Amend".

| file | use |
|---|---|
| `mark.svg` | the mark on its own |
| `lockup-light.svg`, `lockup-dark.svg` | mark + wordmark for light and dark backgrounds (outlined, no font needed) |
| `app-icon.png` | 1024 px, edge to edge, for anywhere that rounds its own corners |

| colour | hex | where |
|---|---|---|
| tile | `#11151B` | the square; `#28303B` on dark backgrounds so it doesn't sink in |
| bar | `#F5B040` | the one amber stroke, same as action items on the site |
| changed line | `#F3F4F6` | |
| other lines | `#5E6773` | |

Keep the bar amber and the tile dark, and don't use the mark below 16 px. Everything is generated from
`amend/brand.py`: the site's favicons and link-preview images on every build, and the iOS app icons and these
files with `python -m amend.brand`.
