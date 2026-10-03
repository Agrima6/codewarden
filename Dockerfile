FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web,langchain]"
RUN useradd --create-home warden
USER warden
WORKDIR /work
ENTRYPOINT ["codewarden"]
