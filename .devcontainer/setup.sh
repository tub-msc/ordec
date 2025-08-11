#!/bin/bash
# SPDX-FileCopyrightText: 2025 ORDeC contributors  
# SPDX-License-Identifier: Apache-2.0

# Setup script for ORDeC development container
# This script replicates the environment setup from base.Dockerfile

set -e

echo "Setting up ORDeC development environment..."

# Create working directories
cd /home/vscode
mkdir -p ngspice openvaf IHP-Open-PDK skywater

# Download and extract ngspice
echo "Downloading ngspice..."
wget -q https://netcologne.dl.sourceforge.net/project/ngspice/ng-spice-rework/44.2/ngspice-44.2.tar.gz
echo "e7dadfb7bd5474fd22409c1e5a67acdec19f77e597df68e17c5549bc1390d7fd ngspice-44.2.tar.gz" | sha256sum -c
tar xf ngspice-44.2.tar.gz
rm ngspice-44.2.tar.gz
mv ngspice-44.2 ngspice-src

# Download and extract OpenVAF
echo "Downloading OpenVAF..."
cd openvaf
wget -q https://openva.fra1.cdn.digitaloceanspaces.com/openvaf_23_5_0_linux_amd64.tar.gz
echo "79c0e08ad948a7a9f460dc87be88b261bbd99b63a4038db3c64680189f44e4f0 openvaf_23_5_0_linux_amd64.tar.gz" | sha256sum -c
tar xf openvaf_23_5_0_linux_amd64.tar.gz
rm openvaf_23_5_0_linux_amd64.tar.gz
cd ..

# Download IHP-Open-PDK
echo "Downloading IHP-Open-PDK..."
cd IHP-Open-PDK
git init
git remote add origin https://github.com/IHP-GmbH/IHP-Open-PDK.git
git fetch --depth 1 origin 0854e9bcd558b68c573149038b4c95706314e2f1
git checkout FETCH_HEAD
rm -rf ihp-sg13g2/libs.doc ihp-sg13g2/libs.tech/openems .git
cd ..

# Download Skywater PDK
echo "Downloading Skywater PDK..."
cd skywater
wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/common.tar.zst"
echo "c7c155596a1fd1fcf6d5414dfcffcbbcf4e35b2b33160af97f4340e763c97406 common.tar.zst" | sha256sum -c
wget -q "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_pr.tar.zst"
echo "41dc9098541ed3329eba4ec7f5dfd1422eb09e94b623ea1f6dc3895f9ccebf63 sky130_fd_pr.tar.zst" | sha256sum -c
tar xf common.tar.zst
tar xf sky130_fd_pr.tar.zst
rm common.tar.zst sky130_fd_pr.tar.zst
rm -rf sky130A/libs.tech/xschem sky130B/libs.tech/xschem
rm -rf sky130A/libs.tech/openlane sky130B/libs.tech/openlane
cd ..

# Build ngspice
echo "Building ngspice..."
cd ngspice-src
ngspice_common_args="--disable-debug --without-x --enable-xspice --disable-cider --enable-openmp --enable-osdi"
./configure --prefix=/home/vscode/ngspice/min ${ngspice_common_args} --with-readline=no --with-editline=no
make -j$(nproc --ignore=1)
make install
cd ..

# Compile Verilog-A models with OpenVAF
echo "Compiling Verilog-A models..."
cd IHP-Open-PDK/ihp-sg13g2/libs.tech/verilog-a/
./openvaf-compile-va.sh
cd /home/vscode

# Create Python virtual environment
echo "Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install --no-cache-dir \
    pyrsistent \
    astor \
    websockets \
    lark \
    scipy \
    numpy \
    pytest \
    pytest-cov \
    selenium \
    build

# Install ORDeC in development mode
echo "Installing ORDeC..."
cd /workspaces/ordec2
pip install -e .[test]

# Install npm dependencies
echo "Installing npm dependencies..."
cd web
npm install

echo "Setup completed successfully!"
echo "You can now use:"
echo "  - ngspice: /home/vscode/ngspice/min/bin/ngspice"
echo "  - openvaf: /home/vscode/openvaf/openvaf"
echo "  - Python venv: source /home/vscode/venv/bin/activate"
echo "  - ORDeC server: ordec-server"