Yosys Integration
=================

ORDeC uses Yosys_ in two places:

- ``ExtLibrary.read_verilog`` (``src/ordec/schematic/verilog_in.py``) runs ``yosys`` to convert a Verilog netlist to Yosys JSON, from which the schematic is built.
- ``tests/test_verilog_in.py`` synthesizes a small counter to IHP SG13G2 standard cells via Yosys Tcl mode (notcl_) and imports the result.

Yosys is optional: the ``yosys`` executable is only needed on ``PATH`` when ``read_verilog`` is called. Tests requiring it carry the pytest marker ``yosys``.

The ordec-base image builds Yosys from source (stage ``ordec-build-yosys`` in *base.Dockerfile*) from the release asset *yosys.tar.gz*, which unlike the tag archive includes the submodules (abc, slang). Debian's packaged Yosys is too old. The ordec image copies the result, so users of the image have ``yosys`` available.

Why not pyosys
--------------

pyosys_, the official PyPI binding, was tried (0.69) and rejected:

- On any error (e.g. a Verilog syntax error), Yosys calls ``exit()`` inside *libyosys.so*. No Python exception is raised, so invalid input would kill the ORDeC server.
- The only safe way to use pyosys is therefore from a separate Python process. This defeats the purpose: pyosys would no longer be used as a Python API, but as a pip-installed Yosys executable with an awkward launcher.
- The wheel has no ``yosys`` executable and no ``tcl`` command, so existing Yosys scripts and notcl flows cannot be reused.
- Importing it has process-global side effects: it calls ``sys.setdlopenflags(RTLD_NOW | RTLD_GLOBAL)``, affecting all subsequently loaded extension modules, and loads a 47 MB shared library. The wheel is 81 MB installed.

The plain ``yosys`` executable avoids all of this: errors surface as ``subprocess.CalledProcessError`` and Tcl mode is available.

.. _Yosys: https://github.com/YosysHQ/yosys
.. _notcl: https://pypi.org/project/notcl/
.. _pyosys: https://pypi.org/project/pyosys/
