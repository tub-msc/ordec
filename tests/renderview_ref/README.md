# Renderview Reference SVGs

These SVGs are reference outputs for the `test_renderview` tests. They are
rendered **without CSS** so that style changes in `SchematicRenderer` don't
require bulk-updating every file in this directory.

Because of this, the raw SVGs look unstyled when opened directly in a browser
(no colors, wrong fonts, missing stroke settings, etc.). This is expected.

## Viewing styled SVGs

Run `make_styled.py` to produce a `styled/` subdirectory with CSS injected:

```bash
python tests/renderview_ref/make_styled.py
```

The script reads the CSS from `ordec.render.SchematicRenderer` (the single
source of truth) and inserts it into each SVG. The `styled/` directory is
gitignored.
