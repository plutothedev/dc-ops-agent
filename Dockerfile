FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data ./data
COPY evals ./evals
# Editable install: the data folder is found relative to the source tree.
RUN pip install --no-cache-dir -e .

ENV OLLAMA_BASE_URL=http://host.docker.internal:11434
ENTRYPOINT ["dcops"]
CMD ["scenarios"]
