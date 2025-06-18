# Install/build ORDeC + run web interface using ordec-base (base.Dockerfile) as base image.

FROM ghcr.io/tub-msc/ordec-base:sha-4084a85 AS ordec

# Install ORDeC core (Python):
WORKDIR /home/app/ordec
COPY --chown=app . .
RUN pip install -e ".[test]"

# Web interface NPM build:
WORKDIR /home/app/ordec/web
# Update install in case the base image is missing something:
RUN npm install
RUN npm run build

# Run web interface:
WORKDIR /home/app/ordec
ENV PATH_ORIG="$PATH"
ENV PATH="/home/app/openvaf:/home/app/ngspice/min/bin:$PATH_ORIG"
EXPOSE 8100
CMD ["ordec-server", "-l", "0.0.0.0", "-p", "8100", "-r", "web/dist/"]
