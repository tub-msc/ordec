.. _getting_started:

Getting Started
===============

Try it out (using Docker)
-------------------------

The easiest way to get started is via Docker::

    docker run --rm -p 127.0.0.1:8100:8100 -it ghcr.io/tub-msc/ordec:latest

Then, visit http://localhost:8100 for the web interface and examples.

.. warning::

    Potential security risk: The web server that is launched allows execution of arbitrary Python code in the Docker container without authentication. For this reason, the setup above only listens on localhost.

Details on how the Docker image is built are found in :ref:`containers_and_ci`.

Development setup (without Docker)
----------------------------------

For development, it is recommended not to use Docker. The setup below is tested with Debian 12.

- Install required packages: :code:`sudo apt-get install libcairo2-dev build-essential fonts-inconsolata libgirepository1.0-dev gir1.2-pango-1.0 ngspice npm`
- For development, install the Python package ordec: :code:`pip3 install -e .`
- Additional dependencies for building the documentation: Jupyter notebooks, Jupytext_, sphinx, sphinx_rtd_theme and myst-nb_.
- Additional dependencies for running tests: pytest and pytest-cov.

Notes:

- The cairo/pycairo dependency has been found to cause trouble in some cases. It might help to install an old version: :code:`pip install PyGObject==3.42.2`. Also, possibly the following helps: :code:`libcairo2-dev libxt-dev libgirepository1.0-dev`. In the medium term, it is planned to get rid of the cairo dependency. 
- The aim is to keep dependencies low and ensure that all used packages are reliable. Currently, myst-nb seems like the largest dependency, but it is only relevant for the documentation and presentation, not for the core components themselves.
- In case of setup problems, *base.Dockerfile* and *Dockerfile* might offer some hints (see :ref:`containers_and_ci`).

.. _Jupytext: https://jupytext.readthedocs.io/
.. _myst-nb: https://myst-nb.readthedocs.io/

Launch webinterface
^^^^^^^^^^^^^^^^^^^

While the Docker-based demo runs using a single web server, it is recommended to use two separate webservers (frontend/backend) during development.

The backend server provides a websocket interface to the Python-based ORDeC core. To launch this websocket server at port 8100, simply run::
    
    ordec-server

.. warning::

    Potential security risk: This web server allows execution of arbitrary Python code without authentication. By default, it only listens on localhost.

The frontend server must be launched separately::

    cd web/
    npm install
    npm run dev

:code:`npm install` is only needed at the first launch. You can then access the webinterface at http://localhost:5173. In this setup, the frontend automatically connects to the backend on localhost port 8100 via websocket.

Run tests
^^^^^^^^^

Automated testing is very important – not only to verify new features, but also to ensure that source code changes do not break existing functionality. Tun run all tests, execute :code:`pytest-3` in the repository's root directory.

Use with Jupyter
^^^^^^^^^^^^^^^^

ORDeC also has some level of Jupyter integration. The provided Jupyter notebooks are in Jupytext_ format. In contrast to th default "ipynb" format, the jupytext files show up nicely in version control and prevent that cached Jupyter results fill up and add noise to the version history.

After installing Jupytext_, you can open and run the notebook **examples/JupyterExample.py** in Jupyter to see a minimal example.
