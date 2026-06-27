"""
s3_client.py — Amazon S3 adapter implementing CloudStorageProvider interface.

Clean Architecture — Infrastructure Layer.
Supports multipart upload, exponential backoff retry, and streaming.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from domain.interfaces import CloudStorageProvider

logger = logging.getLogger(__name__)

# Retry configuration
RETRY_DELAYS = [5, 15, 30, 60]  # exponential backoff in seconds
MULTIPART_THRESHOLD = 50 * 1024 * 1024  # 50 MB
MULTIPART_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB per part


class S3Client(CloudStorageProvider):
    """Amazon S3 storage provider with multipart upload and retry."""

    def __init__(self, bucket_name: str, region: str = "us-east-1",
                 access_key_id: Optional[str] = None,
                 secret_access_key: Optional[str] = None):
        self._bucket = bucket_name
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._client: Any = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Initialize the S3 client using boto3."""
        try:
            import boto3
            from botocore.config import Config

            config = Config(
                region_name=self._region,
                retries={"max_attempts": 3, "mode": "adaptive"},
                connect_timeout=30,
                read_timeout=60,
            )

            if self._access_key_id and self._secret_access_key:
                self._client = boto3.client(
                    "s3",
                    aws_access_key_id=self._access_key_id,
                    aws_secret_access_key=self._secret_access_key,
                    config=config,
                )
            else:
                # Use default credential chain (IAM role, env vars, etc.)
                self._client = boto3.client("s3", config=config)

            # Verify connectivity
            self._client.head_bucket(Bucket=self._bucket)
            logger.info("Connected to S3 bucket '%s' in %s", self._bucket, self._region)
            return True

        except ImportError:
            logger.error("boto3 is not installed. Install with: pip install boto3")
            return False
        except Exception as exc:
            logger.error("S3 connection failed: %s", exc)
            self._client = None
            return False

    def is_connected(self) -> bool:
        if not self._client:
            return False
        try:
            self._client.head_bucket(Bucket=self._bucket)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(self, local_path: Path, remote_key: str) -> bool:
        """Upload a file to S3 with retry."""
        if not self._client:
            logger.error("S3 client not connected")
            return False

        for attempt, delay in enumerate(RETRY_DELAYS + [60]):
            try:
                if local_path.stat().st_size > MULTIPART_THRESHOLD:
                    return self._multipart_upload(local_path, remote_key)

                self._client.upload_file(
                    str(local_path), self._bucket, remote_key,
                    Callback=self._progress_callback(local_path.stat().st_size),
                )
                logger.info("Uploaded %s → s3://%s/%s", local_path.name, self._bucket, remote_key)
                return True

            except Exception as exc:
                logger.warning("S3 upload attempt %d failed: %s", attempt + 1, exc)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(delay)

        logger.error("S3 upload failed after all retries: %s", remote_key)
        return False

    def upload_stream(self, stream: Generator[bytes, None, None],
                      remote_key: str, content_length: int) -> bool:
        """Stream-upload data to S3 using multipart upload."""
        if not self._client:
            return False
        # TODO: Implement streaming multipart upload
        raise NotImplementedError("Streaming upload is not yet implemented.")

    def _multipart_upload(self, local_path: Path, remote_key: str) -> bool:
        """Perform multipart upload for large files."""
        try:
            import boto3.s3.transfer as transfer
            config = transfer.TransferConfig(
                multipart_threshold=MULTIPART_THRESHOLD,
                multipart_chunksize=MULTIPART_CHUNK_SIZE,
                max_concurrency=4,
            )
            self._client.upload_file(
                str(local_path), self._bucket, remote_key,
                Config=config,
                Callback=self._progress_callback(local_path.stat().st_size),
            )
            logger.info("Multipart upload complete: %s → s3://%s/%s",
                        local_path.name, self._bucket, remote_key)
            return True
        except Exception as exc:
            logger.error("Multipart upload failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download(self, remote_key: str, local_path: Path) -> bool:
        if not self._client:
            return False
        for attempt, delay in enumerate(RETRY_DELAYS + [60]):
            try:
                self._client.download_file(self._bucket, remote_key, str(local_path))
                logger.info("Downloaded s3://%s/%s → %s", self._bucket, remote_key, local_path)
                return True
            except Exception as exc:
                logger.warning("S3 download attempt %d failed: %s", attempt + 1, exc)
                if attempt < len(RETRY_DELAYS):
                    time.sleep(delay)
        return False

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_files(self, prefix: str = "") -> List[Dict[str, Any]]:
        if not self._client:
            return []
        try:
            result: List[Dict[str, Any]] = []
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                if "Contents" in page:
                    for obj in page["Contents"]:
                        result.append({
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "etag": obj["ETag"],
                        })
            return result
        except Exception as exc:
            logger.error("Error listing S3 files: %s", exc)
            return []

    def delete_file(self, remote_key: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.delete_object(Bucket=self._bucket, Key=remote_key)
            logger.info("Deleted s3://%s/%s", self._bucket, remote_key)
            return True
        except Exception as exc:
            logger.error("Error deleting S3 file: %s", exc)
            return False

    def file_exists(self, remote_key: str) -> bool:
        if not self._client:
            return False
        try:
            self._client.head_object(Bucket=self._bucket, Key=remote_key)
            return True
        except Exception:
            return False

    def get_quota(self) -> Dict[str, Any]:
        """S3 doesn't have a traditional quota — return bucket info."""
        if not self._client:
            return {}
        try:
            info = self._client.get_bucket_location(Bucket=self._bucket)
            return {
                "bucket": self._bucket,
                "region": info.get("LocationConstraint", self._region),
                "total_bytes": -1,  # S3 is virtually unlimited
                "used_bytes": -1,
            }
        except Exception as exc:
            logger.error("Error getting S3 bucket info: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _progress_callback(total_bytes: int):
        """Return a progress callback for tqdm or similar.

        TODO: Integrate with rich progress bar.
        """
        def callback(bytes_transferred: int) -> None:
            if total_bytes > 0:
                pct = (bytes_transferred / total_bytes) * 100
                if pct % 10 == 0:  # Log every 10%
                    logger.debug("Upload progress: %.1f%% (%d/%d bytes)",
                                 pct, bytes_transferred, total_bytes)
        return callback
