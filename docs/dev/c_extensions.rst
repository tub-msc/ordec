C extensions
============

The ordec package contains two C extensions, both defined in ``setup.py``:

- :mod:`ordec.core.ordb._ordb`: the ORDB core (see :doc:`ordb_core`),
  sources in ``src/ordec/core/ordb/native/``. It is required; there is no
  pure-Python fallback.
- :mod:`ordec.layout._gdsrecords`: GDS record scanning, source
  ``src/ordec/layout/_gdsrecords.c``. It is optional: if it cannot be built,
  :mod:`ordec.layout.gdsrecords` falls back to an equivalent, but much slower
  pure-Python implementation.

Building
--------

Building requires a C compiler and the Python headers (on Debian:
``sudo apt-get install build-essential python3-dev``).

``pip3 install -e .[test]`` builds both extensions into the source tree
(``src/ordec/core/ordb/_ordb.abi3.so``, ``src/ordec/layout/_gdsrecords.abi3.so``).
After changing the C sources, or after pulling changes to them, run the same
command again. For a quick rebuild during development,
``python3 setup.py build_ext --inplace`` does the same if setuptools is
installed.

A missing or failed build of the ORDB core shows up on import as::

    ImportError: cannot import name '_ordb' from partially initialized module 'ordec.core.ordb'

Limited API
-----------

Both extensions use only the limited API of Python 3.11 (``Py_LIMITED_API``
in the sources), so one abi3 build serves all Python versions from 3.11.
The limited API has no static types, no access to type object fields and no
macros like ``PyTuple_GET_ITEM``: the types are heap types created with
``PyType_FromSpec``, and the function forms of the macros cost 2 to 3% on
the ORDB benchmarks. A version-specific build left in the source tree
(``_ordb.cpython-313-*.so``) is imported in preference to the abi3 one;
delete it after switching.
