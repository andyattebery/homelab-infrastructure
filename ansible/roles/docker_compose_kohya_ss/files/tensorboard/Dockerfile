FROM python:3.11-slim
RUN pip install --no-cache-dir tensorboard
EXPOSE 6006
CMD ["tensorboard", "--logdir=/app/logs", "--bind_all"]
