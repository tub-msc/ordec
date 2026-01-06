# Guidance for LLM agents

## Overview

ORDeC (Open Rapid Design Composer) is a custom IC design platform consisting of:
- **ORD Hardware Description Language (HDL)** with two versions (ORD1, ORD2) for design entry
- **ORDB**: Internal graph database for representing IC design data (schematics, symbols, layouts)
- **Python backend** (websockets server + tool integration)
- **Web frontend** (Vite + vanilla JS with WebGL rendering)
- Integration with external tools (Ngspice for simulation, KLayout for layout viewing)

## Security Model and Usage Restrictions

**IMPORTANT**: ORDeC is designed for **local, single-user, trusted use only** - similar to Jupyter Notebook.

### Intended Usage
- **Local development**: Running on localhost (127.0.0.1) for a single authenticated user
- **Trusted code**: User has full control over the machine and trusts all code being executed
- **Similar to Jupyter**: Like Jupyter notebooks, ORDeC allows arbitrary code execution by design

### Threat Model
ORDeC's security model assumes:

✅ **Trusted**: Code executed by the authorized user
- The user running `ordec` trusts all ORD/Python code they write or import
- Arbitrary code execution is intentional and required for core functionality
- No sandboxing - user code runs with full permissions

❌ **Untrusted**: Unauthorized access attempts
- **Web server could be exposed** to unauthorized actors (malicious websites, browser extensions, accidental port exposure)
- **Auth token is critical**: Restricts code execution to the locally authorized user only
- **CSRF is a threat**: Malicious websites could attempt cross-site requests to localhost

### Security Mechanisms
1. **Token-based authentication** (`server.py`):
   - Cryptographically secure tokens generated per session (`secrets.token_bytes(32)`)
   - Constant-time comparison prevents timing attacks (`secrets.compare_digest()`)
   - Required for all WebSocket connections

2. **CSRF protection for local mode** (`server.py`):
   - HMAC-SHA256 authentication for module/view names
   - Prevents malicious websites from importing arbitrary modules via crafted URLs
   - Client-side verification before establishing WebSocket connection

3. **Localhost binding**:
   - Server defaults to 127.0.0.1, not exposed to network
   - User must explicitly change hostname to expose externally (not recommended)

### Code Review Guidance
When reviewing code or suggesting changes:

**Do NOT flag as vulnerabilities:**
- Arbitrary code execution via `eval()`/`exec()` (intentional, required for ORD HDL execution)
- Code execution from imported modules (intentional feature)
- Sandboxing suggestions (would break core functionality)

**DO treat as security issues:**
- **Authentication bypass**: Any way to execute code without valid auth token
- **CSRF vulnerabilities**: Missing HMAC validation, token leakage in Referer headers
- **Token leakage**: Tokens exposed in logs, browser history beyond current design
- **Path traversal**: Accessing files outside intended directories
- **Command injection**: Unsafe subprocess calls (though `shell=True` should never be used)

**DO focus on:**
- Bugs, data corruption, correctness issues
- Resource leaks (file handles, processes, memory, threads)
- Thread safety and race conditions
- Proper cleanup of external processes
- Input validation for security-critical paths (module names, file paths)

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

# Run tests with specific markers
pytest -m web           # Web interface tests
pytest -m libngspice    # Tests requiring libngspice

# Fast testing: skip web and libngspice tests (saves significant time)
# Use this when changes don't affect web interface or ngspice integration
pytest -m "not web and not libngspice"
```

### Web UI Development

**Separate frontend + backend (recommended for development):**
```bash
# Terminal 1: Start Vite dev server with hot module replacement
cd web/
npm run dev

# Terminal 2: Start backend-only server
ordec -b

# Local mode example (importing mymodule.py and displaying MyCell().schematic):
ordec -b -m "mymodule:MyCell().schematic"
```

### Documentation
```bash
cd docs/
make html
# Output in docs/_build/html/
```

## Code Style Guidelines

### Generated Code
When generating or modifying code:
- **Be concise**: Avoid unnecessary verbosity or over-engineering
- **Include reasonable comments**: Explain non-obvious logic, design decisions, and complex algorithms
- **Balance clarity and brevity**: Code should be self-documenting where possible, but comments are valuable for:
  - Why something is done (not just what)
  - Non-obvious edge cases or constraints
  - References to external standards or documentation
  - Threading/synchronization concerns

### Indentation and Formatting
**Single-step indentation rule**: Indentation should never advance by more than one tab (4 spaces) between consecutive lines. This applies to:
- All Python code (function definitions, class definitions, control structures, etc.)
- Docstring continuation lines after field labels (`Args:`, `Returns:`, `Raises:`, parameter names)

**Correct examples:**
```python
# Code indentation
def example():
    if condition:
        result = some_function(
            arg1,
            arg2,
            arg3
        )

# Docstring indentation
def example_function(param1, param2):
    """
    Brief description of function.

    Args:
        param1: First parameter description that may span
            multiple lines uses single tab for continuation.
        param2: Second parameter.

    Returns:
        Description of return value that continues
        on next line needs no additional tab.

    Raises:
        ValueError: When something goes wrong and this
            description continues on next line.
    """
    pass
```

**Incorrect** (avoid multi-level indentation jumps):
```python
# DON'T DO THIS - Code:
def example():
    if condition:
        result = some_function(
                     arg1,  # Jumps too far
                     arg2,
                     arg3
                 )

# DON'T DO THIS - Docstrings:
    Args:
        param1: First parameter description that may span
                multiple lines - DO NOT align with text above.
