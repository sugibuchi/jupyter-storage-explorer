// Jobs: moves, deletions, pastes, uploads and downloads run in the kernel's
// background (_jobs/runner.py). A request starting one is answered {"job": id}; the
// kernel then sends {"type": "job", id, state, counts...} as it runs, and its
// result when it ends. The widget stays usable meanwhile: each job is a row
// with a progress bar and Cancel, above the status bar.

const FINAL_STATES = new Set(["done", "failed", "cancelled"]);

function createJobs(x) {
  const el = h("div", { className: "jse-jobs", hidden: true });
  // id -> {row, parts, waiters}; finished jobs' last messages are kept briefly
  // in `ended`, in case one ends before its request's reply is handled.
  const jobs = new Map();
  const ended = new Map();
  // id -> show(job), for jobs shown elsewhere than in a row (see watch).
  const watchers = new Map();

  const cancel = (id) => x.model.send({ type: "job_cancel", id });

  function jobRow(id) {
    const title = h("span", { className: "jse-job-title" });
    const cancelBtn = h("button", { className: "jse-btn jse-job-cancel", textContent: "Cancel", title: "Stop after the file being worked on" });
    cancelBtn.addEventListener("click", () => {
      cancelBtn.disabled = true;
      cancel(id);
    });
    const fill = h("div", { className: "jse-job-fill" });
    const bar = h("div", { className: "jse-job-bar" }, fill);
    const detail = h("span", { className: "jse-job-detail" });
    const row = h("div", { className: "jse-job" }, h("div", { className: "jse-job-head" }, title, detail, cancelBtn), bar);
    return { row, parts: { title, detail, cancel: cancelBtn, bar, fill }, waiters: [] };
  }

  // e.g. "12 / 340 files · 45 MB / 1.2 GB · a.csv"; "Counting files…".
  function jobDetail(job) {
    if (job.cancelling) return "Cancelling…";
    if (job.state === "queued") return "Waiting…";
    if (!job.files_total) return "Counting files…";
    const parts = [`${job.files_done.toLocaleString()} / ${job.files_total.toLocaleString()} files`];
    if (job.bytes_total) parts.push(`${formatSize(job.bytes_done)} / ${formatSize(job.bytes_total)}`);
    if (job.current) parts.push(job.current);
    return parts.join(" · ");
  }

  // A {"type": "job"} message from the kernel.
  function onJob(job) {
    // Counting files for "Properties": shown in its dialog, not above the status bar.
    const counting = job.kind === "properties";
    if (counting && !FINAL_STATES.has(job.state)) watchers.get(job.id)?.(job);
    let entry = jobs.get(job.id);
    if (FINAL_STATES.has(job.state)) {
      entry?.row.remove();
      jobs.delete(job.id);
      el.hidden = jobs.size === 0;
      if (entry) entry.waiters.forEach((resolve) => resolve(job));
      else {
        ended.set(job.id, job);
        setTimeout(() => ended.delete(job.id), 60_000);
      }
      return;
    }
    if (!entry) {
      entry = jobRow(job.id);
      jobs.set(job.id, entry);
    }
    if (counting) return;
    if (!entry.row.isConnected) {
      el.append(entry.row);
      el.hidden = false;
    }
    const { title, detail, cancel: cancelBtn, bar, fill } = entry.parts;
    title.textContent = title.title = visible(job.title);
    detail.textContent = detail.title = visible(jobDetail(job));
    cancelBtn.disabled = cancelBtn.disabled || job.cancelling;
    // By bytes when known, else by files; unknown yet: an indeterminate bar.
    const fraction = job.bytes_total ? job.bytes_done / job.bytes_total : job.files_total ? job.files_done / job.files_total : null;
    bar.classList.toggle("jse-indeterminate", fraction == null);
    fill.style.width = fraction == null ? "" : `${Math.min(100, fraction * 100).toFixed(1)}%`;
  }

  // The result of a request that may have started a job: for {"job": id},
  // waits for it to end and returns its result with "state" and "error";
  // other replies (e.g. {"conflicts": [...]}) as they are.
  function result(reply) {
    if (!reply.job) return Promise.resolve(reply);
    const asResult = (job) => ({ ...(job.result ?? {}), state: job.state, error: job.error });
    const done = ended.get(reply.job);
    if (done) return Promise.resolve(asResult(done));
    return new Promise((resolve) => {
      let entry = jobs.get(reply.job);
      if (!entry) {
        // Its first message has not arrived yet.
        entry = jobRow(reply.job);
        jobs.set(reply.job, entry);
      }
      entry.waiters.push((job) => resolve(asResult(job)));
    });
  }

  return {
    el,
    onJob,
    result,
    cancel,
    // Calls show(job) as a "Properties" job runs, until unwatch(id).
    watch: (id, show) => watchers.set(id, show),
    unwatch: (id) => watchers.delete(id),
  };
}

// The end of a job's message, after `parts` (e.g. ["Pasted a.csv"]): why it
// failed, or that it was cancelled ("Paste cancelled" with nothing done,
// what = "Paste") and the item it left incomplete (e.g. a folder partly
// copied).
function jobOutcome(result, parts, what) {
  if (result.state === "failed") return [`Failed: ${result.error}`];
  if (!(result.cancelled || result.state === "cancelled")) return [];
  const out = [parts.length ? "cancelled" : `${what} cancelled`];
  if (result.incomplete) out.push(`${result.incomplete} left incomplete`);
  return out;
}

// The status bar's message about a job's result, e.g. "Moved 3 items;
// skipped 1 existing; Failed: b.csv: ...", or "Nothing moved". `done`: the
// names done, shown as one name or a count after `verb` ("Moved"), or as
// `doneText`; `noun`: as in "Move cancelled" (see jobOutcome).
function resultMessage(result, { verb, noun, done = [], doneText }) {
  const parts = [];
  if (done.length) parts.push(doneText ?? `${verb} ${done.length === 1 ? done[0] : `${done.length} items`}`);
  if (result.skipped?.length) parts.push(`skipped ${result.skipped.length} existing`);
  parts.push(...(result.errors ?? []).map((e) => `Failed: ${e}`));
  parts.push(...jobOutcome(result, parts, noun));
  return parts.join("; ") || `Nothing ${verb.toLowerCase()}`;
}
