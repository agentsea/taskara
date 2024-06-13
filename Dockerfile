FROM python:3.10-slim-buster

RUN apt-get update && apt-get install -y openssh-client ntp gcc python3-dev

RUN pip install poetry

COPY . /app
WORKDIR /app

RUN poetry install

EXPOSE 9070
CMD ["poetry", "run", "python", "-m", "taskara.server.app"]