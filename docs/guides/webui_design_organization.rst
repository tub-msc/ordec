Using the web UI and organizing designs
=======================================

This page explains how to use ORDeC's web UI and how to organize the source code of designs created with ORDeC.

Depending on the scope of your project and your Python expertise, chose  one of the following three recommended ways of managing sources:

1. **Beginner:** integrated mode: the code is edited in the web UI's built-in
   editor and is not saved to disk. Good for getting acquainted with ORDeC,
   trying out the examples and quick experiments. Move on when you want to keep
   your work or use more than one file.
2. **Intermediate:** local mode: ``.ord`` / ``.py`` files on your disk, edited
   with your own text editor; the web UI reloads on save. Good for individual
   designs and small projects with a few files. Move on when your files need to
   import each other in a structured way, or when you want version control.
3. **Expert:** design as Python project: a Python package (directory tree) of
   ``.ord`` / ``.py`` files, managed with Git. Good for larger designs, shared
   work and reuse across projects.

.. note::

   **Python background:** ORD is a superset of Python (see :ref:`ord_tutorial`, section *Python support*), and ORDeC reuses Python's mechanisms for organizing code. The Python terms you need to know about are:

   * A **module** is a single source file, ``foo.py`` or ``foo.ord``. Other files use it through ``import foo`` or ``from foo import MyCell``.
   * A **package** is a directory containing a file ``__init__.py`` (which may be empty) plus further modules or sub-packages. ``pkg/cells/inv.ord`` is imported as ``pkg.cells.inv``.
   * A **relative import** such as ``from .inv import Inv`` or ``from ..cells import Inv`` refers to modules by their position relative to the importing module within the same package, instead of by their full name.

   The `Python tutorial on modules and packages <https://docs.python.org/3/tutorial/modules.html>`_ explains these in more detail.

Beginner: integrated mode
-------------------------

The easiest way to try out ORDeC and it's web UI is using the **Docker image**. A **local installation** outside of a container is also possible, but requires you to install a number of dependencies by hand.

.. tab-set::

   .. tab-item:: Docker
      :sync: docker

      ::

          docker pull ghcr.io/tub-msc/ordec:latest
          docker run --rm -p 127.0.0.1:8100:8100 -it ghcr.io/tub-msc/ordec:latest

   .. tab-item:: Local installation
      :sync: local

      For a local installation, you need to set up Ngspice (for simulation), KLayout (for layout viewing) and the PDKs separately. :ref:`dev_setup` describes the PDK installation and the environment variables that point ORDeC to the PDKs.

      Install ORDeC from `PyPI <https://pypi.org/project/ordec/>`_ and start the web UI::

          pip install ordec
          ordec


Then, access the web interface via the generated URL and try out the examples.

The examples open in *integrated mode*: the source code is edited in the web UI's built-in editor and the design is rebuilt on every change. It is what you get when ``ordec`` is started without arguments.

Integrated mode is meant for getting to know the software: **the entered source code is not saved anywhere**. Copy and paste anything you want to keep into a local file. It is also limited to a single source file, so it does not scale to larger designs.

Intermediate: local mode
------------------------

In local mode, your design is stored in files on the local file system and edited with a text editor of your choice (see :doc:`editor_support` for syntax highlighting and language server setup). The web UI watches the files and rebuilds the design when they change.

Create a file ``my_design.ord`` (or ``my_design.py``) and open it:

.. tab-set::

   .. tab-item:: Docker
      :sync: docker

      ::

          docker run --rm -p 127.0.0.1:8100:8100 -v .:/designs -w /designs \
              -it ghcr.io/tub-msc/ordec:latest ordec -l 0.0.0.0 -p 8100 \
              --no-browser --url-authority 127.0.0.1:8100 my_design.ord

      ``-v .:/designs -w /designs`` mounts the current directory into the container. The remaining options make the web UI inside the container reachable from the browser outside of it. All ``ordec`` examples below work the same way: replace ``my_design.ord`` by the respective arguments.

   .. tab-item:: Local installation
      :sync: local

      ::

          ordec my_design.ord

This starts the web UI with the views of ``my_design.ord`` available for selection. ``--view`` / ``-e`` preselects views, each in its own result viewer:

