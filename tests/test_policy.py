"""policy.py: the rules of the directions files may be copied and moved in."""

from __future__ import annotations

import pytest

from jupyter_storage_explorer.policy import (
    TransferPolicy,
    computer_url,
    jupyterlab_url,
)


class TestAllows:
    def test_allowed_without_rules(self):
        assert TransferPolicy().allows("s3://a/x", "/home/me/x")
        assert TransferPolicy([]).allows("s3://a/x", "/home/me/x")

    def test_first_matching_rule_decides(self):
        policy = TransferPolicy(
            [
                {"rule": "allow", "src": r"s3://lake/public/.*", "dest": ".*"},
                {"rule": "deny", "src": r"s3://lake/.*", "dest": ".*"},
            ]
        )
        assert policy.allows("s3://lake/public/a.csv", "/tmp/a.csv")
        assert not policy.allows("s3://lake/private/a.csv", "/tmp/a.csv")
        assert policy.allows("s3://other/a.csv", "/tmp/a.csv")  # no rule matches

    def test_both_patterns_must_match(self):
        policy = TransferPolicy(
            [{"rule": "deny", "src": "s3://.*", "dest": "/home/.*"}]
        )
        assert not policy.allows("s3://a/x", "/home/me/x")
        assert policy.allows("s3://a/x", "/tmp/x")
        assert policy.allows("gs://a/x", "/home/me/x")

    def test_whole_urls_match(self):
        policy = TransferPolicy([{"rule": "deny", "src": "s3://a", "dest": ".*"}])
        assert policy.allows("s3://a/x", "/tmp/x")  # "s3://a" is only a prefix
        assert not policy.allows("s3://a", "/tmp/x")

    def test_pattern_left_out_matches_any(self):
        policy = TransferPolicy([{"rule": "deny", "dest": computer_url(".*")}])
        assert not policy.allows("s3://a/x", "browser:///x")
        assert policy.allows("s3://a/x", "/tmp/x")

    def test_error_names_the_urls(self):
        policy = TransferPolicy([{"rule": "deny"}])
        assert policy.error("s3://a/x", "/tmp/x") == (
            "not allowed by the policy (s3://a/x → /tmp/x)"
        )
        assert TransferPolicy().error("s3://a/x", "/tmp/x") is None


@pytest.mark.parametrize(
    ("path", "url"),
    [
        ("/home/jovyan/x.csv", "jupyterlab:///home/jovyan/x.csv"),
        ("C:/Users/me/x.csv", "jupyterlab:///C:/Users/me/x.csv"),
        ("C:\\Users\\me\\x.csv", "jupyterlab:///C:/Users/me/x.csv"),
    ],
)
def test_jupyterlab_url(path, url):
    assert jupyterlab_url(path) == url


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ({"rule": "deny"}, "must be a list of rules"),
        ("deny", "must be a list of rules"),
        ([["deny", ".*", ".*"]], "policy rule 0: must be a dict"),
        ([{"rule": "block"}], 'policy rule 0: "rule" must be "allow" or "deny"'),
        (
            [{"rule": "deny"}, {"rule": "deny", "source": ".*"}],
            "policy rule 1: unknown keys",
        ),
        ([{"rule": "deny", "src": 3}], "'src' must be a regular expression"),
        ([{"rule": "deny", "dest": "("}], "'dest' is not a regular expression"),
    ],
)
def test_invalid_rules(rules, message):
    with pytest.raises(ValueError, match=message):
        TransferPolicy(rules)
