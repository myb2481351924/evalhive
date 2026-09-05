FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# example configs + dataset fixtures for the offline demo
COPY examples ./examples
COPY web ./web

EXPOSE 8000
VOLUME ["/app/.evalhive"]
# Render/Railway inject $PORT; local runs default to 8000
CMD ["sh", "-c", "evalhive serve --host 0.0.0.0 --port ${PORT:-8000}"]
