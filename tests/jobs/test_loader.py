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


def test_a_lane_runs_one_at_a_time_in_order():
    # The second of a lane waits for the first; another lane's does not.
    release = threading.Event()

    async def main():
        shown = []
        loader = Loader()
        loader.submit(lambda: release.wait() and 1, shown.append, print, lane="a")
        loader.submit(lambda: 2, shown.append, print, lane="a")
        loader.submit(lambda: 3, shown.append, print, lane="b")
        await until(lambda: shown)
        first = list(shown)
        release.set()
        await until(lambda: len(shown) == 3)
        return first, shown

    assert asyncio.run(main()) == ([3], [3, 1, 2])


def test_answers_and_closes_in_a_lane():
    ran = []

    def rows():
        ran.append("rows")
        return {"rows": [1]}

    def failing():
        ran.append("failing")
        return 1 / 0

    async def main():
        replies = []
        loader = Loader()
        loader.answer("q", rows, replies.append)
        loader.answer("q", failing, replies.append)
        loader.close_in_lane("q", lambda: ran.append("close"))
        await until(lambda: "close" in ran and len(replies) == 2)
        return replies

    replies = asyncio.run(main())
    assert replies == [{"rows": [1]}, {"error": "ZeroDivisionError: division by zero"}]
    assert ran == ["rows", "failing", "close"]


def test_an_error_in_work_is_logged(caplog):
    def work():
        raise RuntimeError("boom")

    shown = []
    Loader().submit(work, shown.append, shown.append)
    assert shown == []
    assert "a load failed" in caplog.text
