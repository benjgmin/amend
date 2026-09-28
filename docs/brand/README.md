# Amend logo

An edit: the old a struck through in magenta and the new a beside it, the way a correction reads on paper and the
way Amend shows every change, the old value and then the new one. The wordmark is lowercase **amend** in IBM Plex
Sans SemiBold; in running text the name is "Amend".

| file | use |
|---|---|
| `mark.svg` | the mark on its own (switches to the dark colours in dark mode) |
| `lockup-light.svg`, `lockup-dark.svg` | mark + wordmark for light and dark backgrounds (outlined, no font needed) |
| `app-icon.png` | 1024 px, edge to edge, for anywhere that rounds its own corners |

| part | light | dark |
|---|---|---|
| tile | `#FFFFFF`, `#C3CCD7` edge | `#0E1926`, `#2E4460` edge |
| old a | `#AAB5C3` | `#4F627B` |
| strike | `#A3186E` | `#E26BB2` |
| new a, wordmark | `#0D1B2A` | `#E6EDF5` |

The magenta is the one the site and the app use for changes that need action, and the blue beside it (`#1A5EA6`,
`#7FB2EC` in dark) is for IFR and links: the two colours of a sectional chart. Everything else is neutral.

Keep the strike magenta and the old a lighter than the new one, and don't use the mark below 16 px. Everything is
generated from `amend/brand.py`: the site's favicons and link-preview images on every build, and the iOS app icons
and these files with `python -m amend.brand`.
