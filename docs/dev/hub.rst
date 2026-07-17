ORDeC Hub
=========

ORDeC Hub runs ORDeC for workshop participants: everyone gets their own
ephemeral, isolated instance in the browser, with nothing to install.

The reason it exists is that ORDeC executes arbitrary code by design — an ORD
design *is* a program, and running it is the whole point. A single shared
server is therefore not an option: one participant could read another's work,
or the host. Each participant needs a sandbox of their own, and something has
to hand those out, log people in, and clean up afterwards. That is what the hub
does. Only integrated mode is available behind it; local mode (``-m``) is
disabled, so no participant code touches a filesystem that outlives the
session.

How it works
------------

The hub is JupyterHub, which despite the name has nothing to do with Jupyter:
it is a generic "authenticate a user, spawn a single-user web service, proxy to
it" platform. It was built for exactly this threat model — Jupyter, like ORDeC,
runs untrusted code as a feature — and brings a login page, a spawner, a
reverse proxy, an admin panel and an idle culler. Participants see it only at
login; afterwards they are redirected straight into the ORDeC UI at
``/user/<name>/``.

Each instance is a Docker container run under the `Kata Containers
<https://katacontainers.io/>`_ runtime, which starts it inside a lightweight
KVM virtual machine with its own guest kernel. That is the point: plain
containers share the host kernel, so a kernel bug is a host compromise, whereas
Kata puts a hardware boundary in the way while still being an ordinary OCI
container to build and spawn. The host must therefore expose ``/dev/kvm``,
which dedicated servers do and most budget cloud VMs do not.

The containers sit on an ``internal: true`` Docker network, so they have no
NAT, no DNS and no egress — the hub proxy reaching the ORDeC port is the only
path in or out. Per-user CPU and memory caps are enforced by the kernel, so a
runaway simulation burns only its owner's allowance, and an out-of-memory kill
lands inside that user's own VM. Nothing is mounted and nothing persists:
stopping an instance deletes it. The idle culler stops instances after 90
minutes by default, long enough to survive a lunch break.

Rough sizing: about 1.5–2 GB of RAM per participant, and CPU that is bursty
enough to oversubscribe safely. RAM is the binding resource — 80 participants
want something in the region of 256 GB and 32 cores, which is one rented
dedicated machine rather than a cluster.

What ORDeC does differently behind the hub
------------------------------------------

``ordec/hub.py`` holds the integration; it uses only the standard library, so
the user image does not depend on JupyterHub. It activates automatically when
the ``JUPYTERHUB_SERVICE_PREFIX`` and ``JUPYTERHUB_API_TOKEN`` environment
variables are present.

Serving under a path prefix
    JupyterHub's proxy forwards ``/user/<name>/...`` without stripping the
    prefix, so the server strips it before matching routes and answers 404
    outside it. The frontend keeps every URL relative — websocket, fetches,
    links, and Vite's ``base: './'`` — so the built assets contain no absolute
    paths. This is also available standalone via ``ordec --base-url /pfx/``.

Authenticating against the hub
    A full OAuth flow: authorize redirect with a state cookie, code exchange,
    and a check that the user is the one this instance was spawned for. The
    resulting session cookie is scoped to the prefix. Everything is gated,
    including the websocket handshake; unauthenticated API calls get 401 while
    page navigations get the redirect. The frontend then fetches ORDeC's own
    auth token from the cookie-gated ``api/token`` endpoint instead of reading
    it from the URL fragment, so the per-session token auth stays intact
    underneath.

Reporting activity
    Every websocket message updates a last-activity timestamp, which a
    reporter thread POSTs to the hub every five minutes. Without it the culler
    would see a long-lived idle websocket as activity and keep dead sessions
    alive; with it, an open-but-forgotten tab is culled while real use never
    is.

Surviving a cull
    When the websocket cannot connect and ORDeC knows it is hub-hosted, the
    frontend offers to restart the session: it stashes the editor source in
    ``sessionStorage``, reloads through the hub — which respawns the instance —
    and restores the source.

Deployment
----------

Needs a KVM-capable Linux host (check with ``ls /dev/kvm``) and a DNS record
for the workshop hostname; Caddy fetches Let's Encrypt certificates by itself.

.. code-block:: sh

    # 1. Host: Docker + Kata Containers + smoke test (review this first!)
    sudo hub/deploy/host-setup.sh

    # 2. Images (from the repository root)
    docker build -t ordec .
    docker build -t ordec-hub-user -f hub/Dockerfile hub/

    # 3. Configuration
    cp hub/example.env hub/.env
    $EDITOR hub/.env     # domain, workshop key, limits

    # 4. Start hub + TLS proxy
    cd hub/
    docker compose up -d --build

Participants then browse to ``https://<domain>/``, log in with any username and
the workshop key, and land in ORDeC.

The pieces live in ``hub/``: ``jupyterhub_config.py`` (authenticator, spawner,
limits, culler — all tunable through ``ORDEC_HUB_*`` variables),
``Dockerfile`` (the user image, the regular ``ordec`` image with a hub-suitable
start command), ``hub.Dockerfile`` (the hub itself), ``docker-compose.yml``
(hub plus Caddy, and the internal-only user network) and ``deploy/``
(``Caddyfile``, ``host-setup.sh``).

Authentication is a shared workshop key (JupyterHub's DummyAuthenticator),
rotated per workshop. Moving to institutional or OAuth login is a config change
— ``c.JupyterHub.authenticator_class`` — so nothing in ORDeC or the spawner
setup may assume the shared-key model.

Security checklist
------------------

Worth verifying on the deployed host, since most of this cannot be tested
anywhere else:

1. **Kata is really active**: ``docker run --rm --runtime
   io.containerd.kata.v2 alpine uname -r`` must report a *different* kernel
   than the host. ``host-setup.sh`` checks this.
2. **No egress from user containers**: from inside a spawned container,
   external connections and DNS lookups must fail.
3. **Cross-user access is denied**: another user's ``/user/<name>/api/version``
   must answer 401 without their session cookie. ``tests/test_hub.py`` covers
   this, but re-check it deployed.
4. **Idle culling works**: leave an instance idle past
   ``ORDEC_HUB_IDLE_TIMEOUT`` and watch the container disappear.

Local testing without KVM
-------------------------

Setting ``ORDEC_HUB_RUNTIME=runc`` in ``.env`` runs the whole flow with plain
containers, which is useful on a laptop and must never be used for a real
workshop: it is the shared-kernel isolation that Kata exists to avoid. For
testing without TLS, publish port 8000 of the jupyterhub service and use
``http://localhost:8000``.

To exercise the full path through Caddy on a development host that has no
domain and no certificate, point ``ORDEC_HUB_DOMAIN`` at an ``http://`` address
instead: Caddy only fetches a certificate when the site address is a bare
hostname, and serves plain HTTP when the scheme is explicit.

.. code-block:: sh

    ORDEC_HUB_DOMAIN=http://devhost.local   # or ':80' to match any host / a bare IP

Participants — and the OAuth redirects — then use ``http://<host>/``. ORDeC's
session cookies drop their ``Secure`` flag automatically in this case, since
they follow the ``X-Forwarded-Proto`` that Caddy sends. This is for development
only: without TLS the workshop key and every session cookie cross the network
in the clear.
