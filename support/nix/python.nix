# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Python with the packages ORDeC needs, and ORDeC itself. The dependency
# lists are read from pyproject.toml, the versions are those of nixpkgs:
# building ordec checks them against the version constraints in
# pyproject.toml.
{ pkgs, lib, version, tools, pdkDirs }:
let
  pyproject = builtins.fromTOML (builtins.readFile ../../pyproject.toml);

  # Requirements like "numpy>=1.24.2" to nixpkgs packages.
  deps = ps: map (req: ps.${lib.toLower (lib.replaceStrings [ "_" "." ] [ "-" "-" ]
    (builtins.head (builtins.match "([A-Za-z0-9._-]+).*" req)))});
  runtimeDeps = ps: deps ps pyproject.project.dependencies;
  # All extras (test, test-editors, extra).
  extraDeps = ps: deps ps (lib.concatLists (lib.attrValues pyproject.project.optional-dependencies));
  # The documentation dependencies, only for the development shell. Only
  # plain "name>=version" lines are understood.
  docsDeps = ps: deps ps (lib.filter (l: l != "" && !lib.hasPrefix "#" l)
    (lib.splitString "\n" (builtins.readFile ../../docs/requirements.txt)));

  # The frontend, built separately from ordec (setup.py takes it from
  # ORDEC_WEBDIST), so that only changes in web/ rebuild it.
  web = pkgs.buildNpmPackage {
    pname = "ordec-web";
    inherit version;
    src = ../../web;
    npmDeps = pkgs.importNpmLock { npmRoot = ../../web; };
    npmConfigHook = pkgs.importNpmLock.npmConfigHook;
    installPhase = "cp -r dist $out";
  };

  # Python packages for the Python package set: ordec and those of its
  # dependencies that nixpkgs lacks. Exported as flake output
  # overlays.default, so that other flakes can add ordec to their Python.
  # Within the package set, ps.pkgs is the nixpkgs of the user; the frontend,
  # the tools and the PDKs are the ones of this flake.
  overlay = ps: _: let
    # From PyPI, as nixpkgs lacks them. Packages nixpkgs has are not replaced
    # here: that changes the hashes of all packages depending on them, which
    # then are not on cache.nixos.org and get built locally.
    wheel = pname: version: url: hash: args: ps.buildPythonPackage ({
      inherit pname version;
      format = "wheel";
      src = ps.pkgs.fetchurl { inherit url hash; };
    } // args);
  in {
    notcl = wheel "notcl" "0.5.1"
      "https://files.pythonhosted.org/packages/py3/n/notcl/notcl-0.5.1-py3-none-any.whl"
      "sha256-DfkqqQGslfMeHuViyG2ant9256IyMMDc6ToIoN/DDfQ=" { };
    python-gdsii = wheel "python-gdsii" "0.2.3"
      "https://files.pythonhosted.org/packages/py3/p/python_gdsii/python_gdsii-0.2.3-py3-none-any.whl"
      "sha256-vCysPK1BiCp0fA2IN3kYK558BmwJXIqWqfMdXvegGU8=" { };
    # No sdist on PyPI; the manylinux wheel needs the Nix libstdc++. Only for
    # Python 3.13, and thus ordec as well.
    sc-leflib = wheel "sc-leflib" "0.5.2"
      "https://files.pythonhosted.org/packages/cp313/s/sc_leflib/sc_leflib-0.5.2-cp313-cp313-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
      "sha256-+qtii+mO3PPuOXSrhB4SNGK7T81Lrz7wPg1wM5Y119Y=" {
        nativeBuildInputs = [ ps.pkgs.autoPatchelfHook ];
        buildInputs = [ ps.pkgs.stdenv.cc.cc.lib ];
      };

    # The ordec executable finds the tools without further setup (PATH in the
    # wrapper); for imports, they must be on PATH (passthru.tools). The PDK
    # directories are written into ordec.lib.pdk_dirs, so that any Python
    # importing this ordec finds them; ORDEC_PDK_* set by the user take
    # precedence.
    ordec = ps.buildPythonPackage {
      pname = "ordec";
      inherit version;
      pyproject = true;
      src = lib.fileset.toSource {
        root = ../..;
        fileset = lib.fileset.unions [
          ../../src ../../setup.py ../../pyproject.toml ../../MANIFEST.in
          ../../README.md ../../REUSE.toml ../../LICENSES
        ];
      };
      build-system = [ ps.setuptools ps.setuptools-scm ];
      dependencies = runtimeDeps ps;
      env = {
        SETUPTOOLS_SCM_PRETEND_VERSION = version;
        ORDEC_WEBDIST = web;
      };
      postPatch = lib.concatStrings (lib.mapAttrsToList (n: v: ''
        substituteInPlace src/ordec/lib/pdk_dirs.py --replace-fail '${n} = None' '${n} = "${v}"'
      '') pdkDirs);
      makeWrapperArgs = [ "--prefix" "PATH" ":" (lib.makeBinPath tools) ];
      # _gdsrecords is optional in setup.py, i.e. silently left out when it
      # fails to build.
      pythonImportsCheck = [ "ordec" "ordec.layout._gdsrecords" ];
      passthru = { inherit tools; };
      meta.mainProgram = "ordec";
    };
  };

  python = pkgs.python313.override {
    self = python;
    packageOverrides = overlay;
  };
in {
  inherit python web overlay;
  inherit (python.pkgs) ordec;

  # For the development shell, with ordec installed in editable mode: its .pth
  # file points to src/ of the checkout, which the shell hook exports as
  # ORDEC_CHECKOUT (expanded at Python startup). A fixed version, as the version
  # of the checkout would rebuild the environment on every commit.
  # setuptools for building the C extensions in place.
  devPython = python.withPackages (ps: runtimeDeps ps ++ extraDeps ps ++ docsDeps ps
    ++ [ ps.setuptools ps.setuptools-scm ]
    ++ [ (ps.mkPythonEditablePackage {
      pname = "ordec";
      version = "0.dev0";
      root = "$ORDEC_CHECKOUT/src";
      inherit (pyproject.project) scripts;
    }) ]);

  # The installed ordec with the test dependencies, for running the tests
  # against the package as users get it.
  testPython = python.withPackages (ps: [ ps.ordec ] ++ extraDeps ps);
}
