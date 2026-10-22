"""Loads: reads in worker threads, their results shown or closed on the main thread."""

from __future__ import annotations

import asyncio
import threading

from in_a_kernel import until

from jupyter_storage_explorer._jobs.loader import Loader


def test_without_a_loop_loads_run_at_once():
    shown = []
    load = Loader().submit(lambda: 1, shown.append, lambda _: None)
    assert shown == [1]
    assert load.ended


def test_work_runs_in_a_worker_and_ends_on_the_main_thread():
    threads = {}

    def work():
        threads["work"] = threading.current_thread()
        return "view"

    async def main():
        shown = []
        Loader().submit(
            work, lambda r: shown.append((r, threading.current_thread())), print
        )
        await until(lambda: shown)
        return shown

    [(result, thread)] = asyncio.run(main())
    assert result == "view"
    assert thread is threading.main_thread()
    assert threads["work"] is not threading.main_thread()


def test_a_cancelled_load_is_discarded():
    release = threading.Event()

    async def main():
        shown, discarded = [], []
        load = Loader().submit(
            lambda: release.wait() and "view", shown.append, discarded.append
        )
        load.cancel()
        release.set()
        await until(lambda: discarded)
        return shown, discarded

    assert asyncio.run(main()) == ([], ["view"])


def test_loads_run_side_by_side():
    # The second ends while the first still waits: neither holds up the other.
    release = threading.Event()

    async def main():
        shown = []
        loader = Loader()
        loader.submit(lambda: release.wait() and "slow", shown.append, print)
        loader.submit(lambda: "quick", shown.append, print)
        await until(lambda: shown)
        first = list(shown)
        release.set()
        await until(lambda: len(shown) == 2)
        return first, shown

    assert asyncio.run(main()) == (["quick"], ["quick", "slow"])


def test_an_error_in_work_is_logged(caplog):
    def work():
        raise RuntimeError("boom")

    shown = []
    Loader().submit(work, shown.append, shown.append)
    assert shown == []
    assert "a load failed" in caplog.text
