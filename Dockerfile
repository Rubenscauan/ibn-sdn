FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt requirements-benchmark.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements-benchmark.txt

COPY ibn_sdn/ ibn_sdn/
COPY examples/ examples/
COPY knowledge/ knowledge/
COPY benchmark.py ./

ENTRYPOINT ["python", "/app/benchmark.py"]
CMD ["--scenarios", "examples/benchmark_scenarios.json", "--requests", "12", "--repetitions", "2", "--warmup", "3"]
