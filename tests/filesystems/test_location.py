"""base.py and filesystems/locations.py: locations compare equal when they
name the same item, have URLs, and travel as JSON."""

from __future__ import annotations

import dataclasses

import pytest

from jupyter_storage_explorer import Location
from jupyter_storage_explorer.filesystems.locations import (
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
    FsspecLocation(url="ftp://h/dir/a.csv"),
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
        assert LocalLocation(path="/dir/", hostname="H") == LocalLocation(
            path="/dir", hostname="h"
        )

    def test_hashable(self):
        assert len({*LOCATIONS, *LOCATIONS}) == len(LOCATIONS)

    def test_immutable(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            LOCATIONS[0].path = "x"

    def test_other_fields_other_locations(self):
        """Same URL, other places: S3 on AWS and on an S3-compatible store."""
        aws, minio = LOCATIONS[1], LOCATIONS[2]
        assert aws.url == minio.url
        assert aws != minio


class TestUrls:
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

    def test_protocols_from_urls(self):
        assert [location.protocol for location in LOCATIONS] == [
            "abfs",
            "s3",
            "s3",
            "gs",
            "sftp",
            "file",
            "file",
            "memory",
            "ftp",
        ]

    @pytest.mark.parametrize(
        ("location", "url"),
        [
            (S3Location(), "s3://"),
            (S3Location(bucket="b"), "s3://b"),
            (AbfsLocation(account_name="a"), "abfs://"),
            (LocalLocation(path="C:/", hostname="h"), "file:///C:/"),
            (LocalLocation(path="/", hostname="h"), "file:///"),
        ],
    )
    def test_tops(self, location, url):
        assert location.url == url

    def test_local_paths_in_the_systems_form(self, tmp_path):
        fsspec_path = tmp_path.as_posix()
        assert LocalLocation(path=fsspec_path, hostname="h").os_path == str(tmp_path)


class TestJson:
    @pytest.mark.parametrize("location", LOCATIONS)
    def test_round_trip(self, location):
        data = location.to_json()
        assert (data["kind"], data["url"]) == (location.kind, location.url)
        assert Location.from_json(data) == location

    def test_unknown_kind_is_an_fsspec_url(self):
        """Another kernel's own kind: looked for among this one's storages only."""
        location = Location.from_json({"kind": "elsewhere", "url": "myfs://x"})
        assert location == FsspecLocation(url="myfs://x")

    def test_the_url_of_a_known_kind_comes_from_its_fields(self):
        """An http URL sent as an S3 location: the URL comes from the fields."""
        location = Location.from_json(
            {"kind": "s3", "url": "http://169.254.169.254/latest/", "bucket": "b"}
        )
        assert location.url == "s3://b"

    @pytest.mark.parametrize(
        "data",
        [
            None,
            "s3://b/k",
            {"bucket": "b"},
            {"kind": "s3", "bucket": ["b"]},
            {"kind": "sftp", "path": "/x"},  # no host
            {"kind": "file", "path": None, "hostname": "h"},
            {"kind": "elsewhere"},  # no URL
        ],
    )
    def test_refused(self, data):
        with pytest.raises(ValueError):
            Location.from_json(data)
