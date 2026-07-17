# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# JupyterHub image for ORDeC Hub (the hub itself, not the user containers;
# for those see hub/Dockerfile).

FROM quay.io/jupyterhub/jupyterhub:5

RUN pip install --no-cache-dir \
    dockerspawner \
    jupyterhub-idle-culler

COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py

CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
