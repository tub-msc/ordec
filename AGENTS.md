# Guidance for LLM agents

## Overview

ORDeC (Open Rapid Design Composer) is a custom IC design platform consisting of:
- **The `ordec` Python package** (`src/ordec`)
- **ORDB**: Internal graph database for representing IC design data (schematics, symbols, layouts, simulation results)
- **ORD Hardware Description Language (HDL)** for design entry
- **Web UI** comprising a Python-based backend/server (`src/ordec/server.py`) and a Vite / vanilla JS frontend (`web/`).

ORDeC integrates various external tools, most importantly Ngspice for simulation and KLayout for DRC and LVS.

## Architecture

For narrative descriptions, see `docs/ref/` (data model, ORD language, cells/viewgens, schema, layout) and `docs/dev/` (webui, view generation, ORDB wire format, benchmarks, design decisions). Below are pointers into the source for orientation.

- **ORDB** (`src/ordec/core/ordb/`): custom graph database underlying all IC design data (Symbols, Schematics, Layouts, SimHierarchy, etc.). Node storage and indexing sit behind a pluggable backend interface (`backend.py` plus the `backend_*` modules: `pyrsistent`, `fullcopy`, `cow`, `delta`). The default is `pyrsistent-patricia`; `ORDEC_ORDB_BACKEND` or `ordb.use_backend(name)` selects another, and the suite is expected to pass under every backend. See `docs/ref/ordb.rst` and `docs/dev/ordb_benchmarks.rst`.
- **Cell and view generators** (`src/ordec/core/cell.py`): base class for parametrizable design components; `@viewgen`/`@viewgen_noctx` decorated methods produce cached views (schematic, symbol, layout, simulation). `src/ordec/server.py:discover_views` finds all view generators for the web UI. See `docs/ref/cell_and_viewgen.rst`.
- **ORD language** (`src/ordec/language.py`, `src/ordec/ord/`, `src/ordec/importer.py`): Python-superset HDL; `.ord` files compile to Python AST then `exec()` into ORDB structures. The importer adds an import hook so `.ord` files import like `.py` files. See `docs/ref/ord.rst` and `docs/guides/ord_tutorial.py`. Use ORD (not Python) for new standalone hardware designs.
- **Schema** (`src/ordec/core/schema/`): node type definitions, one module per view family (`schematic.py`, `layout.py`, `simhier.py`, `drc.py`, `lvs.py`, `report.py`, on the common `base.py`). See `docs/ref/schema.rst`.
- **Simulation**: `src/ordec/schematic/netlister.py` (Schematic → SPICE netlist), `src/ordec/core/simarray.py` (SimArray/SimColumn), `src/ordec/sim/ngspice.py` and `src/ordec/sim/simulator.py` (ngspice integration), `src/ordec/core/schema/simhier.py` (SimHierarchy).
- **Layout** (`src/ordec/layout/`): GDS import/export, KLayout integration, via generation; constraint helpers in `src/ordec/core/constraints.py`. See `docs/ref/layout.rst` and `docs/ref/layout_klayout.rst`.
- **Web interface**: backend `src/ordec/server.py` (WebSocket protocol, token auth, integrated/local mode); frontend `web/src/` (Golden Layout app, WebSocket client, renderers). See `docs/dev/webui.rst`.
- **Library system** (`src/ordec/lib/`): PDK primitives and integrations (base, sky130, ihp130, generic_mos), configured via `ORDEC_PDK_*` environment variables. Examples in `src/ordec/examples/`. Standard cell libraries are components on top of PDKs, not parts of PDKs.
- **External libraries** (`src/ordec/extlibrary.py`): external library/GDS cell integration. See `docs/ref/extlibrary.rst`.
- **Editor support** (`support/editors/`): ORD grammars and plugins for tree-sitter, VS Code, Sublime and JetBrains, kept aligned with the Lark grammar by the oracle tests in `support/editors/tests/`. See `docs/guides/editor_support.rst`.
- **ORDeC Hub** (`support/hub/`): multi-user workshop deployment, separate from the single-user server. See `docs/dev/hub.rst`.

Design principles (monorepo, ORDB-first, pure view generators, single source of truth): see `docs/dev/design_decisions.rst`.

