FROM python:3.11-slim

WORKDIR /workspace
COPY train.py /opt/train.py

ENTRYPOINT ["python", "/opt/train.py"]
CMD ["--config", "/workspace/config.json"]
