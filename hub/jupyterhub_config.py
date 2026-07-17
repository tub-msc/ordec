# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
JupyterHub configuration for ORDeC Hub workshop deployments.

See docs/dev/hub.rst for the architecture and deployment steps. Tunables come
from environment variables (ORDEC_HUB_*), see hub/example.env.
"""

import os
import secrets
import sys

from jupyterhub.auth import Authenticator
from jupyterhub.handlers.login import LoginHandler
from jupyterhub.utils import url_path_join

c = get_config()  # noqa

# --- Persistent state ------------------------------------------------------
# The jupyterhub-data volume is mounted at /srv/jupyterhub/data (see
# docker-compose.yml), not over /srv/jupyterhub, so it does not shadow the
# baked config and templates. Keep the DB and cookie secret on that volume so
# they still survive restarts.
c.JupyterHub.db_url = 'sqlite:////srv/jupyterhub/data/jupyterhub.sqlite'
c.JupyterHub.cookie_secret_file = '/srv/jupyterhub/data/jupyterhub_cookie_secret'

# --- Authentication -------------------------------------------------------
# Two separate login pages, one authenticator:
#   - /hub/login : participants enter only the shared workshop key (no
#     username). Each login mints a fresh 'guest-<random>' identity; JupyterHub's
#     own session cookie then binds that browser to its guest container until
#     logout/cull, so every browser gets its own distinct, ephemeral session.
#   - /hub/login?admin : admins enter an allowlisted username plus the separate
#     admin key, which grants the JupyterHub admin panel.
# The username is NOT a credential: authenticate() never lets a caller choose an
# existing guest name (an empty username always mints a fresh random one, and a
# submitted username only reaches the admin path, which requires the admin key).
# Knowing someone's guest-<random> name therefore does not grant access to their
# session — access is gated by the signed hub session cookie and per-server
# OAuth, not by the (URL-visible) username.
# Swapping to institutional/OAuth login is a pure config change of
# c.JupyterHub.authenticator_class (requires oauthenticator in the hub image).
class ORDeCWorkshopAuthenticator(Authenticator):
    workshop_key = os.environ['ORDEC_HUB_WORKSHOP_KEY']
    admin_key = os.environ.get('ORDEC_HUB_ADMIN_KEY', '')
    admin_users_allowed = frozenset(
        filter(None, os.environ.get('ORDEC_HUB_ADMINS', '').split(',')))

    async def authenticate(self, handler, data):
        username = data.get('username', '').strip()
        key = data.get('password', '')
        if username:
            # Admin path: allowlisted name + admin key.
            if (self.admin_key and username in self.admin_users_allowed
                    and secrets.compare_digest(key, self.admin_key)):
                return {'name': username, 'admin': True}
            return None
        # Guest path: workshop key only, unique ephemeral identity per login.
        if secrets.compare_digest(key, self.workshop_key):
            return {'name': 'guest-' + secrets.token_hex(6), 'admin': False}
        return None

    def get_handlers(self, app):
        return [('/login', ORDeCLoginHandler)]

# Selects the admin vs. workshop view of the shared login template. The default
# view is the key-only workshop page; the admin view (username + admin key) shows
# at /hub/login?admin, and also when re-rendering after a failed admin login
# (which submits a non-empty username).
class ORDeCLoginHandler(LoginHandler):
    def _render(self, login_error=None, username=None, **kwargs):
        admin_login = (self.get_argument('admin', default=None) is not None
            or bool((username or '').strip()))
        # The hub's default failure message ("Invalid username or password")
        # makes no sense on the username-less workshop page; keep it for admins.
        if login_error and not admin_login:
            login_error = 'Invalid workshop key.'
        return super()._render(login_error=login_error, username=username,
            admin_login=admin_login, **kwargs)

    def get_next_url(self, user=None, default=None):
        # Admins log in to oversee, not to code: send them to the admin panel
        # instead of spawning them an ORDeC container. An explicit ?next= (or a
        # non-admin user) falls through to the default (their own server).
        if (user is not None and user.admin
                and not self.get_argument('next', default='')):
            return url_path_join(self.hub.base_url, 'admin')
        return super().get_next_url(user, default=default)

c.JupyterHub.authenticator_class = ORDeCWorkshopAuthenticator
# We mint guest names ourselves and gate admins in authenticate(), so every
# name returned above is already authorized:
c.Authenticator.allow_all = True

# --- Login form / logout ---------------------------------------------------
# Custom login.html (see hub/templates/) renders the workshop-key page by
# default and the admin page when ORDeCLoginHandler sets admin_login. It is
# styled to match ORDeC's landing page and shows the logo served at
# {base_url}logo from this file:
c.JupyterHub.template_paths = ['/srv/jupyterhub/templates']
c.JupyterHub.logo_file = '/srv/jupyterhub/ordec_logo.svg'
# "End session" in the ORDeC UI navigates to /hub/logout; stop the container too
# so logging out fully ends the ephemeral session (spawner has remove=True).
c.JupyterHub.shutdown_on_logout = True

# --- Spawner: one Docker container per user, Kata (KVM) runtime -----------
c.JupyterHub.spawner_class = 'dockerspawner.DockerSpawner'
c.DockerSpawner.image = os.environ.get('ORDEC_HUB_IMAGE', 'ordec-hub-user')

c.DockerSpawner.extra_host_config = {
    # Hardware isolation boundary: each container runs in its own KVM VM
    # with its own guest kernel. Set ORDEC_HUB_RUNTIME=runc to fall back to
    # plain containers for local testing without KVM (NOT for production).
    'runtime': os.environ.get('ORDEC_HUB_RUNTIME', 'io.containerd.kata.v2'),
    # A user filling the disk only fills a bounded tmpfs, and container
    # writes cannot grow the image layer without bound:
    'tmpfs': {'/tmp': 'size=256m'},
    # Even on an internal network, Docker's embedded DNS (127.0.0.11) still
    # forwards external lookups through the host, a potential DNS covert
    # channel. Pointing the resolver at 127.0.0.1 (nothing listens there)
    # disables DNS entirely. This also breaks container-name resolution, so
    # ORDeC cannot reach the hub API by name: the hub is instead pinned to a
    # static IP on the users network and ORDEC_HUB_CONNECT_IP references it by
    # address (see docker-compose.yml).
    'dns': ['127.0.0.1'],
}

# The ordec image serves on port 8100 and detects the hub through the
# JUPYTERHUB_* environment (see ordec/hub.py). Do not add jupyterhub to the
# user image; the integration is stdlib-only.
c.DockerSpawner.port = 8100

# Ephemeral by construction: no volumes, container removed on stop.
c.DockerSpawner.remove = True
c.DockerSpawner.volumes = {}

# Internal-only network: user containers can reach the hub (API/OAuth) and
# be reached by the proxy, but have no route to the outside world (the
# docker network is created with internal=true, see docker-compose.yml).
c.DockerSpawner.network_name = os.environ.get(
    'ORDEC_HUB_USER_NETWORK', 'ordec-hub-users')
c.DockerSpawner.use_internal_ip = True

# Per-user resource caps. cpu_limit is a hard cgroup CFS quota on the VM:
# runaway simulations only burn the user's own allowance; the kernel
# fair-shares between VMs below the caps.
c.DockerSpawner.mem_limit = os.environ.get('ORDEC_HUB_MEM_LIMIT', '2G')
c.DockerSpawner.cpu_limit = float(os.environ.get('ORDEC_HUB_CPU_LIMIT', '2'))

# Kata VM boot + first ngspice/PDK load can take a while on a loaded host:
c.DockerSpawner.start_timeout = 300
c.DockerSpawner.http_timeout = 120

# Where the hub redirects the browser after spawn. '/' is the ORDeC example
# chooser; a course can be preselected with e.g. '/app.html#course=intro'.
c.Spawner.default_url = os.environ.get('ORDEC_HUB_DEFAULT_URL', '/')

# Don't leak the hub container's environment into user containers:
c.Spawner.env_keep = []

# --- Hub networking (hub runs as the 'jupyterhub' compose service) --------
c.JupyterHub.hub_ip = '0.0.0.0'
c.JupyterHub.hub_connect_ip = os.environ.get(
    'ORDEC_HUB_CONNECT_IP', 'jupyterhub')

# --- Capacity --------------------------------------------------------------
c.JupyterHub.active_server_limit = int(
    os.environ.get('ORDEC_HUB_MAX_SERVERS', '90'))
c.JupyterHub.concurrent_spawn_limit = int(
    os.environ.get('ORDEC_HUB_CONCURRENT_SPAWNS', '10'))
c.JupyterHub.named_server_limit_per_user = 0  # default server only

# --- Idle culling: ephemeral sessions, default ~90 min ---------------------
# ordec reports websocket activity to the hub (see ordec/hub.py), so open
# but idle browser tabs do not keep instances alive, and running
# interactions do not get culled.
c.JupyterHub.load_roles = [
    {
        'name': 'idle-culler',
        # admin:users is required by --cull-users (deletes stale guests below).
        'scopes': ['list:users', 'read:users:activity',
            'read:servers', 'delete:servers', 'admin:users'],
        'services': ['idle-culler'],
    },
]
c.JupyterHub.services = [
    {
        'name': 'idle-culler',
        'command': [
            sys.executable, '-m', 'jupyterhub_idle_culler',
            '--timeout', os.environ.get('ORDEC_HUB_IDLE_TIMEOUT', '5400'),
            # Ephemeral guests accumulate as user records; delete the ones whose
            # server has stopped and gone idle so the hub DB does not grow.
            '--cull-users',
        ],
    },
]
