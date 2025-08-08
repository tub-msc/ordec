# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# This multi-stage Dockerfile generates the 'ordec' image for users. It contains
# a ready-to-run ORDeC installation and includes recommended tools and PDKs.
#
# See docs/dev/containers_and_ci.rst for details.

# Stage 1
# -------

FROM ghcr.io/tub-msc/ordec-base:sha-81011ee AS ordec-base

# Build ORDeC wheel:
WORKDIR /home/app/ordec
COPY --chown=app . .
#ENV SETUPTOOLS_SCM_PRETEND_VERSION=0
RUN python3 -m build .

# Stage 2
# -------

FROM debian:bookworm AS ordec

RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
        python3-minimal \
        python3-venv \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app
WORKDIR /home/app

COPY --chown=app --from=ordec-base /home/app/ngspice /home/app/ngspice
COPY --chown=app --from=ordec-base /home/app/openvaf /home/app/openvaf
COPY --chown=app --from=ordec-base /home/app/IHP-Open-PDK /home/app/IHP-Open-PDK
COPY --chown=app --from=ordec-base /home/app/skywater /home/app/skywater
COPY --chown=app --from=ordec-base /home/app/ordec/dist/*.whl /home/app

ENV VIRTUAL_ENV=/home/app/venv
RUN python3 -m venv $VIRTUAL_ENV && $VIRTUAL_ENV/bin/pip install --no-cache-dir *.whl

ENV PATH="$VIRTUAL_ENV/bin:/home/app/openvaf:/home/app/ngspice/min/bin:$PATH"
ENV LD_LIBRARY_PATH="/home/app/ngspice/shared/lib"
ENV ORDEC_PDK_SKY130A="/home/app/skywater/sky130A"
ENV ORDEC_PDK_SKY130B="/home/app/skywater/sky130B"
ENV ORDEC_PDK_IHP_SG13G2="/home/app/IHP-Open-PDK/ihp-sg13g2"

EXPOSE 8100
CMD ["ordec-server", "-l", "0.0.0.0", "-p", "8100", "--no-browser", "--url-authority", "127.0.0.1:8100"]
