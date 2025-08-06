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

PDK installation
----------------

The **Skywater PDKs** 'sky130A' and 'sky130B' can for example be downloaded using the following shell commands::

    mkdir skywater
    cd skywater
    wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/common.tar.zst"
    echo "c7c155596a1fd1fcf6d5414dfcffcbbcf4e35b2b33160af97f4340e763c97406 common.tar.zst" | sha256sum -c
    wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_pr.tar.zst"
    echo "41dc9098541ed3329eba4ec7f5dfd1422eb09e94b623ea1f6dc3895f9ccebf63 sky130_fd_pr.tar.zst" | sha256sum -c
    tar xf common.tar.zst
    tar xf sky130_fd_pr.tar.zst
    rm common.tar.zst sky130_fd_pr.tar.zst

Then, configure the environment variable ORDEC_PDK_SKY130A to point to the skywater/sky130A directory and the environment variable ORDEC_PDK_SKY130B to point to the skywater/sky130B directory. You can for example do this in your .bashrc or .profile.

The **IHP Open PDK** can be downloaded using the following shell command::

    git clone https://github.com/IHP-GmbH/IHP-Open-PDK.git

The IHP Open PDK includes Verilog-A models, which must be compiled before use using OpenVAF::

    cd IHP-Open-PDK/ihp-sg13g2/libs.tech/verilog-a/
    ./openvaf-compile-va.sh

Then, configure the environment variable ORDEC_PDK_IHP_SG13G2 to point to the IHP-Open-PDK/ihp-sg13g2 directory, for example in your .bashrc or .profile.


Launch webinterface
-------------------

While the Docker-based demo runs using a single web server, it is recommended to use two separate webservers (frontend/backend) during development.

First, launch the frontend (using Vite_)::

    cd web/
    npm install
    npm run dev

:code:`npm install` is only needed at the first launch. In this setup, the Vite frontend server acts as proxy to the backend server on port 8100, which has to be run separately::
    
    ordec-server -b

This will launch a browser and open the ORDeC interface.

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