Treat ORDB semantics as stable. If you want to change ORDB semantics, it is likely that your architectural direction is off. Require user confirmation before modifying ORDB semantics.

## Development Commands

### Environment Setup

```bash
# Install in editable mode with test dependencies
pip3 install -e .[test]

# Install documentation dependencies
pip3 install -r docs/requirements.txt

# Install frontend dependencies (first time only)
cd web/
npm ci
```

### Running Tests

```bash
# Run all tests from repository root (coverage configured in pytest.ini)
pytest

# Run specific test file
pytest tests/test_schematic.py

# Run tests matching pattern
pytest -k "test_ordb"

# Markers: web (web interface), libngspice
pytest -m web

# Fast testing: skip web tests (saves significant time)
# Use this when changes don't affect web interface or ngspice integration
pytest -m "not web"

# Editor grammar tests: pytest.ini has --ignore=support, so they need an
# explicit path and are not part of a plain 'pytest' run.
pytest support/editors/tests

# Run the suite against a non-default ORDB backend
ORDEC_ORDB_BACKEND=delta pytest -m "not web"
```

Web tests serve the frontend like `server.py` does: in a regular install, the packaged `webdist.tar` is used (no npm needed); in an editable install, `web/dist` is rebuilt automatically when it is missing or older than the frontend sources (`web/src/`), so no manual build step is needed. The rebuild requires npm on PATH; if a rebuild is needed and npm is missing, the web tests fail rather than silently skip.

Keep test runs short: never run multi-minute measurement commands; use the smallest scale that answers the question, wrap uncertain commands in `timeout`.

### Web UI Development

**Separate frontend + backend (recommended for development):**
```bash
# Terminal 1: Start Vite dev server with hot module replacement
cd web/
npm run dev

# Terminal 2: Start backend-only server
ordec -b

# Local mode example (opening mymodule.py and displaying MyCell().schematic):
ordec -b mymodule.py -e "MyCell().schematic"
# Equivalent with python-style module import (-m):
ordec -b -m mymodule -e "MyCell().schematic"
```

### Debugging view generation

1. Use local mode: `ordec mymodule.py` (or `ordec -m mymodule`)
2. Edit files in external editor
3. Server auto-reloads on file changes (inotify)
4. Check server terminal for Python tracebacks
5. Browser console shows WebSocket messages and client-side errors

### Documentation

```bash
cd docs/
make html
# Output in docs/_build/html/
```

## Style Guidelines

### Generated Code

When generating or modifying code:
- **Be concise**: Avoid unnecessary verbosity or over-engineering. The user strongly dislikes "clever" abstraction when a direct, explicit form is possible.
- **Include reasonable comments**: Explain non-obvious logic, design decisions, and complex algorithms
- **Balance clarity and brevity**: Code should be self-documenting where possible, but comments are valuable for:
  - Why something is done (not just what)
  - Non-obvious edge cases or constraints
  - References to external standards or documentation
  - Threading/synchronization concerns
- Never add linter suppression pragmas (`# noqa: F401`, `# type: ignore`, pylint disables). No linter is used in the project.

### Comments and Prose Style

- **No em/en dashes**: use colons, commas, semicolons, parens in all prose and comments; plain hyphens for ranges

### Indentation and Formatting

**Single-step indentation rule**: Indentation should never advance by more than one tab (4 spaces) between consecutive lines. This applies to all Python code and to docstring continuation lines after field labels (`Args:`, `Returns:`, `Raises:`, parameter names). It rules out visual alignment: do not align continuation lines with an opening parenthesis, and do not align docstring continuations with the text above them.

### Use of Git and commit messages

- Do not create a new git branch unless the user asks you to. Do not create a git commit unless the user asks you to. If a commit seems to belong elsewhere than the current branch, ASK rather than switch.
- Commit messages should be **concise and use plain tone**. The subject should start with a concise area prefix (hub:, webui:, ordb:, ...). Unless the diff is particularly large or convoluted, the message body should not summarize the diff. The message body should focus on *why* changes were made rather than repeat *what* changes were made. Try to choose a subject line that sufficiently explains the change and leave out the message body. The subject should say *what changed*, naming concrete identifiers or files touched if possible.

### Terminology

