FROM python:3.11-bookworm
RUN apt-get update
RUN apt-get -y install libcairo2-dev build-essential fonts-inconsolata libgirepository1.0-dev gir1.2-pango-1.0 ngspice npm
RUN useradd -ms /bin/bash app

WORKDIR /usr/local/app
RUN pip install "PyGObject==3.42.2" pytest pytest-cov
COPY pyproject.toml ./
COPY pytest.ini ./
COPY ordec/ ./ordec
COPY tests/ ./tests
COPY web/ ./web

RUN pip install -e .
WORKDIR /usr/local/app/web
RUN npm install
RUN npm run build
WORKDIR /usr/local/app

USER app
EXPOSE 8100
CMD ["ordec-server", "-l", "0.0.0.0", "-p", "8100", "-r", "web/dist/"]