```

## Architecture

### Core Data Model (ORDB)

The foundation is ORDB (ordec/core/ordb.py), a custom graph database using immutable persistent data structures (pyrsistent). Key concepts:

- **Nodes**: Typed graph nodes with attributes (similar to database records)
- **Subgraphs**: Collections of related nodes with indexes for queries
- **SubgraphRoot**: Entry point to a subgraph (nid=0)
- **Inserters**: Functions that add nodes to subgraphs during construction
- **Indexes**: Query interfaces (unique indexes enforce constraints)

All IC design data is represented as ORDB subgraphs: Symbols, Schematics, Layouts, SimHierarchy, etc.

### Cell and View Generators

**Cell** (ordec/core/cell.py): Base class for parametrizable design components
- Cells can have Parameters (type-checked, immutable)
- View generators (@generate decorator) create different representations (schematic, symbol, layout, simulation)
- Views are cached and hashable
- Cell instances are immutable and hashable

**View discovery** (ordec/server.py:discover_views): Server automatically finds all @generate decorated methods and @generate_func decorated functions to populate the web UI view list.

### Language Layer

**ORD HDL** (ordec/language.py, ordec/ord1/, ordec/ord2/):
- Version detection from first line comment (e.g., `# version: ord2`)
- ORD1: Original syntax with Lark parser → AST → Python
- ORD2: Newer syntax with improved features (keyword `viewgen` for view generators), intended as superset of Python
- Both compile to Python AST, then executed to build ORDB structures

**Parser flow**: `.ord file` → `ord_to_py()` → Python AST → `exec()` → ORDB subgraphs

### Schema Layer

**Schema** (ordec/core/schema.py): ORDB node type definitions for IC design
- **Symbol**: Cell symbol with Pins, geometric shapes for visual representation
- **Schematic**: Circuit netlist with Nets, SchemInstances, SchemInstanceConns
- **Layout**: Physical layout with LayoutInstances, shapes on layers, routing
- **SimHierarchy**: Flattened simulation hierarchy with SimInstances, SimNets

Each schema type is a Node subclass with Attr declarations and indexes.

### Simulation Integration

**Netlister** (ordec/schematic/netlister.py): Converts Schematic → SPICE netlist
- Recursive subcircuit netlisting
- Directory tracks node naming
- Setup functions for PDK-specific initialization

**Ngspice** (ordec/sim/): Multiple backend modes
- ngspice_subprocess.py: Subprocess communication
- ngspice_ffi.py: FFI using libngspice
- ngspice_mp.py: Multiprocessing wrapper

**SimHierarchy** (ordec/sim/sim_hierarchy.py): Flattened simulation hierarchy for result analysis

### Layout

**Layout subsystem** (ordec/layout/):
- GDS import/export (gds_in.py, gds_out.py)
- KLayout integration (klayout.py)
- Via generation (makevias.py)
- Constraint-based layout helpers (ordec/core/constraints.py)

### Web Interface

**Server** (ordec/server.py):
- WebSocket-based client-server architecture
- Token-based authentication (HMAC-SHA256 for local mode)
- Two modes:
  - **Integrated mode**: Code edited in browser, not saved to disk
  - **Local mode**: Files on filesystem, inotify-based auto-reload
- Static file serving from webdist.tar (production) or separate Vite server (development)

**Frontend** (web/src/):
- main.js: Application entry point, Golden Layout setup
- client.js: WebSocket client, view management
- resultviewer.js: Result rendering logic
- layout-gl.js: WebGL-based layout renderer
- ace-ord-mode.js: Syntax highlighting for ORD language

**Communication protocol**:
1. Client sends auth token + source/localmodule
2. Server builds cells, discovers views, sends view list
3. Client requests specific view data
4. Server evaluates view generator, sends typed data (schematic, layout, plot, etc.)

### Library System

**PDK Libraries** (ordec/lib/):
- base.py: Common primitives (resistors, capacitors, voltage sources)
- sky130.py: Skywater 130nm PDK integration
- ihp130.py: IHP SG13G2 PDK integration
- generic_mos.py: Generic MOSFET models

**Examples** (ordec/lib/examples/): .ord and .py example designs with .uistate.json UI state

**PDK configuration**: Environment variables (ORDEC_PDK_SKY130A, ORDEC_PDK_IHP_SG13G2, etc.)

### External Tool Integration

**Importer** (ordec/importer.py): Custom import hook for .ord files to work as Python modules

**ExtLibrary** (ordec/extlibrary.py): External library/GDS cell integration

### Key Design Principles

1. **Immutability**: ORDB uses immutable data structures (pyrsistent), Cells and views are immutable
2. **Pure functions**: View generators should be deterministic
3. **Separation**: ORD/Python source is single source of truth, ORDB is internal format
4. **Monorepo**: All components in single repository with modular structure

## Common Workflows

### Adding a new Cell type
1. Subclass Cell in appropriate lib file
2. Define Parameters as class attributes
3. Add @generate decorated methods for symbol, schematic, etc.
4. Return appropriate SubgraphRoot (Symbol, Schematic, Layout)
5. Optionally set .cell attribute on returned subgraph

### Adding a new test
1. Create test_*.py in tests/ directory
2. Use pytest conventions (test_* functions)
3. Import from ordec.core or specific modules
4. Use markers (@pytest.mark.web, @pytest.mark.libngspice) if needed

### Working with ORDB data
1. Create SubgraphRoot instance (e.g., Schematic())
2. Add nodes via insertion: `node.insert_into(subgraph, nid)`
3. Query nodes via indexes: `subgraph.all(NodeType)`, `subgraph.one(index.query(value))`
4. Freeze mutable subgraphs before returning: `mutable_node.freeze()`

### Debugging view generation
1. Use local mode: `ordec -m mymodule`
2. Edit files in external editor
3. Server auto-reloads on file changes (inotify)
4. Check server terminal for Python tracebacks
5. Browser console shows WebSocket messages and client-side errors
