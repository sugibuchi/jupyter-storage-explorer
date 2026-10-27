"""Jobs: their work in a worker thread, their state changed on the main thread."""

from __future__ import annotations

import asyncio
import threading
import time

from in_a_kernel import until

from jupyter_storage_explorer._jobs.runner import JobRunner


def test_without_a_loop_jobs_run_at_once():
    job = JobRunner(lambda job: None).submit("move", "Moving", lambda p: {"moved": []})
    assert job.state == "done"
    assert job.result == {"moved": []}


def test_the_outcome_reaches_the_job_on_the_main_thread():
    """While the work has ended but the main thread has not yet been told,
    the page sees the job still running: never ended before ``finish`` has
    run, or failed without its error."""
    started = threading.Event()
    end = threading.Event()
    seen = []

    def work(progress):
        started.set()
        end.wait(5)
        raise ValueError("bad value")

    async def main():
        runner = JobRunner(lambda job: seen.append(job.snapshot()))
        job = runner.submit(
            "move", "Moving", work, finish=lambda job: seen.append("finish")
        )
        await until(started.is_set)
        end.set()
        # Blocking: the worker ends meanwhile, without the loop running.
        time.sleep(0.2)  # noqa: ASYNC251
        runner.cancel(job.id)
        await until(lambda: job.id not in runner.jobs)
        return job

    job = asyncio.run(main())
    assert (job.state, job.error) == ("failed", "bad value")
    cancelled, finished, final = seen[-3:]
    assert cancelled["state"] in ("queued", "running")
    assert cancelled["cancelling"]
    assert finished == "finish"
    assert (final["state"], final["error"]) == ("failed", "bad value")


def test_a_job_cancelled_while_queued_never_runs():
    ran = []
    started = threading.Event()
    release = threading.Event()

    def first(progress):
        started.set()
        release.wait(5)
        return {}

    async def main():
        runner = JobRunner(lambda job: None)
        runner.submit("move", "First", first)
        second = runner.submit("move", "Second", lambda p: ran.append(1) or {})
        await until(started.is_set)
        runner.cancel(second.id)
        release.set()
        await until(lambda: not runner.jobs)
        return second

    second = asyncio.run(main())
    assert second.state == "cancelled"
    assert ran == []
