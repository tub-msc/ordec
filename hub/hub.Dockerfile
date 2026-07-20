# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# JupyterHub image for ORDeC Hub (the hub itself, not the user containers;
# for those see hub/Dockerfile).

FROM quay.io/jupyterhub/jupyterhub:5

# Pinned: jupyterhub_config.py touches JupyterHub/spawner/culler internals
# (handler overrides, spawner._stop_pending, culler CLI flags), so a workshop
# build must be reproducible. Bump deliberately and re-test the login/logout/
# cull flow.
RUN pip install --no-cache-dir \
    dockerspawner==14.0.0 \
    jupyterhub-idle-culler==2.0.0

COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py
COPY templates/ /srv/jupyterhub/templates/
COPY ordec_logo.svg /srv/jupyterhub/ordec_logo.svg

CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
