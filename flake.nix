# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# ORDeC with tools, PDKs and Python packages, the development shells and the
# Docker images. See docs/dev/setup.rst and docs/dev/containers_and_ci.rst.
{
  description = "ORDeC: tools, PDKs, Python packages and development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  # No nixConfig for the binary cache ordec.cachix.org: for untrusted users
  # (the default with a multi-user installation), Nix only prompts and warns
  # about it on every run. See docs/dev/setup.rst for adding the cache.

  outputs = { self, nixpkgs }:
  let
    system = "x86_64-linux";
    pkgs = nixpkgs.legacyPackages.${system};
    lib = pkgs.lib;

    # Tools
    # =====

    # 45.2 instead of nixpkgs' 45 (bug fix release).
    ngspice = pkgs.ngspice.overrideAttrs (old: {
      version = "45.2";
      src = pkgs.fetchurl {
        url = "mirror://sourceforge/ngspice/ng-spice-rework/old-releases/45.2/ngspice-45.2.tar.gz";
        sha256 = "ba8345f4c3774714c10f33d7da850d361cec7d14b3a295d0dc9fd96f7423812d";
      };
      # The 45.2 tarball triggers an autotools rerun.
      nativeBuildInputs = old.nativeBuildInputs ++ [ pkgs.autoreconfHook ];
    });
    # KLayout only runs in batch mode (klayout -b), but needs Qt for the
    # klayout executable (-without-qt builds only the libraries). nixpkgs'
    # Qt pulls in GTK3 (theme plugin), systemd (journald logging) and, via
    # qt5compat's QML plugin, qtdeclarative: all unneeded here.
    qt = pkgs.qt6.overrideScope (qf: qp: {
      qtbase = qp.qtbase.override {
        withGtk3 = false;
        systemdSupport = false;
        qttranslations = null;
      };
      qt5compat = qp.qt5compat.overrideAttrs { propagatedBuildInputs = [ qf.qtbase ]; };
    });

    # 0.30.5, without the Qt bindings, designer and multimedia parts.
    klayout = (pkgs.klayout.override {
      qt6 = qt;
      python3 = pkgs.python313;
    }).overrideAttrs (old: {
      version = "0.30.5";
      src = pkgs.fetchurl {
        url = "https://www.klayout.org/downloads/source/klayout-0.30.5.tar.gz";
        sha256 = "7646acc1d81a5176dc577b297b96aabfa8515b17d264a9b85c9231a937ba42b7";
      };
      nativeBuildInputs = builtins.filter (d: !(lib.hasPrefix "qtmultimedia" d.name || lib.hasPrefix "qttools" d.name)) old.nativeBuildInputs;
      buildInputs = [ qt.qtbase qt.qtsvg qt.qt5compat pkgs.zlib ];
      buildPhase = ''
        runHook preBuild
        mkdir -p $out/lib
        ./build.sh \
          -prefix $out/lib \
          -option "-j$NIX_BUILD_CORES" \
          -rpath $out/lib \
          -nolibgit2 -nolstream -without-qtbinding \
          -without-qt-uitools -without-qt-designer -without-qt-multimedia
        runHook postBuild
      '';
    });
    # Without the embedded Python (pyosys), which ORDeC does not use: it adds
    # a second Python (3.14) to the closure.
    # Without readline: with it, the abc pass keeps ABC processes running and
    # recognizes the end of each ABC run by the prompts readline echoes. With
    # readline 8.3 and TERM set, this deadlocks (Yosys 0.70). Without
    # readline, Yosys starts ABC with a script file for each run.
    # The test suite (about an hour) is left to nixpkgs, which runs it for
    # its Yosys; this one differs only in the build options.
    yosys = (pkgs.yosys.override { enablePython = false; }).overrideAttrs (old: {
      cmakeFlags = old.cmakeFlags ++ [ (lib.cmakeBool "YOSYS_WITHOUT_READLINE" true) ];
      doCheck = false;
    });
    inherit (pkgs) openvaf magic-vlsi;

    # OpenVAF with only the runtime part of LLVM: the llvm "lib" output it
    # references is 550 MiB, mostly static archives; only libLLVM.so (184 MiB)
    # is needed at runtime.
    # OpenVAF also calls ld at runtime.
    openvaf-slim = let
      llvm-lib = (lib.findFirst (d: lib.hasPrefix "llvm-" d.name) null (openvaf.buildInputs ++ openvaf.nativeBuildInputs)).lib;
    in pkgs.runCommand "openvaf-slim-${openvaf.version}" {
      nativeBuildInputs = [ pkgs.patchelf pkgs.makeWrapper ];
      disallowedReferences = [ llvm-lib ];
    } ''
      mkdir -p $out/bin $out/lib
      cp ${llvm-lib}/lib/libLLVM.so.* $out/lib/
      cp ${openvaf}/bin/openvaf-r $out/lib/
      chmod u+w $out/lib/*
      patchelf --set-rpath "$out/lib:$(patchelf --print-rpath $out/lib/openvaf-r | sed 's|${llvm-lib}/lib:||')" $out/lib/openvaf-r
      makeWrapper $out/lib/openvaf-r $out/bin/openvaf-r --prefix PATH : ${pkgs.binutils-unwrapped}/bin
    '';

    # Yosys without yosys-config (for plugin builds; references gcc) and the
    # formal verification scripts. Yosys finds its share dir relative to the
    # binary.
    yosys-slim = pkgs.runCommand "yosys-slim-${yosys.version}" {
      nativeBuildInputs = [ pkgs.removeReferencesTo ];
      disallowedReferences = [ yosys pkgs.stdenv.cc pkgs.stdenv.cc.cc ];
    } ''
      mkdir -p $out/bin $out/share
      cp ${yosys}/bin/{yosys,yosys-abc,yosys-filterlib} $out/bin/
      cp -r ${yosys}/share/yosys $out/share/
      chmod -R u+w $out
      find $out -type f -exec remove-references-to -t ${yosys} -t ${pkgs.stdenv.cc} -t ${pkgs.stdenv.cc.cc} {} +
    '';

    # PDKs
    # ====

    pdk-sky130 = pkgs.stdenvNoCC.mkDerivation {
      pname = "pdk-sky130";
      version = "fa87f8f4";
      srcs = [
        (pkgs.fetchurl {
          url = "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/common.tar.zst";
          sha256 = "c7c155596a1fd1fcf6d5414dfcffcbbcf4e35b2b33160af97f4340e763c97406";
        })
        (pkgs.fetchurl {
          url = "https://github.com/efabless/volare/releases/download/sky130-fa87f8f4bbcc7255b6f0c0fb506960f531ae2392/sky130_fd_pr.tar.zst";
          sha256 = "41dc9098541ed3329eba4ec7f5dfd1422eb09e94b623ea1f6dc3895f9ccebf63";
        })
      ];
      nativeBuildInputs = [ pkgs.zstd ];
      sourceRoot = ".";
      dontBuild = true;
      dontFixup = true;
      installPhase = ''
        rm -r sky130{A,B}/libs.tech/{xschem,openlane}
        mkdir $out
        mv sky130A sky130B $out/
      '';
    };

    # Source plus the compiled Verilog-A models (libs.tech/ngspice/osdi), as
    # the Docker image has it.
    pdk-ihp-sg13g2 = pkgs.stdenv.mkDerivation {
      pname = "pdk-ihp-sg13g2";
      version = "0.3.0";
      src = pkgs.fetchFromGitHub {
        owner = "IHP-GmbH";
        repo = "IHP-Open-PDK";
        rev = "v0.3.0";
        fetchSubmodules = true;
        postFetch = "rm -r $out/ihp-sg13g2/libs.doc $out/ihp-sg13g2/libs.tech/openems";
        hash = "sha256-hu7KtFvtFIycpVRQo+ptw07KXxN767K97J3U3+kIn0g=";
      };
      nativeBuildInputs = [ openvaf ];
      dontFixup = true;
      # --compile-model-generic: by default, OpenVAF compiles for the CPU of
      # the build machine, and ngspice dies with "illegal instruction" when
      # the models run on a CPU lacking some of its instruction set
      # extensions (e.g. AVX-512). The script does not fail when OpenVAF
      # does, hence the check for its output.
      buildPhase = ''
        cd ihp-sg13g2/libs.tech/verilog-a
        patchShebangs .
        ./openvaf-compile-va.sh --compile-model-generic
        for m in psp103 psp103_nqs r3_cmc mosvar; do test -f ../ngspice/osdi/$m.osdi; done
        cd -
      '';
      installPhase = "cp -r ihp-sg13g2 $out";
    };

    # Written into ordec.lib.pdk_dirs by the ordec build
    # (support/nix/python.nix).
    pdkDirs = {
      sky130a = "${pdk-sky130}/sky130A";
      sky130b = "${pdk-sky130}/sky130B";
      ihp_sg13g2 = "${pdk-ihp-sg13g2}";
    };

    # For development: with yosys-config and the OpenVAF build dependencies.
    tools = [ ngspice klayout magic-vlsi yosys openvaf ];
    # For the ordec package, the images and tests.yaml.
    runtimeTools = [ ngspice klayout magic-vlsi yosys-slim openvaf-slim ];

    # Python
    # ======

    # Flakes do not see git tags. GitHub's source archives, which Nix fetches
    # for github: flake references, have the git describe output in
    # .git_archival.txt (export-subst in .gitattributes). From it, the
    # version is derived as setuptools-scm does on main (release-branch-semver):
    # v0.9.0 -> 0.9.0, v0.9.0-16-gabc1234 -> 0.10.0.dev16+gabc1234. A local
    # checkout only has the placeholder; the ".dev" there makes
    # ordec.version.doc_url link to the latest documentation.
    version = let
      d = builtins.match ".*describe-name: v([0-9]+)\\.([0-9]+)\\.([0-9]+)(-([0-9]+)-(g[0-9a-f]+))?\n.*"
        (builtins.readFile ./.git_archival.txt);
      at = builtins.elemAt d;
    in
      if d == null then "0.dev0+g${self.shortRev or self.dirtyShortRev or "unknown"}"
      else if at 3 == null then "${at 0}.${at 1}.${at 2}"
      else "${at 0}.${toString (lib.toInt (at 1) + 1)}.0.dev${at 4}+${at 5}";

    py = import ./support/nix/python.nix {
      inherit pkgs lib pdkDirs version;
      tools = runtimeTools;
    };
    inherit (py) ordec;

    # Images
    # ======

    # Without a Linux distribution: Python with ordec (so that scripts can
    # import it), the tools and a minimal shell environment, linked into /bin.
    image-env = pkgs.buildEnv {
      name = "ordec-image-env";
      paths = runtimeTools ++ [
        (py.python.withPackages (ps: [ ordec ]))
        pkgs.bashInteractive pkgs.coreutils pkgs.gnugrep pkgs.gnused pkgs.findutils
      ];
      pathsToLink = [ "/bin" ];
    };

    # Load into Docker with: $(nix build --no-link --print-out-paths .#image) | docker load
    mkImage = { name, cmd, env ? [ ] }: pkgs.dockerTools.streamLayeredImage {
      inherit name;
      tag = "latest";
      contents = [ image-env ];
      extraCommands = ''
        mkdir -m 1777 tmp
        mkdir -p etc root usr/bin
        ln -s /bin/env usr/bin/env
        printf 'root:x:0:0::/root:/bin/sh\napp:x:1000:1000::/home/app:/bin/sh\n' > etc/passwd
        printf 'root:x:0:\napp:x:1000:\n' > etc/group
      '';
      fakeRootCommands = "mkdir -p home/app && chown 1000:1000 home/app";
      config = {
        User = "app";
        WorkingDir = "/home/app";
        Env = [
          "PATH=/bin"
          # Files written to the container (e.g. the LayoutStyle
          # customizations in ~/.config/ordec) are lost with it; the web UI
          # warns about this. Set to 0 when ~/.config/ordec is a volume.
          "ORDEC_CONFIG_EPHEMERAL=1"
        ] ++ env;
        Cmd = cmd;
        ExposedPorts."8100/tcp" = { };
        Labels = {
          "org.opencontainers.image.source" = "https://github.com/tub-msc/ordec";
          "org.opencontainers.image.revision" = self.rev or self.dirtyRev or "unknown";
        };
      };
    };

    image = mkImage {
      name = "ordec";
      cmd = [ "ordec" "-l" "0.0.0.0" "-p" "8100" "--no-browser" "--url-authority" "127.0.0.1:8100" ];
    };

    # User image for ORDeC Hub (see docs/dev/hub.rst). ordec detects the hub
    # through the JUPYTERHUB_* environment DockerSpawner sets and then takes
    # address and port from JUPYTERHUB_SERVICE_URL; the command line values
    # are the fallback for running the image without a hub. Unbuffered
    # stdout, so that ordec's messages (e.g. hub login failures) reach
    # docker logs immediately.
    hub-image = mkImage {
      name = "ordec-hub-user";
      cmd = [ "ordec" "-l" "0.0.0.0" "-p" "8100" "--no-browser" ];
      env = [ "PYTHONUNBUFFERED=1" ];
    };
  in {
    packages.${system} = {
      inherit ngspice klayout magic-vlsi yosys yosys-slim openvaf openvaf-slim pdk-sky130 pdk-ihp-sg13g2;
      inherit ordec image-env image hub-image;
      inherit (py) web;
      default = ordec;
    };

    # For other flakes: adds ordec and its dependencies missing in nixpkgs to
    # the Python package sets.
    overlays.default = _: prev: {
      pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [ py.overlay ];
    };

    devShells.${system} = {
      # Python packages from Nix, with ordec installed in editable mode
      # pointing to src/ of the checkout (see devPython), where the C
      # extensions are built in place (setup.py build_ext --inplace).
      # Entering the shell thus changes nothing in the checkout, and any
      # number of shells can run at once.
      default = pkgs.mkShell {
        # graphviz: for the inheritance diagrams in the documentation.
        packages = tools ++ [ py.devPython pkgs.nodejs pkgs.chromium pkgs.chromedriver pkgs.graphviz ];
        # Otherwise, ChromeDriver picks up a system Chromium of another version.
        ORDEC_CHROME = "${pkgs.chromium}/bin/chromium";
        # Outside NixOS, the glibc of Nix cannot read the locales of the
        # system, and setlocale fails for them (e.g. in sphinx-build).
        LOCALE_ARCHIVE = "${pkgs.glibcLocales}/lib/locale/locale-archive";
        # The editable install of ordec runs from the checkout, whose pdk_dirs
        # has no directories.
        ORDEC_PDK_SKY130A = pdkDirs.sky130a;
        ORDEC_PDK_SKY130B = pdkDirs.sky130b;
        ORDEC_PDK_IHP_SG13G2 = pdkDirs.ihp_sg13g2;
        # Nix does not tell where the checkout is (the flake is evaluated from
        # a copy in the Nix store), hence the current directory.
        shellHook = ''
          root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
          if [ -f "$root/src/ordec/__init__.py" ]; then
            export ORDEC_CHECKOUT="$root"
            if ! compgen -G "$root/src/ordec/core/ordb/_ordb*.so" > /dev/null; then
              echo "nix develop: The C extensions of ordec are not built yet. In $root, run: python3 setup.py build_ext --inplace" >&2
            fi
          else
            echo "nix develop: $root is not an ORDeC checkout, so ordec is not available in this shell. Enter the shell in the checkout." >&2
          fi
        '';
      };

      # For tests.yaml: the ordec package and the tools as in the images, the
      # test dependencies and Chromium, with fonts of its own (without any,
      # it crashes when rendering pages). Chromium without its wrapper, which
      # adds GTK 4 and GStreamer (about 700 MiB) that headless runs do not
      # need. Without ORDEC_PDK_*, so that the tests use the PDK directories
      # written into the ordec package.
      test = pkgs.mkShellNoCC {
        packages = runtimeTools ++ [ py.testPython pkgs.chromedriver ];
        ORDEC_CHROME = "${pkgs.chromium.browser}/libexec/chromium/chromium";
        FONTCONFIG_FILE = pkgs.makeFontsConf { fontDirectories = [ pkgs.dejavu_fonts ]; };
        # Entered from the development shell, its ORDEC_PDK_* would be used.
        shellHook = "unset ORDEC_PDK_SKY130A ORDEC_PDK_SKY130B ORDEC_PDK_IHP_SG13G2";
      };
    };
  };
}
