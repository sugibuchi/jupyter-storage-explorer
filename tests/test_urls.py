"""_urls: the locations shown to users and given to libraries, and back."""

from __future__ import annotations

import fsspec
import pytest
from fsspec.implementations.dirfs import DirFileSystem

from jupyter_storage_explorer._urls import default_location, default_url


class FakeAzure:
    """Just what default_url reads from an adlfs filesystem."""

    protocol = ("abfs", "az")

    def __init__(self, account_url: str | None) -> None:
        self.account_url = account_url

    def unstrip_protocol(self, path: str) -> str:
        return f"abfs://{path}"


def test_local_paths_stay_plain(tmp_path):
    fs = fsspec.filesystem("file")
    assert default_url(fs, str(tmp_path)) == str(tmp_path)


def test_other_protocols(memfs):
    assert default_url(memfs, "/a/b.csv") == "memory:///a/b.csv"


def test_azure_names_the_account():
    fs = FakeAzure("https://myaccount.blob.core.windows.net")
    assert (
        default_url(fs, "lake/raw/x.csv")
        == "abfs://lake@myaccount.dfs.core.windows.net/raw/x.csv"
    )


def test_azure_other_cloud_keeps_its_domain():
    fs = FakeAzure("https://acc.blob.core.chinacloudapi.cn/")
    assert default_url(fs, "c/k") == "abfs://c@acc.dfs.core.chinacloudapi.cn/k"


@pytest.mark.parametrize(
    "account_url", [None, "http://127.0.0.1:10000/devstoreaccount1"]
)
def test_azure_without_known_host(account_url):
    assert default_url(FakeAzure(account_url), "c/k") == "abfs://c/k"


class TestDefaultLocation:
    """default_location: the reverse of default_url."""

    def test_round_trip(self, memfs, tmp_path):
        local = fsspec.filesystem("file")
        for fs, path in [
            (memfs, "/a/b.csv"),
            (local, local._strip_protocol(str(tmp_path))),
        ]:
            assert default_location(default_url(fs, path), [fs]) == (fs, path)

    def test_the_first_with_the_protocol(self, memfs):
        other = DirFileSystem("/sub", memfs)
        local = fsspec.filesystem("file")
        assert default_location("memory:///x", [local, other, memfs]) == (memfs, "/x")

    def test_else_opened_by_fsspec(self, memfs):
        fs, path = default_location("memory:///x", [])
        assert fs is memfs and path == "/x"

    def test_azure_by_account(self):
        lake = FakeAzure("https://lake.blob.core.windows.net")
        other = FakeAzure("https://other.blob.core.windows.net")
        url = "abfs://data@lake.dfs.core.windows.net/raw/x.csv"
        assert default_location(url, [other, lake]) == (lake, "data/raw/x.csv")
        assert default_url(lake, "data/raw/x.csv") == url

    @pytest.mark.parametrize(
        "url", ["abfs://data/raw/x.csv", "abfs://", "dir:///sub/x.csv"]
    )
    def test_unknown_storage_refused(self, url):
        lake = FakeAzure("https://lake.blob.core.windows.net")
        with pytest.raises(ValueError, match="unknown"):
            default_location(url, [lake])
