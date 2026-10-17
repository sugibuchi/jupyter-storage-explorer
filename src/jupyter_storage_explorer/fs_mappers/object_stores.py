"""Object stores whose buckets are their file systems: Amazon S3 and
S3-compatible stores (s3fs), Google Cloud Storage (gcsfs)."""

from __future__ import annotations

import urllib.parse
from typing import TYPE_CHECKING, Any

from jupyter_storage_explorer.fs_mappers.base import FileSystemMapper, split_url

if TYPE_CHECKING:
    from fsspec import AbstractFileSystem


class _BucketMapper(FileSystemMapper):
    """Paths are "bucket/key", URLs ``<scheme>://bucket/key`` for each of
    ``schemes``, the first one made."""

    schemes: tuple[str, ...] = ()

    def to_url(self, fs: AbstractFileSystem, path: str) -> str:
        return f"{self.schemes[0]}://{path.lstrip('/')}"

    def path_of(self, fs: AbstractFileSystem, url: str) -> str | None:
        scheme, bucket, key = split_url(url)
        if scheme not in self.schemes:
            return None
        return f"{bucket}/{key.strip('/')}".strip("/")


class S3Mapper(_BucketMapper):
    """s3fs's ``S3FileSystem``, which reaches the buckets of one endpoint.

    Its identifier is the endpoint, ``{"endpoint": "http://minio:9000"}``,
    when one is set (S3-compatible stores), else the AWS partition, e.g.
    ``{"partition": "aws"}``, within which bucket names are unique (from
    the region set, if any). URLs are ``s3://bucket/key``; ``s3a://`` (Spark's)
    are read too. They do not name an endpoint, so an S3-compatible store
    is reached from another kernel only if its explorer has it.
    """

    protocol = "s3"
    classes = ("s3fs.core.S3FileSystem",)
    schemes = ("s3", "s3a")

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        client_kwargs = getattr(fs, "client_kwargs", None) or {}
        endpoint = getattr(fs, "endpoint_url", None) or client_kwargs.get(
            "endpoint_url"
        )
        if endpoint:
            return {"endpoint": _origin(endpoint)}
        region = client_kwargs.get("region_name") or ""
        if region.startswith("cn-"):
            return {"partition": "aws-cn"}
        if region.startswith("us-gov-"):
            return {"partition": "aws-us-gov"}
        return {"partition": "aws"}


class GCSMapper(_BucketMapper):
    """gcsfs's ``GCSFileSystem``. Bucket names are unique in Google Cloud
    Storage, so its identifier is empty, ``{}``, except with another
    endpoint (an emulator): ``{"endpoint": ...}``. URLs are ``gs://bucket/key``;
    ``gcs://`` are read too."""

    protocol = "gs"
    classes = ("gcsfs.core.GCSFileSystem",)
    schemes = ("gs", "gcs")

    def identifier(self, fs: AbstractFileSystem) -> dict[str, Any]:
        endpoint = getattr(fs, "_endpoint", None) or ""
        if not endpoint or _origin(endpoint) == "https://storage.googleapis.com":
            return {}
        return {"endpoint": _origin(endpoint)}


def _origin(url: str) -> str:
    """``scheme://host[:port]`` of ``url``, in lower case: the same endpoint
    written two ways compares equal."""
    parts = urllib.parse.urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}".lower()
