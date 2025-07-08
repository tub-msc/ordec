Design Decisions
================

We collect some past and future design decisions here.

- ORDeC is organized as a **monorepo**. Inside it, things should be as modular as possible.
- Use ORDB for internal data as much as possible. Avoid YAML and flat string keys.
- Support common exchange formats like Verilog, Spice netlists, DEF/LEF and GDS.
- Design tasks should be pure functions.
- The native design entry format (ORD/Python) is separate from the native exchange format (serialized ORDB). Foreign exchange formats can be used for both purposes, design entry and exchange.
- Do not generate code for the user. Eliminate the need for boilerplate and overly verbose code.
- The ORD or Python design input should act as single source of truth.
- Try to minimize external dependencies, especially if they are large and at risk of becoming unmaintained.
