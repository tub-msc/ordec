.. _containers_and_ci:

Containers & continuous integration
===================================

For containerization and continuous integration, Docker and GitHub Actions are used.

+------------------------+--------------------------------+---------------------------------------+
| Container image        | ordec-base                     | ordec                                 |
+========================+================================+=======================================+
| Purpose                | testing, development, building | **for users**                         |
+------------------------+--------------------------------+---------------------------------------+
| ORDeC installation     | ❌ no                          | ✅ included                           |
+------------------------+--------------------------------+---------------------------------------+
| Recommended tools (1)  | ✅ included                    | ✅ included                           |
+------------------------+--------------------------------+---------------------------------------+
| Recommended PDKs (2)   | ✅ included                    | ✅ included                           |
+------------------------+--------------------------------+---------------------------------------+
| Runtime dependencies   | ✅ included                    | ✅ included                           |
+------------------------+--------------------------------+---------------------------------------+
| Test dependencies (3)  | ✅ included                    | ❌ no                                 |
+------------------------+--------------------------------+---------------------------------------+
| Build dependencies (4) | ✅ included                    | ❌ no                                 |
+------------------------+--------------------------------+---------------------------------------+
| Image size             | ~ 2 GB                         | ~ 1 GB                                |
+------------------------+--------------------------------+---------------------------------------+
| Base image             | Debian                         | Debian + ordec-base                   |
+------------------------+--------------------------------+---------------------------------------+
| Release cycle          | manual, commit hash as version | synchronized to ORDeC / PyPI versions |
+------------------------+--------------------------------+---------------------------------------+
| Build script           | /base.Dockerfile               | /Dockerfile                           |
+------------------------+--------------------------------+---------------------------------------+

(1) The included recommended tools are: Ngspice, OpenVAF
(2) The included recommended PDKs are: SKY130, IHP-Open-PDK
(3) Test dependencies are: Selenium with Chromium
(4) Build dependencies are: Npm

ordec-base Docker image
-----------------------

The custom base image `ordec-base <https://github.com/tub-msc/ordec/pkgs/container/ordec-base>`_ is used for building and testing ORDeC. It contains most build and runtime dependencies. It also includes an environment with a custom Ngspice build, PDKs and OpenVAF.

This base image prevents having to recompile the fixed environment too often. It is a bit optimized for size (e.g., build dependencies of ngspice are not in final image).

This image is automatically built through *.github/workflows/base.yaml* using *base.Dockerfile*. It can of course also be built manually using *base.Dockerfile*.

ordec Docker image
------------------

The `ordec <https://github.com/tub-msc/ordec/pkgs/container/ordec>`_ image is built on top of ordec-base. It contains an installation of ORDeC that can be run by users through a single docker command, as is described in :ref:`getting_started` and the readme file.

This image is automatically built through *.github/workflows/build.yaml* using *Dockerfile*. It can also be built manually using this *Dockerfile*.

In the future, ordec Docker images should be released in sync with the PyPI package ordec, both using git version tags (vX.Y.Z).

Automated pytest runs
---------------------

Pytest is run automatically through *.github/workflows/tests.yaml*. Here, ordec-base is used as container in which the tests are run.

There are some slight mismatches between this GitHub action and the ordec-base image (maybe this can be addressed in the future):

- While ordec-base uses the *app* user, GitHub actions seem to only work properly as the *root* user inside of a container.
- The user venv */home/app/venv*, where parts of the dependencies are installed, is reused by root.
- The directory */home/app/ordec*, where ORDeC is "supposed to go" in the logic of ordec-base, is ignored here.
