# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# User image for ORDeC Hub: the regular ordec image (ordec + ngspice +
# KLayout + PDKs, see /Dockerfile in the repository root) with a
# hub-suitable start command. ordec detects the hub automatically through
# the JUPYTERHUB_* environment DockerSpawner sets (see ordec/hub.py) and
# then serves under /user/<name>/, gated by hub OAuth.
#
# Build (from the repository root):
#   docker build -t ordec .
#   docker build -t ordec-hub-user -f hub/Dockerfile hub/

ARG ORDEC_IMAGE=ordec
FROM ${ORDEC_IMAGE}

# Unbuffered stdout so ORDeC's operational messages (e.g. hub login failures)
# reach `docker logs` immediately instead of sitting in a pipe buffer.
ENV PYTHONUNBUFFERED=1

# Bind address/port come from JUPYTERHUB_SERVICE_URL; the CLI values are
# the fallback for running the image without a hub.
CMD ["ordec", "-l", "0.0.0.0", "-p", "8100", "--no-browser"]
