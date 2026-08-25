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
path in or out. In the other direction they see just the hub's REST API, which
they need for OAuth and activity reporting: the public proxy binds the hub's
address on the Caddy-facing network instead of every interface, so it is not
exposed to the containers it serves. Per-user CPU and memory caps are enforced
by the kernel, so a runaway simulation burns only its owner's allowance, and an
out-of-memory kill lands inside that user's own VM. Nothing is mounted and nothing persists:
stopping an instance deletes it. The idle culler stops instances after 90
minutes by default, long enough to survive a lunch break.

All containers and the hub share one bridge on that network, which is an
accepted residual risk rather than an oversight. Frames forged inside a guest
do reach the bridge, since Kata's tcfilter networking mirrors between the veth
and the tap without inspecting them; a participant who first wins a
guest-kernel privilege escalation could therefore ARP-spoof the hub's address
and read proxy-to-container traffic, which carries other participants' session
cookies and ORDeC auth tokens. The mitigation would be host-side (a network per
user, static ARP entries or ebtables rules on the bridge), and a per-user
network in particular means restructuring how the hub reaches containers, as
DockerSpawner attaches exactly one. It is accepted because the attack needs
that escalation first, and because the app-layer gate still denies cross-user
access. What does *not* help is hardening inside the guest, such as dropping
``CAP_NET_RAW``: under Kata the guest kernel is conceded by design, so an
attacker who can forge frames at all can also rewrite their own capability
set. The same reasoning is why there is no pids limit; a fork bomb exhausts
only the attacker's own VM. Under ``ORDEC_HUB_RUNTIME=runc`` none of this
holds, which is one more reason that mode is for local testing only.

Rough sizing: about 1.5–2 GB of RAM per participant, and CPU that is bursty
enough to oversubscribe safely. RAM is the binding resource — 80 participants
want something in the region of 256 GB and 32 cores, which is one rented
dedicated machine rather than a cluster.

What ORDeC does differently behind the hub
------------------------------------------

``src/ordec/hub.py`` holds the integration; it uses only the standard library, so
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
    sudo support/hub/deploy/host-setup.sh

    # 2. Images (from the repository root)
    docker build -t ordec .
    docker build -t ordec-hub-user -f support/hub/Dockerfile support/hub/

    # 3. Configuration
    cp support/hub/example.env support/hub/.env
    python3 -c 'import secrets; print(secrets.token_urlsafe(24))'   # per key
    $EDITOR support/hub/.env     # domain, workshop key, admin key, limits

    # 4. Start hub + TLS proxy
    cd support/hub/
    docker compose up -d --build

Participants then browse to ``https://<domain>/``, enter the workshop key (no
username), and land in ORDeC.

The pieces live in ``support/hub/``: ``jupyterhub_config.py`` (authenticator, spawner,
limits, culler — all tunable through ``ORDEC_HUB_*`` variables),
``templates/login.html`` (the key-only login form), ``Dockerfile`` (the user
image, the regular ``ordec`` image with a hub-suitable start command),
``hub.Dockerfile`` (the hub itself), ``docker-compose.yml`` (hub plus Caddy, and
the internal-only user network) and ``deploy/`` (``Caddyfile``,
``host-setup.sh``).

Login and sessions
------------------

There are two ways in, both from the same login page (a small custom
``Authenticator`` in ``jupyterhub_config.py``):

Participants
    Enter only the shared workshop key — no username. Each login mints a fresh
    ``guest-<random>`` identity, and JupyterHub's own session cookie then binds
    that browser to its guest container until logout or culling. So every
    browser gets its own distinct, ephemeral session; a second browser with the
    same key gets a *separate* container.

Admins
    Follow the "Admin login" link (``/hub/login?admin``) to a separate page and
    enter an allowlisted username (``ORDEC_HUB_ADMINS``) plus the separate admin
    key (``ORDEC_HUB_ADMIN_KEY``). Admins land directly on the JupyterHub admin
    panel at ``/hub/admin`` (no ORDeC container is spawned for them), which lists
    every session, shows activity, and can stop or delete servers. For
    live CPU/RAM use ``docker stats`` on the host. Leaving ``ORDEC_HUB_ADMIN_KEY``
    empty disables admin login.

    Admins deliberately cannot *open* a participant's ORDeC UI. The hub does not
    enforce this: its built-in admin role holds ``access:servers`` and cannot be
    narrowed, so the "access server" link does get a valid OAuth grant. ORDeC's
    own user check in ``login_with_code`` (``ordec/hub.py``, commented with the
    reason) is the single guard that refuses it.

    The username is not a credential. ``authenticate`` never lets a caller pick
    an existing guest identity — an empty username always mints a fresh random
    one, and a submitted username only reaches the admin path (which requires
    the admin key) — so knowing a participant's URL-visible ``guest-<random>``
    name does not grant access to their session. Access is gated by the signed
    hub session cookie and per-server OAuth, not the username.

Key strength
    Both keys guard code execution on the host, so generate them
    (``python3 -c 'import secrets; print(secrets.token_urlsafe(24))'``) rather
    than inventing them. The hub refuses to start on the ``example.env``
    placeholders. Entropy is the defense that matters: the login page answers
    guesses from the internet and, since the proxy also listens on the user
    network, from inside every participant container.

    Failed logins are additionally rate-limited per client address (30 at once,
    refilling at 10/min, answered with 429 over budget). Successful logins are
    never charged, so a room sharing one NAT address does not throttle itself.
    This needs the real client address, which is read from the end of the
    ``X-Forwarded-For`` chain, skipping the proxies named by
    ``ORDEC_HUB_TRUSTED_PROXY_IPS`` (docker-compose.yml pins Caddy's address).
    Each hop appends the peer it actually saw, so a client can prepend entries
    but never append one. Tornado's ``request.remote_ip`` is deliberately not
    used: it honours a client-supplied ``X-Real-Ip`` header without any trust
    check, which the Caddyfile therefore also strips.

Ending a session
    The ORDeC toolbar shows an **End session** button in hub mode. It navigates
    to ``/hub/logout``; the hub runs with ``shutdown_on_logout`` so logging out
    also stops the container (which, with the spawner's ``remove=True``, deletes
    it). The backend hands the hub logout URL to the frontend via the
    ``api/token`` response, so it is correct under any hub base URL.

    Guest accounts are genuinely ephemeral. A custom logout handler deletes the
    ``guest-<random>`` account on logout, once its server has stopped, so an
    active "End session" leaves nothing behind. Sessions that are merely
    abandoned (tab closed, no logout) are cleaned up by the idle-culler: after
    ``ORDEC_HUB_IDLE_TIMEOUT`` it stops the idle server and ``--cull-users``
    deletes the now-inactive account. Admin accounts are never auto-deleted.

Moving to institutional or OAuth login is a config change of
``c.JupyterHub.authenticator_class`` — nothing in ORDeC or the spawner setup may
assume the shared-key model.

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
testing without TLS, publish port 8000 of the jupyterhub service, set
``ORDEC_HUB_BIND_IP: 0.0.0.0`` so the proxy listens on every interface rather
than only the one Caddy uses, and browse to ``http://localhost:8000``.

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
