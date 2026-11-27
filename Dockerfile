# For a cloud build, supply an approved base image digest via PYTHON_IMAGE.
# The default is for local development only.
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY drift_lab /app/drift_lab
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "drift_lab", "serve", "--host", "0.0.0.0"]
