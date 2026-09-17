# Garden horizon

Generated with the built-in imagegen tool on 2026-09-17. Style reference: the Tomade improvement mockup approved for implementation in this task. The original PNG is preserved at `/Users/anjeongseob/.codex/generated_images/01a0ae39-e339-7da1-a608-0cafafe43bc8/exec-57b86402-00cb-4029-9f74-a21dfa55d59a.png`.

The committed `garden-horizon.webp` is a quality-88 WebP encoding of that PNG (`cwebp -q 88 -sharp_yuv -m 6`), approximately 97 KiB at 2172×724. The office uses this same image behind the house and inside its window panes. No runtime generation, color-key removal or palette conversion is needed for the panorama. The three window placements reuse one composed sprite.

## Generation prompt

Use case: stylized-concept. Asset type: production 2D pixel-art horizontally repeating distant garden background strip for the existing Tomade web UI.
Input reference: the approved Tomade office concept image is STYLE AND PALETTE REFERENCE ONLY. Generate ONLY the OUTDOOR BACKGROUND STRIP, no house, no office, no UI, no foreground props or foreground trees.
Composition: very wide 3:1 panoramic strip, preferably 1536x512. Upper 30 percent clear pale blue daylight sky with a few restrained small pixel clouds. Middle 35 percent layered distant blue-green low hills and quiet olive/sage deciduous treeline, leaves formed from crisp fine pixel clusters. Lower 35 percent gently receding open sage-green lawn, just a few very subtle fine grass flecks at the upper lawn. The final bottom 10 percent MUST be absolutely flat solid sage green HEX #9bb97e with no texture, no shadow, no lines; transition gently from the lawn to this flat color so it can meet the app's ground background seamlessly. The uppermost edge is flat sky HEX #acd5eb. Left/right edges must match seamlessly for horizontal tiling, continuous sky, forest and lawn heights. Restrained and airy, no dense visual noise.
Style: match the fine small-pixel cozy garden style in the reference, soft colors with lower contrast in distant foliage, light from upper left. Carefully placed crisp pixel clusters, not blurry painted detail, no oversized block pixels. This is a distant background, so NO large standalone trees, no visible trunks in foreground, no houses, buildings, roads, paths, benches, fences, people, flowers in foreground, text, UI, border or watermark. We will place large trees separately in front.
One single finished background strip filling the image, no labels, no atlas grid.
