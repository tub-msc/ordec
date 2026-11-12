.. _dev_setup:

Development setup
=================

To just try out ORDeC, the Docker image or ``nix run`` from the Readme is enough. This page sets up a repository checkout for development.

.. _nix_setup:

Setup with Nix (recommended)
----------------------------

*flake.nix* provides everything needed for development: Ngspice, KLayout, Yosys, OpenVAF (as ``openvaf-r``), the PDKs (SKY130, IHP-Open-PDK with compiled Verilog-A models), the Python packages including those for building the documentation, Graphviz, Node.js and Chromium. *flake.lock* pins their versions, so you get the same as the Docker image and the automated tests. It supports x86_64 Linux, including WSL2 on Windows.

1. `Install Nix <https://nixos.org/download>`_.
2. Enable flakes and the binary cache of ORDeC in */etc/nix/nix.conf* (or *~/.config/nix/nix.conf* with a single-user installation)::

       experimental-features = nix-command flakes
       extra-substituters = https://ordec.cachix.org
       extra-trusted-public-keys = ordec.cachix.org-1:vYjSnOZ3z10QWY3r6xEHibmzSXvCVsSwcLN7UmxbgbQ=

   Then restart the Nix daemon: ``sudo systemctl restart nix-daemon``. Without the cache, the first build takes one to two hours.
3. In the repository root, enter the development shell and install the frontend dependencies::

       nix develop
       (cd web && npm ci)

The shell sets the ``ORDEC_PDK_*`` variables and activates the venv *.venv* in the repository root, which has ORDeC installed in editable mode. The venv is set up on first use and again whenever the Python packages from Nix change; anything you install into it with pip is lost then.

.. _manual_setup:

Manual setup
------------

Without Nix, install the dependencies yourself. The commands below are for Debian.

- Install the distribution packages: ``sudo apt-get install ngspice npm python3 python3-dev build-essential chromium-driver``
- Install KLayout, and optionally Yosys (see :doc:`yosys`) and OpenVAF (needed to compile the IHP models, see below). Debian's packages of these are too old or missing; *flake.nix* lists the versions in use.
- Install ORDeC in editable mode: ``pip3 install -e .[test]``. This also builds the C extensions (see :doc:`c_extensions`).
- For building the documentation: ``pip3 install -r docs/requirements.txt`` and Graphviz (``sudo apt-get install graphviz``)

The **SKY130 PDKs** 'sky130A' and 'sky130B' can be downloaded as follows::

    mkdir skywater
    cd skywater
    wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/common.tar.zst"
    echo "c7c155596a1fd1fcf6d5414dfcffcbbcf4e35b2b33160af97f4340e763c97406 common.tar.zst" | sha256sum -c
    wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_pr.tar.zst"
    echo "41dc9098541ed3329eba4ec7f5dfd1422eb09e94b623ea1f6dc3895f9ccebf63 sky130_fd_pr.tar.zst" | sha256sum -c
    tar xf common.tar.zst
    tar xf sky130_fd_pr.tar.zst
    rm common.tar.zst sky130_fd_pr.tar.zst

Point the environment variables ``ORDEC_PDK_SKY130A`` and ``ORDEC_PDK_SKY130B`` to the *skywater/sky130A* and *skywater/sky130B* directories, for example in your *.bashrc* or *.profile*.

The **IHP Open PDK** is cloned with its submodules, which include the PCell support needed by ``tests/test_ihp130_pcells.py``. Its Verilog-A models must then be compiled with OpenVAF::

    git clone --recurse-submodules https://github.com/IHP-GmbH/IHP-Open-PDK.git
    cd IHP-Open-PDK/ihp-sg13g2/libs.tech/verilog-a/
    ./openvaf-compile-va.sh

Point ``ORDEC_PDK_IHP_SG13G2`` to the *IHP-Open-PDK/ihp-sg13g2* directory. Tests requiring this PDK carry the pytest marker ``ihp130``; ``pytest -m "not ihp130"`` runs the rest without it.


Launch webinterface
-------------------

There are three setups to run the ``ordec`` web UI:

1. **Combined frontend + backend server with regular installation:** A regular installation of ORDeC (with Nix, from PyPI or in the Docker image) includes a compiled version of the frontend (*webdist.tar*). In this case, ORDeC is started through a simple ``ordec``. This is the setup for users; see :doc:`/guides/webui_design_organization`.
2. **Editable installation:** An editable installation ("develop mode", ``pip install -e``, as in the development shell) lacks *webdist.tar*. Instead, ``ordec`` runs the Vite_ dev server of the checkout's *web/* directory (*web/dev-server.mjs*) as child process, listening on a Unix domain socket. ``ordec`` forwards static file requests and the websocket connections of Vite's hot module replacement (HMR) client to it. The browser uses the usual URL of ``ordec`` only, and frontend changes show up instantly. Of Vite's output, only warnings and errors are shown, prefixed with ``vite:``. The frontend dependencies must be installed once through ``npm ci`` in the *web/* directory.
3. **Separate frontend + backend server (fallback):** If the Vite integration of setup 2 fails, e.g. after a Vite upgrade, ``npm run dev`` in *web/* starts Vite on its own (port 5173), which acts as proxy to the backend started by ``ordec -b`` (port 8100). Use the browser only to connect to the Vite server / port.

Run tests
---------

Automated testing is very important: not only to verify new features, but also to ensure that source code changes do not break existing functionality. To run all tests, execute :code:`pytest` in the repository's root directory.

The tests run in parallel by default (pytest-xdist, up to 8 workers, see *tests/conftest.py*). Pass :code:`-n 0` to run them serially, e.g. for debugging.

Coverage measurement is off by default, as it slows down the test run noticeably. To measure it, pass the pytest-cov options explicitly, e.g.::

    pytest --cov=ordec --cov-report=html

The HTML report is written to *htmlcov/*.

Use with Jupyter
----------------

ORDeC also has some level of Jupyter integration. The provided Jupyter notebooks are in Jupytext_ format. In contrast to th default "ipynb" format, the jupytext files show up nicely in version control and prevent that cached Jupyter results fill up and add noise to the version history.

After installing Jupytext_, you can open and run the notebook **support/jupyter/JupyterExample.py** in Jupyter to see a minimal example.


.. _Jupytext: https://jupytext.readthedocs.io/
.. _myst-nb: https://myst-nb.readthedocs.io/
.. _Vite: https://vite.dev/
