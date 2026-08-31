# UnifiedFieldTheory consumer contract

- Source card: `Vivhite/VivhiteCode/Cards/Hybrid/UnifiedFieldTheory.cs`.
- Runtime type: rare, self-targeting Power; energy cost `3`; fixed 謦欬 cost `14`.
- Power semantics: every Margin point that prevents 謦欬 grants `4` Drain percentage points per stack; actual Drain healing returns `floor(H/3)` Margin, or `floor(H/2)` for the upgraded Power; no custom gameplay cap.
- Chinese localization title: `统一场论`; card text describes the same Margin → Drain → Margin loop.
- Portrait resolver: `VivhiteCard.CustomPortraitPath` resolves the compiled type name to `res://Vivhite/images/cards/UnifiedFieldTheory.png`.
- Consumer form: one independent PNG loaded directly by Godot; no atlas, region, Spine slot, pivot, animation frame, or transparency layer.
- Runtime image contract: `1000x760`, PNG color type `2` (`RGB8`), no Alpha, full-bleed environment, no card frame or text baked into the artwork.
- Conversion: largest centered integer `25:19` crop from the untouched native output, followed by Lanczos resize through `tools/art/prepare_vivhite_card_portrait.gd`.

The visual specification therefore uses a stable vertical/cyclic self-Power silhouette. It deliberately excludes outgoing attacks, targets, impacts, incoming strikes, shields, and defensive domes.
