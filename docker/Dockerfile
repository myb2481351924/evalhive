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
CMD ["evalhive", "serve", "--host", "0.0.0.0", "--port", "8000"]
