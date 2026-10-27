"""AWS operations helpers. Use the instance role; never print runtime secrets."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import ssl
import tarfile
import time
import urllib.request
from pathlib import Path

import boto3


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def age_hours(path, now=None):
    try:
        stamp = float(Path(path).read_text().strip())
        return max(0, ((time.time() if now is None else now) - stamp) / 3600)
    except (OSError, ValueError):
        return 999999.0


def healthy(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return int(json.load(response).get("status") == "ok")
    except Exception:
        return 0


def extract_database(bundle, destination):
    # Never extract the secret-bearing .env or arbitrary archive paths in drills.
    with tarfile.open(bundle, "r:gz") as archive:
        member = archive.getmember("database.dump")
        if not member.isfile():
            raise ValueError("database.dump is not a regular file")
        with archive.extractfile(member) as source, Path(destination).open("wb") as target:
            shutil.copyfileobj(source, target)


def s3_client():
    return boto3.client("s3", region_name=os.environ["S3_REGION"])


def upload(path):
    path = Path(path)
    checksum = digest(path)
    key = "backups/" + path.name
    client = s3_client()
    bucket = os.environ["BACKUP_BUCKET"]
    client.upload_file(str(path), bucket, key, ExtraArgs={
        "ServerSideEncryption": "AES256", "Metadata": {"sha256": checksum},
    })
    remote = client.head_object(Bucket=bucket, Key=key)
    if remote["ContentLength"] != path.stat().st_size or remote["Metadata"].get("sha256") != checksum:
        raise RuntimeError("Backup upload verification failed")
    print(key)


def download(key, path):
    if not key.startswith("backups/") or not key.endswith(".tar.gz"):
        raise ValueError("Unexpected backup object key")
    client = s3_client()
    bucket = os.environ["BACKUP_BUCKET"]
    remote = client.head_object(Bucket=bucket, Key=key)
    client.download_file(bucket, key, path)
    if digest(path) != remote.get("Metadata", {}).get("sha256"):
        raise RuntimeError("Backup checksum mismatch")


def latest():
    newest = None
    for page in s3_client().get_paginator("list_objects_v2").paginate(
        Bucket=os.environ["BACKUP_BUCKET"], Prefix="backups/",
    ):
        for item in page.get("Contents", []):
            if item["Key"].endswith(".tar.gz") and (newest is None or item["LastModified"] > newest["LastModified"]):
                newest = item
    if newest is None:
        raise RuntimeError("No off-site backup exists")
    print(newest["Key"])


def monitor(args):
    state = Path("/data/backups/state")
    values = {
        "ApplicationHealthy": healthy("http://localhost:8000/api/health"),
        "PublicHTTPSHealthy": healthy(f"https://{args.domain}/api/health"),
        "DiskUsedPercent": args.disk,
        "MemoryUsedPercent": args.memory,
        "BackupAgeHours": age_hours(state / "backup-success"),
        "RestoreCheckAgeHours": age_hours(state / "restore-success"),
        "TLSExpiryDays": 0,
    }
    try:
        with socket.create_connection((args.domain, 443), timeout=10) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=args.domain) as tls:
                values["TLSExpiryDays"] = max(0, (ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"]) - time.time()) / 86400)
    except Exception:
        pass
    region = os.environ["S3_REGION"]
    boto3.client("cloudwatch", region_name=region).put_metric_data(
        Namespace="IsoSafe/Operations", MetricData=[{
            "MetricName": name, "Value": value,
            "Dimensions": [{"Name": "InstanceId", "Value": args.instance_id}],
        } for name, value in values.items()],
    )
    logs = boto3.client("logs", region_name=region)
    group = os.environ["OPS_LOG_GROUP"]
    try:
        logs.create_log_stream(logGroupName=group, logStreamName=args.instance_id)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_log_events(logGroupName=group, logStreamName=args.instance_id, logEvents=[{
        "timestamp": int(time.time() * 1000), "message": json.dumps(values),
    }])
    print(json.dumps(values))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("latest")
    up = sub.add_parser("upload")
    up.add_argument("path")
    down = sub.add_parser("download")
    down.add_argument("key")
    down.add_argument("path")
    extract = sub.add_parser("extract-db")
    extract.add_argument("bundle")
    extract.add_argument("destination")
    mon = sub.add_parser("monitor")
    mon.add_argument("--domain", required=True)
    mon.add_argument("--instance-id", required=True)
    mon.add_argument("--disk", type=float, required=True)
    mon.add_argument("--memory", type=float, required=True)
    args = parser.parse_args()
    if args.command == "upload":
        upload(args.path)
    elif args.command == "download":
        download(args.key, args.path)
    elif args.command == "extract-db":
        extract_database(args.bundle, args.destination)
    elif args.command == "latest":
        latest()
    else:
        monitor(args)


if __name__ == "__main__":
    main()
