Web UI: ``ordec-server``
========================

.. automodule:: ordec.server

Integrated mode is recommended for demo purposes and getting started. Local mode is likely preferrable for bigger projects.

The mode is selected purely using URL parameters passed the frontend. Every running server supports both integrated and local mode.
``/app.html?example=nand2`` opens example *nand2* in integrated mode.
``/app.html?module=mymodule&view=CellA().schematic`` opens *mymodule* in local mode and shows *CellA().schematic*.

.. note::

  The Docker image mainly supports integrated mode. Local mode would require
  additional setup, as the container's file system is separate from the host's
  file system.

Security
--------

To prevent unauthorized users from gaining access and executing arbitrary code through ORDeC, a new authentication token is generated on each start of ordec-server (similar to https://jupyter-server.readthedocs.io/en/latest/operators/security.html). This token-based authentication is also important in localhost / single-user setups to prevent privilege escalation. The authentication token is passed to the frontend using the auth= query parameter. From there, it is stored as a cookie and sent to the server at the start of each websocket connection.

In combination with access to the web server, the authentication token allows executing arbitrary code in the context of the user running ``ordec-server``. Therefore, the authentication token must be kept secret.
