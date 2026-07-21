<!--
SPDX-FileCopyrightText: 2026 ORDeC contributors
SPDX-License-Identifier: Apache-2.0
-->

# tree-sitter-ord

tree-sitter grammar for the ORD language.

Unlike the TextMate/Sublime packages in `editors/`, this folder contains a
real parser. It targets tree-sitter-based editors — tree-sitter originated in
Atom, and is used today by its successor Pulsar as well as Neovim, Emacs 29+,
Helix and Zed. See `docs/editor_support.rst` for editor setup.

## Design

ORD is Python-derived, but it is not just Python with a few colored keywords.
It introduces grammar-level constructs such as:

- `cell` and `viewgen` declarations
- node statements like `output y:`, `Nmos n1:`, `Series(gap=4) core:`
- `anonymous` and bodyless node statements (`nmos m3, m5, m7`)
- `path` / `net` statements
- constrain statements like `! .pos == (0, 0)`
- member and parameter access `.align`, `.$l`, `t.$w`
- connection statements like `.y -- out`
- SI-suffixed number literals like `400n`

Because of that, this grammar is implemented as:

- an extension of the tree-sitter-python grammar (tree-sitter's
  grammar-inheritance mechanism, as used by tree-sitter-typescript to
  extend JavaScript) — Python comes from the `tree-sitter-python` npm
  devDependency, only the ORD delta lives in `grammar.js`
- ORD-specific productions where the language diverges (including the
  removal of the Python 2 legacy print/exec statements)
- query files layered on top for highlighting

The authoritative ORD grammar is `ordec/ord/ord.lark`.
`tests/test_editor_grammars.py` compiles this parser and cross-checks it
against the Lark parser on every `.ord` file in the repository. Update this
grammar whenever `ord.lark` changes.

## Important Files

- [grammar.js](./grammar.js):
  grammar source (ORD delta on top of tree-sitter-python)
- `src/parser.c`:
  generated parser (gitignored — create it with `npm run generate`)
- `src/scanner.c`:
  external scanner (indentation, strings, comments), copied from the
  tree-sitter-python devDependency by `npm run generate` (gitignored)
- [queries/highlights.scm](./queries/highlights.scm):
  generic highlight query
- [queries/highlights-emacs.scm](./queries/highlights-emacs.scm):
  Emacs-specific highlight query (plain patterns only)
- [queries/tags.scm](./queries/tags.scm):
  tags query
- [queries/folds.scm](./queries/folds.scm):
  shared folding query for tree-sitter-aware editors
- [queries/locals.scm](./queries/locals.scm):
  shared locals/scope query for tree-sitter-aware editors

## Build

The entire `src/` directory is derived and gitignored, and `grammar.js` is
the source of truth. Generate it on a fresh checkout and after editing
`grammar.js`:

```bash
npm ci
npm run generate
```

The generate script copies the external scanner from the pinned
`tree-sitter-python` version (renaming its exported symbols to
`tree_sitter_ord_*`) and runs `tree-sitter generate --abi 14`. ABI 14 keeps
the parser loadable by the tree-sitter runtimes bundled with current
editors. When bumping the `tree-sitter-python` dependency, rerun the corpus
tests and the repository grammar tests — upstream node-shape changes
surface there.

Build the shared library used by Emacs and other libtree-sitter consumers:

```bash
cc -fPIC -shared -I src src/parser.c src/scanner.c -o libtree-sitter-ord.so
```

## Validation

Run the corpus tests, which also validate all query files:

```bash
npm test
```

For ad-hoc parsing of single files with `npx tree-sitter parse`, run
`npx tree-sitter init-config` once and add this repository's `editors/`
directory to the `parser-directories` list in the created config file.

The repository test suite additionally parses all `.ord` files with this
parser (`.venv/bin/pytest tests/test_editor_grammars.py`). Those tests skip
until the parser has been generated.

## References

- [tree-sitter](https://github.com/tree-sitter/tree-sitter)
- [Python 3 grammar](https://docs.python.org/3/reference/grammar.html)

## Licensing

This package is derived from the MIT-licensed `tree-sitter-python` grammar.
Files containing upstream tree-sitter-python material are licensed
`MIT AND Apache-2.0`, while ORDeC-only files such as
`queries/highlights-emacs.scm` are licensed Apache-2.0. `LICENSE.md`
contains both license texts.
