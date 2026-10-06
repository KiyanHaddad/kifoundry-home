# Asset provenance

## Documentation screenshot

`docs/images/town-demo.jpg` is an unedited browser capture of this application on 6 October 2026. It shows a fresh offline fixture town with the default Echo and Quill residents and no user conversations. It contains no browser chrome, local paths, launch URL or native provider data. The included artwork and fonts retain the provenance and licenses below.

SHA-256: `ed36ca3b0191b949d96a2cb7285d498b44853efcfa360b51e1843664b67432d6`.

Public demonstration text in `examples/script.txt` and the interface code are original to this project. Provider CLIs are external prerequisites and are not bundled.

## Illustrated town and residents

These four illustrations were generated for this project on 6 October 2026 using Codex's built-in image generation tool. The distributed illustrations are generated assets; no sprites from reference repositories are bundled. The exact generation prompts ship in docs/asset-prompts.json, and the conversion details and distributed hashes are recorded below.

| Distributed asset | Dimensions | Bytes | Conversion |
| --- | --- | ---: | --- |
| `home/web/town-dusk.webp` | 1536 × 1024 | 683,718 | WebP quality 90, method 6; original dimensions |
| `home/web/residents.webp` | 2172 × 724 | 1,119,386 | Lossless WebP, method 6; original dimensions and exact alpha channel |
| `home/web/town-terrain.webp` | 1536 × 1024 | 611,324 | WebP quality 90; original dimensions, no resize |
| `home/web/houses.webp` | 2172 × 724 | 746,356 | Lossless WebP, method 6; original dimensions and exact RGBA pixels |

No crop, resize, retouch or replacement of illustration content was performed during packaging. Each town image satisfies a 1,000,000-byte budget. Both atlases retain transparency, including fully transparent pixels. The house atlas was reloaded after lossless conversion and every RGBA pixel matched its selected source PNG. The town images use lossy compression, so their pixels are not claimed identical to their source PNGs. The source PNGs remain untouched.

The original town is a single background illustration and the resident atlas contains five static figures. These assets do not establish directional walking animations, real agent activity, unique copyright, or provider execution. Activity and identity must come from application state.

SHA-256 of the distributed assets:

- `town-dusk.webp`: `75917de1078cdbba6f17ea1c620517c898fe217ff16863c8075fcc759f21e226`
- `residents.webp`: `4a4573411ccc3c0e1b879fda18140acfea449edb1a7aa575f6f88b7c8d8fbe71`
- `town-terrain.webp`: `b3801a4e82066b909ff83fdd744303b288dca96836482b37f8a0783105251afe`
- `houses.webp`: `eb777b71fef42c478e49276ce456151e1e07b504883088a956afa9975ab11742`

## Modular terrain and houses

The terrain is an image-generation edit of the original town illustration. Five painted residential cottages were replaced with empty clearings; the forest, paths, stream, Council table and studio remain scenery. The house atlas was generated with the original town as a style reference, then corrected twice through image generation to separate its five cottages. Earlier assets remain available. No agent names, provider identities or private paths are baked into these new images.

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

The new hashes are included in the reviewed binary allowlist in `scripts/check_public_tree.py`. A changed binary requires provenance review again. These checks do not establish owner acceptance or browser usability.

## Self-hosted fonts

Unmodified TrueType files were downloaded from the official Google Fonts endpoints. They are served from this application; font rendering requires no request to Google. Each family is licensed under the SIL Open Font License 1.1, with its original copyright notice and full license in `docs/font-licenses/`. Those license files are declared as distribution data under `share/kifoundry-home/font-licenses`.

| Asset | Source | SHA-256 |
| --- | --- | --- |
| `home/web/fraunces-500.ttf` | [Fraunces 500](https://fonts.gstatic.com/s/fraunces/v38/6NUh8FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0K7iN7hzFUPJH58nib1603gg7S2nfgRYIchRujDg.ttf) | `0c2fad18ed36cc400041f1e281ee79954a329b345caffc38dfaa3bb8bcef57de` |
| `home/web/manrope-400.ttf` | [Manrope 400](https://fonts.gstatic.com/s/manrope/v20/xn7_YHE41ni1AdIRqAuZuw1Bx9mbZk79FO_F.ttf) | `a13d9b41b0a471ce58f0e46d377fa3cc76615e4632c3b15eb397caadf7a13f0a` |
| `home/web/manrope-600.ttf` | [Manrope 600](https://fonts.gstatic.com/s/manrope/v20/xn7_YHE41ni1AdIRqAuZuw1Bx9mbZk4jE-_F.ttf) | `6bad1a774228464cc88b8b0271555b266f7a3c64a7bedf15e165fdab4f6ac0ce` |

The official [Fraunces OFL](https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/OFL.txt) and [Manrope OFL](https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt) were retrieved with the font files. The project's MIT license does not replace these font licenses.

Review the exact release tree before publication. Packaging and hashes establish these files' origin and conversion; browser appearance and usability require separate checks.