- **Minimal vocabulary:** When naming states/concepts, reuse the term family already established in the codebase instead of introducing new words.
- The terms "height"/"width" refer to extent, not position. Do not use the terms "height"/"width" to refer to y/x positions.
- Keep names and terminology professional. No gimmick names like "boss level", "museum" or "gremlin".
- When naming things, especially on public APIs, choose precise terms and make sure the terms do not collide with established terms (either of the codebase itself or of common jargon). Choose short names, e.g. drop superfluous adjectives.

### Adding test coverage

- Alongside new features or new critical edge cases, tests should be created. Reuse an existing `test_*.py` in `tests/` or add one, follow pytest conventions, and apply markers (`@pytest.mark.web` etc.) where needed.
- **Overtesting is discouraged!**  Keep in mind that tests add real code volume and carry forward costs. Therefore, it is critical that you do not overtest and keep test code concise and focused. In many situations, you can forgo creation of a new test by just adding some detail to existing tests. Keep the number of added tests and test logic complexity low. (As a rule of thumb, one test should roughly correspond to one feature.)
- When in doubt, prefer testing features using higher-level integration/system tests rather than using isolated unit tests.
- Moreover, consider and prioritize test runtime.
- Web tests are slow, so don't add narrow regression tests!
- When creating new tests, avoid overly long test names.

## Review and Security

When reviewing code or suggesting changes, focus on:

- Bugs, data corruption, correctness issues
- Resource leaks (file handles, processes, memory, threads)
- Thread safety and race conditions
- Proper cleanup of external processes
- Input validation for security-critical paths (module names, file paths)

Editor support code (`support/editors/`) gets light review only: run the cheap tests (`pytest support/editors/tests`, covering the grammar oracle and tree-sitter corpus), read the diff, skip heavy JetBrains/Gradle verification.

### Security model

ORDeC is designed for **local, single-user, trusted use only**, similar to Jupyter notebooks. For the mechanisms and their rationale, see `docs/dev/webui.rst` and `src/ordec/server.py`.

Assumptions:
- The server runs on localhost for a single authenticated user.
- By design, the authenticated user is allowed to run arbitrary code through the ORDeC server.
- `ordec` trusts all ORD/Python code the authenticated user writes or imports.
- User code runs with full permissions of the `ordec` process (no sandboxing).

Main threats:
- The web server could be exposed to unauthorized actors (malicious websites, browser extensions, accidental port exposure).
- The auth token is critical. Its role is to restrict code execution to the locally authorized user only.
- **CSRF is a threat**: Malicious websites could attempt cross-site requests to localhost.

Security mechanisms, in short: `server.py` enforces per-session token authentication on all WebSocket connections (`secrets.token_bytes(32)`, compared with `secrets.compare_digest()`); in "local mode", module/view names passed as URL parameters are authenticated with HMAC-SHA256, verified client-side before the connection is established, so malicious websites cannot import arbitrary modules via crafted URLs; and the server binds to localhost by default to reduce attack surface (this is not integral to the security, but exposing the single-user server to a wider network is not recommended). Multi-user workshop deployments use the separate ORDeC Hub instead, which gives every participant an ephemeral, isolated instance.

**When doing a security review, DO NOT flag as vulnerabilities:**
- Arbitrary code execution by the authenticated user via `eval()`/`exec()` (intentional, required for ORD HDL execution)
- Code execution from imported modules (intentional feature)
- Sandboxing suggestions (would break core functionality)

**DO treat the following as security issues:**
- Authentication bypass: Any way to execute code without valid auth token
- CSRF vulnerabilities: Missing HMAC validation, token leakage in Referer headers
- Token leakage: Tokens exposed in logs, browser history beyond current design
- Path traversal: Accessing files outside intended directories
- Command injection: Unsafe subprocess calls (though `shell=True` should never be used)

## Interaction

- **"Why" means rationale**: why-questions want the forcing chain (requirements, rejected alternatives, why they fail), not a mechanism walkthrough.
- **Negative evaluation means stop**: "evaluate before changing" is a real gate; a negative verdict ends the turn, no compromise variant.
- When the user asks a question about code (e.g., "what is X meant to be?"), just answer the question. Do not change the code unless explicitly asked to.
