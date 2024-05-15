FROM us-central1-docker.pkg.dev/agentsea-dev/core/poetry:latest

COPY . /app
WORKDIR /app

RUN apt-get update && apt-get install -y openssh-client ntp
RUN poetry install

EXPOSE 9070

CMD ["poetry", "run", "python", "-m", "taskara.server.app"]

