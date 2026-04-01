Web UI
======

Docker-based web UI
-------------------

As mentioned in the Readme, the easiest way to try out ORDeC including its web UI is using Docker::

    docker pull ghcr.io/tub-msc/ordec:latest
    docker run --rm -p 127.0.0.1:8100:8100 -it ghcr.io/tub-msc/ordec:latest

Then, access the web interface via the generated URL and try out examples.

For serious work, you likely want to **use your own local files and text editor** instead of the text editor integrated in the web UI. To do so, you can create an ORD file ``my_design.ord`` (or a Python file ``my_design.py``) and then run the Docker-based web UI in *local mode*::

    docker run --rm -p 127.0.0.1:8100:8100 -v .:/designs -w /designs \
        -it ghcr.io/tub-msc/ordec:latest ordec -l 0.0.0.0 -p 8100 \
        --no-browser --url-authority 127.0.0.1:8100 -m my_design

The web UI will automatically refresh when it detects changes to ``my_design.ord``.

As projects grow, you can split them into multiple files or create a `Python Package <https://docs.python.org/3/tutorial/modules.html#packages>`_, e.g. a folder ``my_design`` containing an ``__init__.py`` file and your other ``.py`` or ``.ord`` files.

Launching the web UI in a custom installation
---------------------------------------------

You can also install ORDeC without Docker, e.g. using the `ORDeC PyPI package <https://pypi.org/project/ordec/>`_ and then launch the web UI using the ``ordec`` command.

.. automodule:: ordec.server

Integrated mode is recommended for demo purposes and getting started. Local mode is likely preferrable for bigger projects.

The mode is selected purely using URL parameters passed the frontend. Every running server supports both integrated and local mode.
``/app.html?example=nand2`` opens example *nand2* in integrated mode.
``/app.html?module=mymodule&view=CellA().schematic`` opens *mymodule* in local mode and shows *CellA().schematic*.

Security
--------

To prevent unauthorized users from gaining access and executing arbitrary code through ORDeC, a new **authentication token** is generated on each start of the `ordec` server (similar to https://jupyter-server.readthedocs.io/en/latest/operators/security.html). This token-based authentication is also important in localhost / single-user setups to prevent privilege escalation. The authentication token is passed to the frontend using the auth= query parameter. From there, it is stored in the browser's localStorage and sent to the server at the start of each websocket connection.

In combination with access to the web server, the authentication token allows executing arbitrary code in the context of the user running ``ordec``. Therefore, the authentication token must be kept secret.

**CSRF protection:** The authentication token empowers the browser to execute arbitrary Python code on the ORDeC server. This opens up some scenarios on which an attacker could execute arbitrary code by linking to a running ORDeC web UI instance. This is a form of cross-site request forgery (CSRF). Links that open the web UI in *integrated mode* are considered safe, as only the predefined and safe examples can be run. However, links that open the web UI in local mode are a potential danger, as they can import (i.e. run) arbitrary locally available Python modules, which is unsafe in itself. Moreover, arbitrary code can be passed and executing through the view name in the URL's query string. To prevent this, in local mode, module and view name must be authenticated using an HMAC-SHA256 code passed through the query string. The authentication token, known to the web UI and the server, is used as shared secret. This HMAC is verified in client-side Javascript, before the websocket connection is established.
