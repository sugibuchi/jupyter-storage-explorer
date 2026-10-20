"""location.py and filesystems/locations.py: locations compare equal when they
name the same item, move through paths, and travel as JSON."""

from __future__ import annotations

import dataclasses

import pytest

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems import (
    AbfsLocation,
    FsspecLocation,
    GcsLocation,
    LocalLocation,
    MemoryLocation,
    S3Location,
    SftpLocation,
)

LOCATIONS = [
    AbfsLocation(account_name="acct", container_name="c", path="dir/a.csv"),
    S3Location(bucket="b", key="dir/a.csv"),
    S3Location(bucket="b", key="dir/a.csv", endpoint="http://minio:9000"),
    GcsLocation(bucket="b", key="dir/a.csv"),
    SftpLocation(host="h", port=2222, user="u", path="/dir/a.csv"),
    LocalLocation(path="/dir/a.csv", hostname="h", machine_id="m"),
    LocalLocation(path="C:/dir/a.csv", hostname="h"),
    MemoryLocation(path="/dir/a.csv", process="p"),
    FsspecLocation(fsspec_protocol="ftp", fsspec_url="ftp://h/dir/a.csv"),
]


class TestEquality:
    def test_normalized(self):
        assert AbfsLocation(
            account_name="ACCT", container_name="c", path="/dir/a.csv/"
        ) == AbfsLocation(account_name="acct", container_name="c", path="dir/a.csv")
        assert S3Location(bucket="b", key="k", endpoint="HTTP://MinIO:9000/x") == (
            S3Location(bucket="b", key="k", endpoint="http://minio:9000")
        )
        assert SftpLocation(host="Host", path="dir/") == SftpLocation(
            host="host", path="/dir"
        )

    def test_hashable(self):
        assert len({*LOCATIONS, *LOCATIONS}) == len(LOCATIONS)

    def test_immutable(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            LOCATIONS[0].path = "x"

    def test_kinds_are_never_equal(self):
        """Same URL, other storages: S3 on AWS and on an S3-compatible store."""
        aws, minio = LOCATIONS[1], LOCATIONS[2]
        assert aws.url == minio.url
        assert aws != minio and aws.storage != minio.storage


class TestPaths:
    @pytest.mark.parametrize("location", LOCATIONS)
    def test_name_parent_and_join(self, location):
        assert location.name == "a.csv"
        assert location.parent.name == "dir"
        assert location.parent.join("a.csv") == location
        assert location.parent.join("x", "/y/") == location.parent.join("x").join("y")

    @pytest.mark.parametrize(
        ("location", "top"),
        [
            (LocalLocation(path="/dir", hostname="h"), "/"),
            (LocalLocation(path="C:/dir", hostname="h"), "C:/"),
            (SftpLocation(host="h", path="/dir"), "/"),
            (MemoryLocation(path="/dir", process="p"), "/"),
        ],
    )
    def test_the_top_is_its_own_parent(self, location, top):
        assert location.parent.path == top
        assert location.parent.parent == location.parent
        assert location.parent.join("dir") == location

    def test_buckets_are_part_of_the_path(self):
        key = S3Location(bucket="b", key="k")
        assert key.parent == S3Location(bucket="b")
        assert key.parent.parent == S3Location()
        assert S3Location().join("b", "k") == key

    def test_urls(self):
        assert [location.url for location in LOCATIONS] == [
            "abfs://c@acct.dfs.core.windows.net/dir/a.csv",
            "s3://b/dir/a.csv",
            "s3://b/dir/a.csv",
            "gs://b/dir/a.csv",
            "sftp://u@h:2222/dir/a.csv",
            "file:///dir/a.csv",
            "file:///C:/dir/a.csv",
            "memory:///dir/a.csv",
            "ftp://h/dir/a.csv",
        ]


class TestJson:
    @pytest.mark.parametrize("location", LOCATIONS)
    def test_round_trip(self, location):
        data = location.to_json()
        assert (data["protocol"], data["url"]) == (location.protocol, location.url)
        assert Location.from_json(data) == location

    def test_unknown_kind_is_an_fsspec_url(self):
        """Another kernel's own kind: looked for among this one's storages only."""
        location = Location.from_json(
            {"kind": "elsewhere", "protocol": "myfs", "url": "myfs://x"}
        )
        assert location == FsspecLocation(fsspec_protocol="myfs", fsspec_url="myfs://x")

    @pytest.mark.parametrize(
        "data",
        [
            None,
            "s3://b/k",
            {"bucket": "b"},
            {"kind": "s3", "bucket": ["b"]},
            {"kind": "sftp", "path": "/x"},  # no host
            {"kind": "file", "path": None, "hostname": "h"},
        ],
    )
    def test_refused(self, data):
        with pytest.raises(ValueError):
            Location.from_json(data)
