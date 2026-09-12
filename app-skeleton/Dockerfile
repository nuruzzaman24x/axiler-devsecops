# Small, deliberately simple image. In the CI/CD stage this image will
# additionally be scanned (Trivy), have an SBOM generated (Syft), and be
# signed (cosign) before it's considered a trusted, deployable artifact.

FROM python:3.12-slim

# Run as non-root — a basic least-privilege measure at the container level.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /home/appuser/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()" || exit 1

CMD ["python", "app/main.py"]