.. tab-set::

   .. tab-item:: Docker
      :sync: docker

      ::

          docker run --rm -p 127.0.0.1:8100:8100 -v .:/designs -w /designs \
              -it ghcr.io/tub-msc/ordec:latest ordec -l 0.0.0.0 -p 8100 \
              --no-browser --url-authority 127.0.0.1:8100 \
              my_design.ord -e "MyCell().schematic" -e "MyCell().symbol"

   .. tab-item:: Local installation
      :sync: local

      ::

          ordec my_design.ord -e "MyCell().schematic" -e "MyCell().symbol"

Splitting a design into several files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Local mode is not limited to a single file. ``.ord`` files are imported exactly like ``.py`` files (see :ref:`ord_importing`), so a design can be split into several modules that import each other with ordinary Python imports: ``.ord`` importing ``.py``, ``.py`` importing ``.ord``, or any mix of the two:

.. code-block:: text

    # inv.ord
    from ordec.lib.generic_mos import Nmos, Pmos

    cell Inv:
        ...

.. code-block:: text

    # tb_inv.ord
    from inv import Inv

    cell TbInv:
        ...

``ordec tb_inv.ord`` opens the testbench. Like ``python tb_inv.py``, the file's directory is put first on ``sys.path``, which is what makes ``from inv import Inv`` work. Changes to *any* file that was imported while building the design (not only the one passed on the command line) trigger a rebuild.

Two details to keep in mind:

* If ``foo.py`` and ``foo.ord`` exist in the same directory, ``import foo`` picks ``foo.py``.
* The ``.ord`` importer is activated by the ``ordec`` command. In a standalone Python script or a Jupyter notebook, activate it with ``import ordec.importer`` before importing ``.ord`` modules.

Expert: the design as a Python project
--------------------------------------

Once a design consists of more than a handful of files, organize it as a Python package. This gives you a namespace for your cells, relative imports between modules, and a directory tree that works well with Git or other version control systems. A typical layout:

.. code-block:: text

    myproject/
    ├── __init__.py          # empty; marks the directory as a package
    ├── cells/
    │   ├── __init__.py
    │   ├── inv.ord
    │   └── nand2.ord
    ├── testbenches/
    │   ├── __init__.py
    │   └── tb_inv.ord
    └── helpers.py           # plain Python code shared by the cells

The ``__init__.py`` files may also be written in ORD as ``__init__.ord``. Inside the package, modules refer to each other either by absolute name or by relative import:

.. code-block:: text

    # myproject/testbenches/tb_inv.ord
    from myproject.cells.inv import Inv     # absolute import
    from ..cells.inv import Inv             # relative import, equivalent

Open modules of a package with ``-m``, from the directory that contains ``myproject/``:

.. tab-set::

   .. tab-item:: Docker
      :sync: docker

      ::

          docker run --rm -p 127.0.0.1:8100:8100 -v .:/designs -w /designs \
              -it ghcr.io/tub-msc/ordec:latest ordec -l 0.0.0.0 -p 8100 \
              --no-browser --url-authority 127.0.0.1:8100 \
              -m myproject.testbenches.tb_inv -e "TbInv().sim_dc"

   .. tab-item:: Local installation
      :sync: local

      ::

          ordec -m myproject.testbenches.tb_inv -e "TbInv().sim_dc"

This mirrors ``python -m``: the current directory is put first on ``sys.path`` and the module is imported *as part of its package*, so relative imports work. Passing the file path instead (``ordec myproject/testbenches/tb_inv.ord``) opens it like ``python myproject/testbenches/tb_inv.py``, without package context, and relative imports fail with ``ImportError: attempted relative import with no known parent package``. Passing the package directory itself (``ordec myproject/``) opens its ``__init__`` module.

Beyond that, everything that applies to Python projects applies to ORDeC projects: for example, a ``pyproject.toml`` makes the project installable (``pip install -e .``) so it can be imported from anywhere and reused by other projects, and tests of your cells and views can be written with ``pytest``.

Command line reference
----------------------

.. automodule:: ordec.server

Details of the web UI's client-server protocol, URL parameters and security model are described in :doc:`/dev/webui`.
