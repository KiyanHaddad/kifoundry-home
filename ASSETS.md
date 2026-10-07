# Asset provenance

## Documentation screenshot

`docs/images/town-demo.jpg` is an unedited browser capture of version 0.1.3 on 6 October 2026. It shows the working desk and the Commons Quarter in an isolated 64-resident fixture town. All names and the conversation are synthetic. It contains no browser chrome, local paths, launch URL, private user records or native provider data. The included artwork and fonts retain the provenance and licenses below.

SHA-256: `6638d376620db0bb420c333f397d5acc67375c3ee18b24ce36a35f1c690dcd64`.

Public demonstration text in `examples/script.txt` and the interface code are original to this project. Provider CLIs are external prerequisites and are not bundled.

## Illustrated town and residents

These five illustrations were generated for this project on 6 October 2026 using Codex's built-in image generation tool. The distributed illustrations are generated assets; no sprites from reference repositories are bundled. The exact generation prompts ship in docs/asset-prompts.json, and the conversion details and distributed hashes are recorded below.

| Distributed asset | Dimensions | Bytes | Conversion |
| --- | --- | ---: | --- |
| `home/web/town-dusk.webp` | 1536 × 1024 | 683,718 | WebP quality 90, method 6; original dimensions |
| `home/web/residents.webp` | 2172 × 724 | 1,119,386 | Lossless WebP, method 6; original dimensions and exact alpha channel |
| `home/web/town-terrain.webp` | 1536 × 1024 | 611,324 | WebP quality 90; original dimensions, no resize |
| `home/web/houses.webp` | 2172 × 724 | 746,356 | Lossless WebP, method 6; original dimensions and exact RGBA pixels |
| `home/web/town-props.webp` | 1448 × 1086 | 549,054 | Lossless WebP, method 6; original dimensions and exact RGBA pixels |

No crop, resize, retouch or replacement of illustration content was performed during packaging. Each town image satisfies a 1,000,000-byte budget. All three atlases retain transparency, including fully transparent pixels. The house and prop atlases were reloaded after lossless conversion and every RGBA pixel matched their selected source PNGs. The town images use lossy compression, so their pixels are not claimed identical to their source PNGs. The source PNGs remain untouched.

The two earlier town images remain in the package but are not rendered by the live map. The live terrain combines procedural SVG ground and paths with the reusable generated prop atlas, resident cottages and people. The resident atlas contains five static figures. These assets do not establish directional walking animations, real agent activity, unique copyright, or provider execution. Activity and identity must come from application state.

SHA-256 of the distributed assets:

- `town-dusk.webp`: `75917de1078cdbba6f17ea1c620517c898fe217ff16863c8075fcc759f21e226`
- `residents.webp`: `4a4573411ccc3c0e1b879fda18140acfea449edb1a7aa575f6f88b7c8d8fbe71`
- `town-terrain.webp`: `b3801a4e82066b909ff83fdd744303b288dca96836482b37f8a0783105251afe`
- `houses.webp`: `eb777b71fef42c478e49276ce456151e1e07b504883088a956afa9975ab11742`
- `town-props.webp`: `5db01f5d76f1c8d00c59285ec9faf3017afd80d28bd5244b9e695b22e95ba84e`

## Modular terrain and houses

The retained `town-terrain.webp` is an image-generation edit of the original town illustration. Five painted residential cottages were replaced with empty clearings; the forest, paths, stream, Council table and studio remain scenery in that historical image. The house atlas was generated with the original town as a style reference, then corrected twice through image generation to separate its five cottages. Earlier assets remain available. No agent names, provider identities or private paths are baked into these images.

Application state determines which reusable houses and residents appear. These illustrations alone do not establish agent activity or working add/remove controls.

The house sheet has five equal-width cells of 434.4 pixels. All four nominal cell boundary columns have alpha zero. At alpha 16 or greater, the cottages' local cell bounds are:

| Variant | Left | Top | Right | Bottom |
| --- | ---: | ---: | ---: | ---: |
| Terracotta | 77 | 222 | 375 | 562 |
| Teal | 91 | 221 | 373 | 576 |
| Slate | 70 | 220 | 356 | 577 |
| Plum | 57 | 223 | 365 | 575 |
| Sage | 77 | 221 | 370 | 578 |

