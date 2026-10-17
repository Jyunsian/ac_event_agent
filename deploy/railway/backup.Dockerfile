FROM postgres:16-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/backup && /opt/backup/bin/pip install --no-cache-dir boto3==1.42.39
COPY deploy/railway/backup.py /opt/backup.py
USER postgres
ENTRYPOINT ["/opt/backup/bin/python", "/opt/backup.py"]
