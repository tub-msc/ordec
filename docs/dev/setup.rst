.. _dev_setup:

Development setup
=================

The Docker container (see Readme) is the easiest way to try out ORDeC. Details on how the Docker image is built are found in :ref:`containers_and_ci`.

For development, it is recommended not to use Docker. The setup below is tested with Debian 12.

- Install required packages: :code:`sudo apt-get install ngspice npm python3 chromium-driver jupyter-notebook`
- Install the Python ordec package in editable/"develop" mode: :code:`pip3 install -e .\[test\]`
- Install additional dependencies for building the documentation: :code:`pip3 install -r docs/requirements.txt`

.. note::

  In case of setup problems, *base.Dockerfile* and *Dockerfile* might offer some hints (see :ref:`containers_and_ci`).

Launch webinterface
-------------------

While the Docker-based demo runs using a single web server, it is recommended to use two separate webservers (frontend/backend) during development.

First, launch the frontend (Vite_)::

    cd web/
    npm install
    npm run dev

:code:`npm install` is only needed at the first launch. You can then access the webinterface at http://localhost:5173. In this setup, the frontend automatically connects to the backend on localhost port 8100 via websocket.

The backend server provides a websocket interface to the Python-based ORDeC core. To launch the backend, simply run::
    
    ordec-server -n

Then, navigate to the provided URL. The URL includes an authentication token to prevent unauthorized users from gaining access and executing arbitrary code through ORDeC (similar to https://jupyter-server.readthedocs.io/en/latest/operators/security.html). This token-based authentication is also important in a localhost / single-user setup to prevent privilege escalation.

Run tests
---------

Automated testing is very important – not only to verify new features, but also to ensure that source code changes do not break existing functionality. Tun run all tests, execute :code:`pytest-3` in the repository's root directory.

Use with Jupyter
----------------

ORDeC also has some level of Jupyter integration. The provided Jupyter notebooks are in Jupytext_ format. In contrast to th default "ipynb" format, the jupytext files show up nicely in version control and prevent that cached Jupyter results fill up and add noise to the version history.

After installing Jupytext_, you can open and run the notebook **examples/JupyterExample.py** in Jupyter to see a minimal example.


.. _Jupytext: https://jupytext.readthedocs.io/
.. _myst-nb: https://myst-nb.readthedocs.io/
.. _Vite: https://vite.dev/
