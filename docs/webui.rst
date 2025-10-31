Web UI
======

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

To prevent unauthorized users from gaining access and executing arbitrary code through ORDeC, a new **authentication token** is generated on each start of the `ordec` server (similar to https://jupyter-server.readthedocs.io/en/latest/operators/security.html). This token-based authentication is also important in localhost / single-user setups to prevent privilege escalation. The authentication token is passed to the frontend using the auth= query parameter. From there, it is stored in the browser's localStorage and sent to the server at the start of each websocket connection.

In combination with access to the web server, the authentication token allows executing arbitrary code in the context of the user running ``ordec``. Therefore, the authentication token must be kept secret.

**CSRF protection:** The authentication token empowers the browser to execute arbitrary Python code on the ORDeC server. This opens up some scenarios on which an attacker could execute arbitrary code by linking to a running ORDeC web UI instance. This is a form of cross-site request forgery (CSRF). Links that open the web UI in *integrated mode* are considered safe, as only the predefined and safe examples can be run. However, links that open the web UI in local mode are a potential danger, as they can import (i.e. run) arbitrary locally available Python modules, which is unsafe in itself. Moreover, arbitrary code can be passed and executing through the view name in the URL's query string. To prevent this, in local mode, module and view name must be authenticated using an HMAC-SHA256 code passed through the query string. The authentication token, known to the web UI and the server, is used as shared secret. This HMAC is verified in client-side Javascript, before the websocket connection is established.