Bounds use rounded equal-cell edges and exclusive right/bottom coordinates. The exact 85% baseline requested in the prompt was not achieved: solid cottage feet fall between 77.6% and 79.8% of image height. Placement must account for those offsets. Very faint alpha residual pixels and fine fringes remain in some cells. No visual cleanup or alpha thresholding was performed during format conversion.

### Reusable terrain props

`town-props.webp` was generated with `houses.webp` and `town-terrain.webp` as style references, then revised twice through image generation to separate the props. It contains eight complete props in four columns and two rows: pine, broadleaf tree, shrub and rocks, lantern, Council table and eight chairs, canopy writing studio, pond, and herb garden. No asset from another repository was used.

Each cell is exactly 362 × 543 pixels. The following bounds are local to its cell and include pixels with alpha greater than 8; right and bottom coordinates are exclusive. Rendering uses measured offsets because the requested shared baseline was not achieved. The final correction centered the isolated props with generous margins.

| Prop | Column | Row | Left | Top | Right | Bottom |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pine | 0 | 0 | 113 | 157 | 272 | 399 |
| Broadleaf tree | 1 | 0 | 110 | 165 | 299 | 398 |
| Shrub and rocks | 2 | 0 | 97 | 244 | 289 | 386 |
| Lantern | 3 | 0 | 141 | 179 | 258 | 399 |
| Council table | 0 | 1 | 78 | 216 | 323 | 410 |
| Writing studio | 1 | 1 | 112 | 173 | 320 | 405 |
| Pond | 2 | 1 | 66 | 197 | 320 | 409 |
| Herb garden | 3 | 1 | 85 | 199 | 296 | 401 |

The source alpha ranges from 0 to 255. All 20-pixel cell border bands contain no alpha greater than 1. Scattered alpha-1 pixels remain in some gutters; these were preserved without cleanup or thresholding. Lossless format conversion preserved every RGBA pixel, including those faint residuals. The distributed WebP contains one `VP8L` pixel-data chunk and no EXIF, XMP or ICC metadata.

Reviewed illustration hashes belong in the binary allowlist in `scripts/check_public_tree.py`. A changed binary requires provenance review again. These checks do not establish owner acceptance or browser usability.

## Self-hosted fonts

Unmodified TrueType files were downloaded from the official Google Fonts endpoints. They are served from this application; font rendering requires no request to Google. Each family is licensed under the SIL Open Font License 1.1, with its original copyright notice and full license in `docs/font-licenses/`. Those license files are declared as distribution data under `share/kifoundry-home/font-licenses`.

| Asset | Source | SHA-256 |
| --- | --- | --- |
| `home/web/fraunces-500.ttf` | [Fraunces 500](https://fonts.gstatic.com/s/fraunces/v38/6NUh8FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0K7iN7hzFUPJH58nib1603gg7S2nfgRYIchRujDg.ttf) | `0c2fad18ed36cc400041f1e281ee79954a329b345caffc38dfaa3bb8bcef57de` |
| `home/web/manrope-400.ttf` | [Manrope 400](https://fonts.gstatic.com/s/manrope/v20/xn7_YHE41ni1AdIRqAuZuw1Bx9mbZk79FO_F.ttf) | `a13d9b41b0a471ce58f0e46d377fa3cc76615e4632c3b15eb397caadf7a13f0a` |
| `home/web/manrope-600.ttf` | [Manrope 600](https://fonts.gstatic.com/s/manrope/v20/xn7_YHE41ni1AdIRqAuZuw1Bx9mbZk4jE-_F.ttf) | `6bad1a774228464cc88b8b0271555b266f7a3c64a7bedf15e165fdab4f6ac0ce` |

The official [Fraunces OFL](https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/OFL.txt) and [Manrope OFL](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt) were retrieved with the font files. The project's MIT license does not replace these font licenses.

Review the exact release tree before publication. Packaging and hashes establish these files' origin and conversion; browser appearance and usability require separate checks.
