.. _containers_and_ci:

Containers & continuous integration
===================================

For containerization and continuous integration, Docker and GitHub Actions are used.

ordec-base Docker image
-----------------------

The custom base image `ordec-base <https://github.com/tub-msc/ordec/pkgs/container/ordec-base>`_ is used for building and testing ORDeC in the subsequent stages. It contains all (or most) dependencies, including a custom Ngspice build. In the future, PDKs and OpenVAF will also be included in the base image.

This base image prevents having to recompile the fixed environment too often. Additionally, it is somwhat optimized for size (e.g., build dependencies of ngspice are not in final image).

This image is automatically built through *.github/workflows/base.yaml* using *base.Dockerfile*. It can of course also be built manually using *base.Dockerfile*.

ordec Docker image
------------------

The `ordec <https://github.com/tub-msc/ordec/pkgs/container/ordec>`_ image is built on top of ordec-base. Its default run command starts the web interface on port 8100. This image makes it possible to install + run ORDeC through a single docker command, as is described in :ref:`getting_started` and the readme file.

This image is automatically built through *.github/workflows/build.yaml* using *Dockerfile*. It can also be built manually using this *Dockerfile*.

Automated pytest runs
---------------------

Pytest is run automatically through *.github/workflows/tests.yaml*. Here, ordec-base is used as container in which the tests are run.

There are some slight mismatches between this GitHub action and the ordec-base image (maybe this can be addressed in the future):

- While ordec-base uses the *app* user, GitHub actions seem to only work properly as the *root* user inside of a container.
- The user venv */home/app/venv*, where parts of the dependencies are installed, is reused by root.
- The directory */home/app/ordec*, where ORDeC is "supposed to go" in the logic of ordec-base, is ignored here.
