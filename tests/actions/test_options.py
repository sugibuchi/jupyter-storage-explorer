"""Actions' options by themselves (``ActionOptions``, and util.py's secret
fields and ``LIBRARY_DEFAULT``): their names, secrets left out of generated
code, and the options that are a library's arguments."""

from __future__ import annotations

import copy
import dataclasses
import pickle

from jupyter_storage_explorer.actions import ActionOptions
from jupyter_storage_explorer.util import (
    LIBRARY_DEFAULT,
    LibraryDefault,
    format_arguments,
    secret_dict_field,
    secret_field,
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class SecretOptions(ActionOptions):
    password: str | None = secret_field(default=None)
    storage_options: dict | None = secret_dict_field(
        default=None, secret_keys=["shared_key"]
    )
    version: int = 1
    engine: object = None


def test_option_names():
    assert ActionOptions.option_names() == frozenset()
    assert SecretOptions.option_names() == {
        "password",
        "storage_options",
        "version",
        "engine",
    }


class TestSecrets:
    """Options marked secret never reach generated code (``code_value``)."""

    def test_secret_field(self):
        options = SecretOptions(password="hunter2")
        assert options.code_value("password") is None
        assert "hunter2" not in repr(options)  # nor tracebacks and logs

    def test_secret_keys_at_any_depth(self):
        options = SecretOptions(
            storage_options={
                "shared_key": "s1",
                "account_name": "acct",
                "client_kwargs": {"shared_key": "s2", "endpoint_url": "http://e"},
            }
        )
        assert options.code_value("storage_options") == {
            "account_name": "acct",
            "client_kwargs": {"endpoint_url": "http://e"},
        }

    def test_credential_like_keys_left_out_anyway(self):
        # Not declared, but named like a credential.
        options = SecretOptions(storage_options={"sas_token": "t", "shared_key": "k"})
        assert options.code_value("storage_options") is None  # nothing left

    def test_plain_values(self):
        options = SecretOptions(version=2, engine=object())
        assert options.code_value("version") == 2
        assert options.code_value("engine") is None  # not plain data

    def test_metadata_kept(self):
        [field] = [
            f for f in dataclasses.fields(SecretOptions) if f.name == "storage_options"
        ]
        assert field.metadata["secret_keys"] == ("shared_key",)


@dataclasses.dataclass(frozen=True, kw_only=True)
class ReaderOptions(ActionOptions):
    storage_options: dict | None = None  # not an argument: no LIBRARY_DEFAULT
    header: bool | LibraryDefault = LIBRARY_DEFAULT
    quote: str | LibraryDefault | None = LIBRARY_DEFAULT
    dtype: object = LIBRARY_DEFAULT
    token: str | LibraryDefault | None = secret_field(default=LIBRARY_DEFAULT)


class TestArguments:
    """Options that are a library's arguments (``LIBRARY_DEFAULT``)."""

    def test_only_those_given(self):
        assert ReaderOptions(storage_options={"a": 1}).arguments() == {}
        assert ReaderOptions(header=False, quote=None).arguments() == {
            "header": False,
            "quote": None,  # a value given, unlike LIBRARY_DEFAULT
        }

    def test_in_the_code(self):
        options = ReaderOptions(quote=None, dtype=object(), token="t")
        # None kept; objects and secrets left out.
        assert options.code_arguments() == {"quote": None}
        assert format_arguments(options.code_arguments()) == ", quote=None"

    def test_one_object(self):
        assert copy.deepcopy(LIBRARY_DEFAULT) is LIBRARY_DEFAULT
        assert pickle.loads(pickle.dumps(LIBRARY_DEFAULT)) is LIBRARY_DEFAULT
        assert repr(LIBRARY_DEFAULT) == "LIBRARY_DEFAULT"
