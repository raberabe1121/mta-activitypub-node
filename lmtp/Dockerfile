FROM python:3.11-slim

WORKDIR /usr/local/bin

COPY ../scripts /usr/local/bin
RUN chmod +x /usr/local/bin/activitypub-*.py

EXPOSE 2626
CMD ["python", "/usr/local/bin/activitypub_lmtp_server.py"]
