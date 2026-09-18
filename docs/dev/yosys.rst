Yosys Integration
=================

ORDeC uses Yosys_ in two places:

- ``ExtLibrary.read_verilog`` (``src/ordec/schematic/verilog_in.py``) runs ``yosys`` to convert a synthesized Verilog netlist to Yosys JSON, from which the schematic is built.
- ``tests/test_verilog_in.py`` synthesizes a small counter (``tests/lib/counter.v``) to IHP SG13G2 standard cells and imports the result. This test drives Yosys through its Tcl mode (``yosys -c``) using notcl_.

Yosys is an **optional** dependency. ORDeC only needs the ``yosys`` executable on ``PATH`` when ``read_verilog`` is called. Tests that need Yosys carry the pytest marker ``yosys`` and can be deselected with ``pytest -m "not yosys"``.

How Yosys is provided
---------------------

The ordec-base image builds Yosys from source (stage ``ordec-build-yosys`` in *base.Dockerfile*), like Ngspice and KLayout:

- The source is the release asset *yosys.tar.gz*, not the GitHub tag archive. Only the release asset contains the submodules (abc, slang and others).
- The slang frontend (``read_slang``, SystemVerilog) is part of the Yosys tree and enabled by default. No separate yosys-slang plugin is needed.
- The Debian package was not an option: Debian trixie ships Yosys 0.52.

Outside the container, users install Yosys themselves.

Why not pyosys
--------------

Yosys is also published on PyPI as pyosys_, the official Python binding. Obtaining Yosys through pip would remove the source build and make ``read_verilog`` work for every pip install of ORDeC. This was tried (pyosys 0.69) and rejected for the following reasons:

- **Errors terminate the Python process.** On any error (for example a Verilog syntax error), Yosys calls ``exit()`` inside *libyosys.so*. No Python exception is raised, and ``except BaseException`` does not run. For ``read_verilog``, which runs inside the long-lived ORDeC server, invalid user input would kill the whole session instead of producing a traceback. The pyosys module exposes no hook to change this behaviour.
- **The workaround defeats the purpose.** The only safe way to use pyosys is to run it in a child Python process. At that point, pyosys is no longer used as a Python API, but as a pip-installable Yosys executable with an awkward launcher.
- **No executable, no Tcl.** The wheel contains *libyosys.so*, *yosys-abc* and the techlibs, but no ``yosys`` executable, and the ``tcl`` command is missing. Existing Yosys scripts and notcl-based flows cannot be reused.
- **Process-global side effects.** Importing pyosys sets ``sys.setdlopenflags(RTLD_NOW | RTLD_GLOBAL)`` and loads a 47 MB shared library into the process.
- **Size.** The wheel is about 29 MB to download and 81 MB installed, which is too much for a regular dependency of ORDeC.

The plain ``yosys`` executable has none of these problems: it is a separate process by nature, a failing run surfaces as ``subprocess.CalledProcessError``, and it supports Tcl mode. The cost is a build stage of about three minutes in the base image and three additional runtime packages (*libtcl8.6*, *libreadline8t64*, *libffi8*).

.. _Yosys: https://github.com/YosysHQ/yosys
.. _notcl: https://pypi.org/project/notcl/
.. _pyosys: https://pypi.org/project/pyosys/
