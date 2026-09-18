# Bootstrap candidate only. Resolve and record the base image digest on the target builder.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY rcwg_boot /app/rcwg_boot
USER 65532:65532
CMD ["python", "-m", "rcwg_boot.cloud"]
