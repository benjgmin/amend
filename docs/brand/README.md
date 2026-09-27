# Amend logo

A taxiway location sign: the black sign with a yellow border and a yellow letter that tells a pilot where they are
on the airport. Ours says A. The wordmark is lowercase **amend** in Geist SemiBold; in running text the name is
"Amend".

| file | use |
|---|---|
| `mark.svg` | the mark on its own |
| `lockup-light.svg`, `lockup-dark.svg` | mark + wordmark for light and dark backgrounds (outlined, no font needed) |
| `app-icon.png` | 1024 px, edge to edge, for anywhere that rounds its own corners |

| colour | hex | where |
|---|---|---|
| panel | `#11151B` | the sign; `#28303B` on dark backgrounds so it doesn't sink in |
| border and letter | `#F5B040` | the same amber the site uses for action items |

Keep the border and the A amber and the panel dark, and don't use the mark below 16 px. The A is Geist at weight
800. Everything is generated from `amend/brand.py`: the site's favicons and link-preview images on every build,
and the iOS app icons and these files with `python -m amend.brand`.
