# Sprunki Pokemon Jam

A classic Sprunki-style music mixer, packaged for the web with [TurboWarp](https://turbowarp.org/).

**Play:** https://sprunkijam.github.io/sprunkipokemonjam/

This build uses the classic Sprunki placeholders. Pokémon-inspired sprites are planned as costume replacements later — they are **not** included yet.

## About

Drag characters onto the stage to layer beats and melodies, Incredibox / Sprunki style. Playback runs in the TurboWarp runtime (a Scratch-compatible engine with performance improvements).

Ideas inspired by community Sprunki / Incredibox-style mixers. Built with TurboWarp for packaging and playback.

**Not affiliated** with Sprunki, Incredibox, Nintendo, or Pokémon.

## Swap sprites later

Sprites live as **costumes** inside the Scratch project (`sprunki-base.sb3`):

1. Open `sprunki-base.sb3` in [TurboWarp](https://turbowarp.org/editor) or Scratch.
2. Select a character sprite and replace its costumes with your new artwork (same size / centering helps).
3. Keep sound/costume names aligned with how the project scripts expect them, or update the scripts to match.
4. Save the `.sb3`, replace `sprunki-base.sb3` in this repo, then rebuild:

    npm ci
    npm run build

GitHub Actions rebuilds `dist/` on every push to `main`, so you do not need to commit the packaged output.

## Local build

    npm ci
    npm run build

Static site output is written to `dist/` (open `dist/index.html` or serve that folder).

## License / credits

See [CREDITS.md](./CREDITS.md). Community remix — respect original creators and trademarks.
