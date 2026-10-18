"""_jobs/transfer_policy.py: the rules of the directions files may be copied and moved in."""

from __future__ import annotations

import pytest

from jupyter_storage_explorer._jobs.transfer_policy import (
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
            "not allowed by the transfer policy (s3://a/x → /tmp/x)"
        )
        assert TransferPolicy().error("s3://a/x", "/tmp/x") is None


LAKE = r"abfs://(?P<container>[^@/]+)@lake\.dfs\.core\.windows\.net/"


class TestNamedGroups:
    """Named groups tie the source and the destination together."""

    def test_same_text_in_both(self):
        policy = TransferPolicy(
            [
                {"rule": "allow", "src": LAKE + ".*", "dest": LAKE + ".*"},
                # Without the group: "dest" has none.
                {
                    "rule": "deny",
                    "src": r"abfs://[^@/]+@lake\.dfs\.core\.windows\.net/.*",
                },
            ]
        )
        url = "abfs://{}@lake.dfs.core.windows.net/{}".format
        assert policy.allows(url("raw", "a.csv"), url("raw", "b/a.csv"))
        assert not policy.allows(url("raw", "a.csv"), url("curated", "a.csv"))
        assert not policy.allows(url("raw", "a.csv"), "/tmp/a.csv")

    def test_several_groups_and_other_texts_around_them(self):
        """raw → curated, but only within one project."""
        src = r"abfs://raw@lake/(?P<project>[^/]+)/(?P<year>\d{4})/.*"
        dest = r"abfs://curated@lake/(?P<project>[^/]+)/(?P<year>\d{4})/.*"
        policy = TransferPolicy(
            [
                {"rule": "allow", "src": src, "dest": dest},
                {"rule": "deny", "src": "abfs://raw@lake/.*", "dest": ".*"},
            ]
        )
        assert policy.allows(
            "abfs://raw@lake/p1/2026/x", "abfs://curated@lake/p1/2026/x"
        )
        assert not policy.allows(
            "abfs://raw@lake/p1/2026/x", "abfs://curated@lake/p2/2026/x"
        )
        assert not policy.allows(
            "abfs://raw@lake/p1/2026/x", "abfs://curated@lake/p1/2025/x"
        )

    def test_group_that_did_not_take_part(self):
        """A group outside the match captures None: equal only to None."""
        pattern = r"s3://b/(?:(?P<team>[^/]+)/)?x"
        policy = TransferPolicy(
            [
                {"rule": "allow", "src": pattern, "dest": pattern},
                {"rule": "deny"},
            ]
        )
        assert policy.allows("s3://b/x", "s3://b/x")
        assert policy.allows("s3://b/t1/x", "s3://b/t1/x")
        assert not policy.allows("s3://b/x", "s3://b/t1/x")

    def test_unnamed_groups_are_not_compared(self):
        policy = TransferPolicy(
            [{"rule": "deny", "src": r"s3://(a|b)/.*", "dest": r"s3://(a|b)/.*"}]
        )
        assert not policy.allows("s3://a/x", "s3://b/x")


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
        ([["deny", ".*", ".*"]], "transfer_policy rule 0: must be a dict"),
        (
            [{"rule": "block"}],
            'transfer_policy rule 0: "rule" must be "allow" or "deny"',
        ),
        (
            [{"rule": "deny"}, {"rule": "deny", "source": ".*"}],
            "transfer_policy rule 1: unknown keys",
        ),
        ([{"rule": "deny", "src": 3}], "'src' must be a regular expression"),
        ([{"rule": "deny", "dest": "("}], "'dest' is not a regular expression"),
        (
            [
                {
                    "rule": "deny",
                    "src": r"s3://(?P<b>[^/]+)/.*",
                    "dest": r"s3://(?P<c>[^/]+)/.*",
                }
            ],
            r"rule 0: 'src' and 'dest' must have the same named groups "
            r"\(src: \['b'\], dest: \['c'\]\)",
        ),
        (
            [{"rule": "deny", "src": r"s3://(?P<b>[^/]+)/.*"}],
            r"must have the same named groups \(src: \['b'\], dest: \[\]\)",
        ),
    ],
)
def test_invalid_rules(rules, message):
    with pytest.raises(ValueError, match=message):
        TransferPolicy(rules)
