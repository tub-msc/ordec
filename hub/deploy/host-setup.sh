#!/bin/sh
# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0
#
# Host provisioning for ORDeC Hub on a fresh Debian/Ubuntu dedicated server
# with KVM (check: ls /dev/kvm). Installs Docker and Kata Containers and
# runs a smoke test. Review before running; run as root.
#
# NOTE: written for the workshop PoC; verify each step on the target host.

set -eu

# Needs >= 3.32.0: Docker 29.5.0 enables private time namespaces by default, and
# older kata-agents reject the resulting OCI spec with "invalid namespace type".
# Fixed upstream by kata-containers#13082, first released in 3.32.0.
KATA_VERSION="${KATA_VERSION:-3.32.0}"

echo "== Checking KVM =="
if [ ! -e /dev/kvm ]; then
    echo "ERROR: /dev/kvm not found. This host cannot run Kata Containers."
    echo "Dedicated servers have KVM natively; most budget cloud VMs do not."
    exit 1
fi

echo "== Installing Docker (get.docker.com) =="
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
docker version

echo "== Installing Kata Containers ${KATA_VERSION} (static tarball) =="
# https://github.com/kata-containers/kata-containers/releases
if [ ! -x /opt/kata/bin/kata-runtime ]; then
    # Kata names its release assets by Go arch, not uname -m.
    case "$(uname -m)" in
        x86_64) arch=amd64 ;;
        aarch64) arch=arm64 ;;
        ppc64le) arch=ppc64le ;;
        s390x) arch=s390x ;;
        *) echo "ERROR: no Kata static tarball for $(uname -m)."; exit 1 ;;
    esac
    # Releases from 3.32.0 on ship zstd tarballs; earlier ones were xz.
    if ! command -v zstd >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get -y -qq install zstd >/dev/null
    fi
    curl -fsSL -o /tmp/kata-static.tar.zst \
        "https://github.com/kata-containers/kata-containers/releases/download/${KATA_VERSION}/kata-static-${KATA_VERSION}-${arch}.tar.zst"
    tar --zstd -xf /tmp/kata-static.tar.zst -C /
    rm /tmp/kata-static.tar.zst
fi
# Docker >= 23 resolves the runtime string io.containerd.kata.v2 to a
# containerd shim binary on PATH:
ln -sf /opt/kata/bin/containerd-shim-kata-v2 /usr/local/bin/containerd-shim-kata-v2
/opt/kata/bin/kata-runtime check || true

echo "== Registering kata runtime with Docker =="
mkdir -p /etc/docker
python3 - <<'EOF'
import json, os
path = '/etc/docker/daemon.json'
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)
cfg.setdefault('runtimes', {})['kata'] = {
    'runtimeType': 'io.containerd.kata.v2',
}
with open(path, 'w') as f:
    json.dump(cfg, f, indent=2)
EOF
systemctl restart docker

echo "== Smoke test: container under Kata must see a different kernel =="
host_kernel="$(uname -r)"
kata_kernel="$(docker run --rm --runtime io.containerd.kata.v2 alpine uname -r)"
echo "host kernel: ${host_kernel}"
echo "kata kernel: ${kata_kernel}"
if [ "${host_kernel}" = "${kata_kernel}" ]; then
    echo "ERROR: kernel inside the container equals the host kernel;"
    echo "Kata/KVM isolation is NOT active."
    exit 1
fi

echo "== OK. Next steps: see docs/dev/hub.rst =="
