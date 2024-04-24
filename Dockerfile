FROM thehale/python-poetry:1.8.2-py3.10-slim

COPY . /app
WORKDIR /app

RUN apt-get update && apt-get install -y openssh-client ntp
RUN poetry install

EXPOSE 8080

CMD ["poetry", "run", "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "threadmem.server.app:app", "--workers=4", "--bind", "0.0.0.0:8080", "--log-level", "debug", "--log-config", "logging.conf", "--timeout", "240"]

