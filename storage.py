"""
storage.py — Cloudflare R2 file storage for Lens League Apex
Drop-in wrapper around boto3 S3 client pointed at R2.
All uploads go to R2; public URLs are served directly from R2.
"""

import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from boto3.s3.transfer import TransferConfig

# ---------------------------------------------------------------------------
# R2 client — initialised once at import time
# ---------------------------------------------------------------------------

def _make_client():
    account_id   = os.getenv('R2_ACCOUNT_ID', '')
    access_key   = os.getenv('R2_ACCESS_KEY_ID', '')
    secret_key   = os.getenv('R2_SECRET_ACCESS_KEY', '')
    if not all([account_id, access_key, secret_key]):
        return None
    return boto3.client(
        's3',
        endpoint_url            = f'https://{account_id}.r2.cloudflarestorage.com',
        aws_access_key_id       = access_key,
        aws_secret_access_key   = secret_key,
        config                  = Config(signature_version='s3v4'),
        region_name             = 'auto',
    )

_client = None

def get_client():
    global _client
    if _client is None:
        _client = _make_client()
    return _client


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

BUCKET = os.getenv('R2_BUCKET_NAME', 'lens-league-apex')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', '').rstrip('/')   # e.g. https://pub-xxx.r2.dev


def upload_file(local_path: str, object_key: str, content_type: str = 'image/jpeg') -> str | None:
    """
    Upload a local file to R2.
    Returns the public URL on success, None on failure.
    object_key example: 'thumbs/abc123.jpg'
    """
    client = get_client()
    if client is None:
        print('[R2] Client not configured — check R2_* env vars.')
        return None
    try:
        client.upload_file(
            local_path,
            BUCKET,
            object_key,
            ExtraArgs={'ContentType': content_type},
        )
        return f'{R2_PUBLIC_URL}/{object_key}'
    except ClientError as e:
        print(f'[R2] Upload failed for {object_key}: {e}')
        return None


def upload_fileobj(fileobj, object_key: str, content_type: str = 'image/jpeg') -> str | None:
    """Upload a file-like object directly (no temp file needed).
    Uses multipart transfer for files > 10 MB (e.g. RAW files).
    """
    client = get_client()
    if client is None:
        return None
    try:
        config = TransferConfig(
            multipart_threshold = 10 * 1024 * 1024,   # 10 MB — RAW files go multipart
            multipart_chunksize = 10 * 1024 * 1024,   # 10 MB chunks
            max_concurrency     = 2,                   # conservative for Railway
            use_threads         = True,
        )
        client.upload_fileobj(
            fileobj,
            BUCKET,
            object_key,
            ExtraArgs={'ContentType': content_type},
            Config=config,
        )
        return f'{R2_PUBLIC_URL}/{object_key}'
    except ClientError as e:
        print(f'[R2] Upload failed for {object_key}: {e}')
        return None


def delete_file(object_key: str) -> bool:
    """Delete an object from R2. Returns True on success."""
    client = get_client()
    if client is None:
        return False
    try:
        client.delete_object(Bucket=BUCKET, Key=object_key)
        return True
    except ClientError as e:
        print(f'[R2] Delete failed for {object_key}: {e}')
        return False


def public_url(object_key: str) -> str:
    """Return the public URL for an object key."""
    return f'{R2_PUBLIC_URL}/{object_key}'
