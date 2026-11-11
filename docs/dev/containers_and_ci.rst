.. _containers_and_ci:

Packaging and CI
================

*flake.nix* defines how ORDeC is built with Nix: the ordec package, the tools (Ngspice, KLayout, Yosys, OpenVAF), the PDKs (SKY130, IHP-Open-PDK), the development shells (see :ref:`dev_setup`) and the Docker images. *flake.lock* pins the nixpkgs revision and with it the versions of everything.

The ordec package
-----------------

``nix build`` builds the default package *ordec*, which is also what ``nix run`` and ``nix profile add`` use. It includes the C extensions and the frontend. Its ``ordec`` executable has the tools on ``PATH`` and defaults for the ``ORDEC_PDK_*`` variables, so it needs no further setup. Variables set by the user take precedence.

*support/nix/python.nix* reads the Python dependencies from *pyproject.toml* and takes them from nixpkgs. The few packages nixpkgs lacks are fetched as wheels from PyPI. The build checks all versions against *pyproject.toml*. Installations with pip get the newest versions *pyproject.toml* allows instead, which the automated tests do not cover.

The frontend is built separately, as flake output *web* from *web/package-lock.json*, because the Nix build has no network access for ``npm ci``. *setup.py* takes it from ``ORDEC_WEBDIST``.

The version is derived from git tags, as with setuptools-scm, but a flake does not see the git history. Instead, *.git_archival.txt* is filled with the ``git describe`` output whenever GitHub creates a source archive (``export-subst`` in *.gitattributes*), and Nix fetches ``github:`` flake references as such archives. So ``nix run github:tub-msc/ordec/v0.10.0`` reports 0.10.0. Builds from a local checkout only see the placeholder and report ``0.dev0+g<rev>``. A drawback: the content of an archive changes when a tag is later added to its commit (or to a commit between it and the previous tag), so a *flake.lock* elsewhere that pins ORDeC by commit then fails with a hash mismatch until it is updated.

Docker images
-------------

The `ordec <https://github.com/tub-msc/ordec/pkgs/container/ordec>`__ image runs ORDeC through a single docker command (see Readme). The flake output *image* builds it without Docker and without a Linux distribution: */bin* has Python with ordec, the tools, bash and the core utilities, everything else is in */nix/store*. There is no package manager and no pip. To load the image into Docker as *ordec:latest*::

    $(nix build --no-link --print-out-paths .#image) | docker load

*hub-image* is the same image with the start command for ORDeC Hub (see :doc:`hub`).

The image sets ``ORDEC_CONFIG_EPHEMERAL=1``: files ORDeC writes to the user's configuration directory (the LayoutStyle customizations in ``~/.config/ordec/layout/`` and the settings in ``~/.config/ordec/config.toml``, such as the crossing style of schematics) are lost with the container. The layout viewer points this out when saving a LayoutStyle customization. Users who mount ``~/.config/ordec`` as a volume can set it to ``0``.

*.github/workflows/build.yaml* builds and pushes the image when started manually. Before pushing, it checks only what is specific to the image: user, environment, tools, PDKs and that the server starts. The test suite itself runs in *tests.yaml* with the same ordec package and tools.

In the future, ordec Docker images should be released in sync with the PyPI package ordec, both using git version tags (vX.Y.Z).

Automated tests
---------------

*.github/workflows/tests.yaml* runs pytest on every push, in the development shell *test* (``nix develop .#test``). Like *build.yaml*, it takes the flake from GitHub (``github:<repository>/<commit>``) rather than from the checkout, so that the version is set. This shell has the ordec package as built by Nix, the tools of the image, the test dependencies and Chromium. The tests thus run against the installed package with its packaged frontend, not against the checkout.

Binary cache
------------

What *flake.nix* builds itself (KLayout with its Qt, Yosys, Ngspice, the PDKs, ordec) is not in the binary cache of nixpkgs. It is kept in the public Cachix cache `ordec <https://app.cachix.org/cache/ordec>`__, which drops the least recently used entries when it reaches 5 GB. *tests.yaml* and *build.yaml* push everything they build, using the repository secret ``CACHIX_AUTH_TOKEN``. Without the cache, building KLayout, Qt and Yosys takes one to two hours.

Updating the pinned versions
----------------------------

``nix flake update`` moves *flake.lock* to the newest nixpkgs. This usually rebuilds Qt, KLayout and Yosys, which would make the next run of *tests.yaml* take one to two hours (the 30 minute limit there applies only to the tests). To avoid this, build the development shells and the image locally and push them to the cache (with the Cachix auth token configured) before committing the new *flake.lock*::

    nix flake update
    nix develop --profile /tmp/ordec-dev -c true
    nix develop .#test --profile /tmp/ordec-test -c true
    nix build -o /tmp/ordec-image .#image
    cachix push ordec /tmp/ordec-dev /tmp/ordec-test /tmp/ordec-image
