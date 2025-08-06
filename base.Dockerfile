# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# This multi-stage Dockerfile generates the 'ordec-base' image for testing,
# development and building of ORDeC.
#
# See docs/dev/containers_and_ci.rst for details.

# Stage 1: Download stuff
# =======================

FROM debian:bookworm AS ordec-fetch

RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget ca-certificates zstd git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app

WORKDIR /home/app
RUN wget -q https://netcologne.dl.sourceforge.net/project/ngspice/ng-spice-rework/44.2/ngspice-44.2.tar.gz && \
    echo "e7dadfb7bd5474fd22409c1e5a67acdec19f77e597df68e17c5549bc1390d7fd ngspice-44.2.tar.gz" | sha256sum -c && \
    tar xf ngspice-44.2.tar.gz && \
    rm ngspice-44.2.tar.gz && \
    mv ngspice-44.2 ngspice-src

WORKDIR /home/app/openvaf
RUN wget -q https://openva.fra1.cdn.digitaloceanspaces.com/openvaf_23_5_0_linux_amd64.tar.gz && \
    echo "79c0e08ad948a7a9f460dc87be88b261bbd99b63a4038db3c64680189f44e4f0 openvaf_23_5_0_linux_amd64.tar.gz" | sha256sum -c && \
    tar xf openvaf_23_5_0_linux_amd64.tar.gz && \
    rm openvaf_23_5_0_linux_amd64.tar.gz

# The IHP PDK version is pinned to a specific commit hash (on the main branch) below:
# Note: Some stuff (like libs.doc) are deleted to save space.
WORKDIR /home/app/IHP-Open-PDK
RUN git init && \
    git remote add origin https://github.com/IHP-GmbH/IHP-Open-PDK.git && \
    git fetch --depth 1 origin 0854e9bcd558b68c573149038b4c95706314e2f1 && \
    git checkout FETCH_HEAD && \
    rm -r ihp-sg13g2/libs.doc ihp-sg13g2/libs.tech/openems .git

# Note: Some stuff (like libs.tech/xschem) are deleted to save space.
WORKDIR /home/app/skywater
RUN wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/common.tar.zst" && \
    echo "c7c155596a1fd1fcf6d5414dfcffcbbcf4e35b2b33160af97f4340e763c97406 common.tar.zst" | sha256sum -c && \
    wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_pr.tar.zst" && \
    echo "41dc9098541ed3329eba4ec7f5dfd1422eb09e94b623ea1f6dc3895f9ccebf63 sky130_fd_pr.tar.zst" | sha256sum -c && \
    tar xf common.tar.zst && \
    tar xf sky130_fd_pr.tar.zst && \
    rm common.tar.zst sky130_fd_pr.tar.zst && \
    rm -r sky130A/libs.tech/xschem sky130B/libs.tech/xschem && \
    rm -r sky130A/libs.tech/openlane sky130B/libs.tech/openlane

# Stage 2: Build Ngspice
# ======================

FROM debian:bookworm AS ordec-cbuild

# Set ngspice_multibuild to "on" to enable triple ngspice build (for future testing).
ARG ngspice_multibuild="off"

RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        automake \
        bison \
        flex \
        gfortran \
        libedit-dev \
        libncurses-dev \
        libtool \
        libreadline-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app
WORKDIR /home/app

# Three variants are possible. See docs/dev/ngspice_pipe_mode.rst for details.

COPY --chown=app --from=ordec-fetch /home/app/ngspice-src /home/app/ngspice-src

ARG ngspice_common_args="--disable-debug --without-x --enable-xspice --disable-cider --enable-openmp --enable-osdi"

WORKDIR /home/app/ngspice-src

RUN ./configure --prefix=/home/app/ngspice/min ${ngspice_common_args} --with-readline=no --with-editline=no && \
    make -j`nproc --ignore=1` && \
    make install

# ngspice shared library:
RUN ./configure --prefix=/home/app/ngspice/shared ${ngspice_common_args} --with-ngshared --with-readline=no --with-editline=no && \
    make -j`nproc --ignore=1` && \
    make install

RUN if [ ${ngspice_multibuild} != off ]; then \
    ./configure --prefix=/home/app/ngspice/readline ${ngspice_common_args} --with-readline=yes --with-editline=no && \
    make -j`nproc --ignore=1` && \
    make install; \
    fi

RUN if [ ${ngspice_multibuild} != off ]; then \
    ./configure --prefix=/home/app/ngspice/editline ${ngspice_common_args} --with-readline=no --with-editline=yes && \
    make -j`nproc --ignore=1` && \
    make install; \
    fi

# Stage 3: ORDeC base image
# =========================

FROM debian:bookworm AS ordec-base

# - libgomp1: needed for Ngspice
# - binutils: needed for OpenVAF
RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
        python3-minimal \
        python3-venv \
        chromium-driver \
        npm \
        git \
        binutils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app
WORKDIR /home/app

COPY --chown=app --from=ordec-cbuild /home/app/ngspice /home/app/ngspice
COPY --chown=app --from=ordec-fetch /home/app/openvaf /home/app/openvaf
COPY --chown=app --from=ordec-fetch /home/app/IHP-Open-PDK /home/app/IHP-Open-PDK
COPY --chown=app --from=ordec-fetch /home/app/skywater /home/app/skywater

ENV PATH="/home/app/openvaf:/home/app/ngspice/min/bin:$PATH"
ENV LD_LIBRARY_PATH="/home/app/ngspice/shared/lib"
ENV ORDEC_PDK_SKY130A="/home/app/skywater/sky130A"
ENV ORDEC_PDK_SKY130B="/home/app/skywater/sky130B"
ENV ORDEC_PDK_IHP_SG13G2="/home/app/IHP-Open-PDK/ihp-sg13g2"

WORKDIR /home/app/IHP-Open-PDK/ihp-sg13g2/libs.tech/verilog-a/
RUN ./openvaf-compile-va.sh

# Create Python venv + install Python dependencies
# ------------------------------------------------

WORKDIR /home/app/ordec
ENV VIRTUAL_ENV=/home/app/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# TODO: Docker layer with pyproject.toml for this / maybe also pin dependencies via requirements.txt or so.
RUN pip install --no-cache-dir \
    pyrsistent \
    astor \
    websockets \
    lark \
    scipy \
    numpy \
    pytest \
    pytest-cov \
    selenium \
    inotify-simple \
    build

# NPM install
# -----------

WORKDIR /home/app/ordec/web
COPY --chown=app web/package.json web/package-lock.json .
RUN npm install && npm cache clean --force

WORKDIR /home/app
