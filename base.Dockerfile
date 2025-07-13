# Set ngspice_multibuild to "on" to enable triple ngspice build (for future testing).
ARG ngspice_multibuild="off"

# Set experimental to "on" to include experimental stuff (OpenVAF, PDKs).
ARG experimental="off"

# Stage 1: Download stuff
# =======================

FROM debian:bookworm AS ordec-fetch

RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app

WORKDIR /home/app
RUN wget https://netcologne.dl.sourceforge.net/project/ngspice/ng-spice-rework/44.2/ngspice-44.2.tar.gz && \
    echo "e7dadfb7bd5474fd22409c1e5a67acdec19f77e597df68e17c5549bc1390d7fd ngspice-44.2.tar.gz" | sha256sum -c && \
    tar xzvf ngspice-44.2.tar.gz && \
    rm ngspice-44.2.tar.gz && \
    mv ngspice-44.2 ngspice-src

WORKDIR /home/app/openvaf
RUN if [ ${experimental} != off ]; then \
    wget https://openva.fra1.cdn.digitaloceanspaces.com/openvaf_23_5_0_linux_amd64.tar.gz && \
    echo "79c0e08ad948a7a9f460dc87be88b261bbd99b63a4038db3c64680189f44e4f0 openvaf_23_5_0_linux_amd64.tar.gz" | sha256sum -c && \
    tar xzvf openvaf_23_5_0_linux_amd64.tar.gz && \
    rm openvaf_23_5_0_linux_amd64.tar.gz; \
    fi

WORKDIR /home/app
RUN if [ ${experimental} != off ]; then \
    wget https://github.com/IHP-GmbH/IHP-Open-PDK/archive/refs/tags/v0.2.0.tar.gz && \
    echo "3fbc8da1aa59505a6eee2122bfcf5419f621b9f1ed7ed9826318505f7bb38fbf v0.2.0.tar.gz" | sha256sum -c && \
    tar xzvf v0.2.0.tar.gz && \
    rm v0.2.0.tar.gz && \
    mv IHP-Open-PDK-0.2.0 IHP-Open-PDK; \
    fi && mkdir -p /home/app/IHP-Open-PDK

# Stage 2: Build Ngspice
# ======================

FROM debian:bookworm AS ordec-cbuild

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

RUN useradd -ms /bin/bash app && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-inconsolata \
        libgomp1 \
        python3-minimal \
        python3-venv \
        npm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
USER app
WORKDIR /home/app

COPY --chown=app --from=ordec-cbuild /home/app/ngspice /home/app/ngspice
COPY --chown=app --from=ordec-fetch /home/app/openvaf /home/app/openvaf
COPY --chown=app --from=ordec-fetch /home/app/IHP-Open-PDK /home/app/IHP-Open-PDK

# Create Python venv + install Python dependencies
# ------------------------------------------------

WORKDIR /home/app/ordec
ENV VIRTUAL_ENV=/home/app/venv
RUN python3 -m venv $VIRTUAL_ENV --system-site-packages
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# TODO: Docker layer with pyproject.toml for this / maybe also pin dependencies via requirements.txt or so.
RUN pip install \
    pyrsistent \
    astor \
    websockets \
    lark \
    scipy \
    numpy \
    pytest \
    pytest-cov

# NPM install
# -----------

WORKDIR /home/app/ordec/web
COPY --chown=app web/package.json web/package-lock.json .
RUN npm install

WORKDIR /home/app
