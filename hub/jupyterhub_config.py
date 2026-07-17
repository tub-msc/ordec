# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

"""
JupyterHub configuration for ORDeC Hub workshop deployments.

See docs/dev/hub.rst for the architecture and deployment steps. Tunables come
from environment variables (ORDEC_HUB_*), see hub/example.env.
"""

import os
import sys

c = get_config()  # noqa

# --- Authentication -------------------------------------------------------
# Shared workshop key: participants pick any username and enter the key.
# Swapping to institutional/OAuth login is a pure config change, e.g.:
#   c.JupyterHub.authenticator_class = 'github'
#   c.GitHubOAuthenticator.client_id = ...
# (requires oauthenticator in the hub image; nothing else changes).
c.JupyterHub.authenticator_class = 'dummy'
c.DummyAuthenticator.password = os.environ['ORDEC_HUB_WORKSHOP_KEY']
c.Authenticator.allow_all = True
c.Authenticator.admin_users = set(
    filter(None, os.environ.get('ORDEC_HUB_ADMINS', '').split(',')))

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
        'scopes': ['list:users', 'read:users:activity',
            'read:servers', 'delete:servers'],
        'services': ['idle-culler'],
    },
]
c.JupyterHub.services = [
    {
        'name': 'idle-culler',
        'command': [
            sys.executable, '-m', 'jupyterhub_idle_culler',
            '--timeout', os.environ.get('ORDEC_HUB_IDLE_TIMEOUT', '5400'),
        ],
    },
]
