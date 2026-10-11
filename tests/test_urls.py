"""_urls.default_url: the locations shown to users and given to libraries."""

from __future__ import annotations

import fsspec
import pytest

from jupyter_storage_explorer._urls import default_url


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
