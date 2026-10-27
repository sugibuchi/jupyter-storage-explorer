// --- Data browser: pages through a query in the kernel ---
// The kernel applies the settings (filters, sort, hidden columns) and returns
// QUERY_PAGES_PER_WINDOW pages of rows at a time; pages of the kernel's
// "page_rows" rows (ViewLimits.max_display_rows) are shown from that window. The kernel also remembers the settings per dataset, and runs
// queries on the data itself ("Live") or on rows read into memory ("In
// memory"; see DataQuery in _query/data_query.py).

const QUERY_PAGES_PER_WINDOW = 10;
// Filter types ("op"); the kernel says which apply to each column. "range"
// has "min" and "max" (both included, either may be empty); "eq" is for
// booleans; the others with a value have "value".
const OP_LABELS = {
  not_null: "Not null",
  null: "Null",
  not_empty: "Not empty",
  empty: "Empty",
  contains: "Contains",
  regex: "Regex",
  range: "Range",
  eq: "=",
};
const NO_VALUE_OPS = new Set(["not_null", "null", "not_empty", "empty"]);
const VALUE_HINTS = { numeric: "e.g. 10", temporal: "e.g. 2025-01-31", text: "" };

// Column widths: automatic until a column is resized, then fixed. Part of the
// dataset's settings ("widths": {column name: px}), so the kernel remembers
// them with the filters.
// Kept within the kernel's range (_query/filters.py).
const MIN_COLUMN_WIDTH = 40;
const MAX_COLUMN_WIDTH = 2000;
const DEFAULT_COLUMN_WIDTH = 120;

// The filter types that take no value (Null, Not null, Empty, Not empty) are
// one type in the dialog, chosen between with radio buttons.
const NO_VALUE_TYPE = "null_or_empty";
const NO_VALUE_TYPE_LABEL = "Null / empty";

// Text filters with a "Case sensitive" option.
const CASE_OPS = new Set(["contains", "regex", "range"]);
// Browser field for each kind of value ("input" from the kernel).
const INPUT_TYPES = {
  text: { type: "text" },
  number: { type: "number", step: "any" },
  date: { type: "date" },
  datetime: { type: "datetime-local", step: "1" },
  time: { type: "time", step: "1" },
};

// label: text, or an icon (an SVG element).
function queryButton(label, onClick, title = "") {
  const btn = h("button", { className: typeof label === "string" ? "jse-btn" : "jse-btn jse-icon-btn", title }, label);
  btn.addEventListener("click", onClick);
  return btn;
}

// e.g. "quantity >= 8", "price between 1 and 5", "product contains tea (any
// case)", "comment: Not null".
function describeFilter(name, filter) {
  if (NO_VALUE_OPS.has(filter.op)) return `${name}: ${OP_LABELS[filter.op]}`;
  const anyCase = filter.case_sensitive === false ? " (any case)" : "";
  if (filter.op === "range") {
    const min = (filter.min ?? "").trim() ? filter.min : null;
    const max = (filter.max ?? "").trim() ? filter.max : null;
    if (min != null && max != null) return `${name} between ${min} and ${max}${anyCase}`;
    return (min != null ? `${name} >= ${min}` : `${name} <= ${max}`) + anyCase;
  }
  const label = filter.op === "eq" ? "=" : OP_LABELS[filter.op].toLowerCase();
  return `${name} ${label} ${filter.value}${anyCase}`;
}

// Radio buttons, one per [value, label]; returns the group and a getter.
function radioGroup(choices, selected) {
  const name = `jse-radio-${Math.random().toString(36).slice(2)}`;
  const inputs = choices.map(([value]) => h("input", { type: "radio", name, value, checked: value === selected }));
  if (!inputs.some((i) => i.checked)) inputs[0].checked = true;
  const el = h("div", { className: "jse-query-radios" }, ...choices.map(([, label], i) => h("label", {}, inputs[i], h("span", { textContent: label }))));
  return { el, value: () => inputs.find((i) => i.checked).value };
}

// Fixes the table's layout to the given widths.
function applyColumnWidths(table, columns, widths) {
  table.querySelector("colgroup")?.remove();
  const cols = columns.map((c) => h("col", { style: `width: ${widths[c.name]}px` }));
  table.prepend(h("colgroup", {}, ...cols));
  table.classList.add("jse-fixed");
  table.style.width = `${columns.reduce((sum, c) => sum + widths[c.name], 0)}px`;
  return cols;
}

// The data browser for one dataset. `host` is what it needs from the widget:
// {request, ask, answer, flash} (request: see createRequester; ask, answer:
// see createConfirm; flash(message): a short notice). `data` is the kernel's
// {columns, settings} for the dataset; `path` identifies it in requests.
// Returns {el, dispose}: dispose() when the panel is replaced or closed, so
// late replies are ignored.
function createQueryPanel(host, path, data) {
  const view = {
    columns: data.columns, // {name, dtype, kind, input, ops}
    settings: data.settings, // remembered by the kernel
    // Where queries run: {mode: "live" | "memory", fixed: why it cannot be
    // switched (or ""), memory: {rows, cut} in memory mode, partial: lazy data
    // of only the item's first part, live_limit: the most rows a live query
    // gives (or null), max_memory_rows}. See DataQuery.
    mode: data.mode,
    pageRows: data.page_rows ?? 100, // rows of a page
    start: 0, // first row of the fetched window
    rows: [],
    more: false,
    limited: false, // the result has more rows than live_limit
    total: null, // rows in the result, when the kernel counted them (in memory)
    switching: false,
    page: 0, // page within the window
    loading: false,
    error: "",
    disposed: false,
    el: h("div", { className: "jse-query" }),
  };

  async function fetchRows(start, page) {
    view.loading = true;
    draw();
    const reply = await host.request({ type: "query_rows", path, settings: view.settings, offset: start, window: view.pageRows * QUERY_PAGES_PER_WINDOW });
    if (view.disposed) return;
    view.loading = false;
    if (reply.settings) view.settings = reply.settings;
    if (reply.error) {
      Object.assign(view, { error: reply.error, rows: [], more: false, limited: false, total: null, start: 0, page: 0 });
    } else {
      const { offset: start, rows, more, limited, total } = reply;
      Object.assign(view, { error: "", start, rows, more, limited: Boolean(limited), total: total ?? null, page });
    }
    draw();
  }

  // "Live" | "In memory", at the right of the toolbar: greyed out while
  // loading, or when the kernel says the mode is fixed (e.g. a pandas
  // DataFrame, or data small enough to be all in memory).
  function modeSwitch() {
    const m = view.mode;
    const fixed = Boolean(m.fixed);
    const button = (mode, label, title) => {
      const btn = h("button", {
        className: "jse-btn jse-query-mode-btn" + (m.mode === mode ? " jse-on" : ""),
        textContent: label,
        title: fixed ? m.fixed : title,
        disabled: view.loading || fixed,
      });
      btn.setAttribute("aria-pressed", String(m.mode === mode));
      btn.addEventListener("click", () => m.mode !== mode && switchMode(mode));
      return btn;
    };
    const max = m.max_memory_rows.toLocaleString();
    return h(
      "span",
      { className: "jse-query-mode", role: "group", ariaLabel: "Where queries run" },
      button("live", "Live", "Query the data itself: each change reads it again"),
      button("memory", "In memory", `Read the first ${max} rows into memory once, and query them there (faster)`),
    );
  }

  // A note on rows left out: lazy data of only the item's first part (e.g. a
  // file's first bytes), in either mode; in memory, only the first rows of
  // the data (also when only those were read, e.g. by pandas: the mode is
  // fixed); live, only the first rows of the result.
  function modeNote() {
    const m = view.mode;
    if (m.partial) {
      return h("span", {
        className: "jse-query-mode-note",
        textContent: "First part of the data",
        title: "Only the first part of the item was read: filters and sorting apply to it, in either mode.",
      });
    }
    if (m.mode === "memory" && m.memory?.cut) {
      const n = m.memory.rows.toLocaleString();
      const live = m.fixed ? "" : " Switch to Live to query all the data.";
      return h("span", {
        className: "jse-query-mode-note",
        textContent: `First ${n} rows`,
        title: `Only the first ${n} rows of the data are in memory: filters and sorting apply to them.${live}`,
      });
    }
    if (m.mode === "live" && view.limited) {
      const n = m.live_limit.toLocaleString();
      return h("span", {
        className: "jse-query-mode-note",
        textContent: `First ${n} rows of the result`,
        title: `Live queries on this data give at most ${n} rows: narrow the result with filters, or switch to In memory.`,
      });
    }
    return null;
  }

  async function switchMode(mode) {
    view.loading = true;
    view.switching = mode === "memory";
    draw();
    const reply = await host.request({ type: "query_mode", path, mode, settings: view.settings });
    if (view.disposed) return;
    view.switching = false;
    if (reply.mode) Object.assign(view, { columns: reply.columns, settings: reply.settings, mode: reply.mode });
    if (reply.error) {
      Object.assign(view, { loading: false, error: reply.error });
      draw();
      return;
    }
    fetchRows(0, 0);
  }

  function draw() {
    const s = view.settings;
    const columns = view.columns.filter((c) => !s.hidden.includes(c.name));
    const pageRows = view.rows.slice(view.page * view.pageRows, (view.page + 1) * view.pageRows);
    const first = view.start + view.page * view.pageRows;
    const hasNext = (view.page + 1) * view.pageRows < view.rows.length || view.more;
    const resettable = Object.keys(s.filters).length > 0 || s.hidden.length > 0;

    let status;
    if (view.switching) status = "Reading into memory…";
    else if (view.loading) status = "Loading…";
    else if (!pageRows.length) status = "No rows";
    else {
      // In memory, the kernel counts the result. Live, the total is known once
      // the last rows are read; until then, the rows read so far and "+".
      const read = view.start + view.rows.length;
      let total;
      if (view.total != null) total = view.total.toLocaleString();
      else if (view.more || view.limited) total = `${read.toLocaleString()}+`;
      else total = read.toLocaleString();
      status = `Rows ${(first + 1).toLocaleString()}–${(first + pageRows.length).toLocaleString()} / ${total}`;
    }

    const prev = queryButton(icon("chevron-left"), prevPage, "Previous page");
    prev.disabled = view.loading || first === 0;
    const next = queryButton(icon("chevron-right"), nextPage, "Next page");
    next.disabled = view.loading || !hasNext;
    const reset = queryButton("Reset", resetQuery, "Remove all filters and show all columns");
    reset.disabled = !resettable;
    const reloadBtn = queryButton(icon("refresh"), reload, "Reload the data, e.g. after it changed");
    reloadBtn.disabled = view.loading;
    const toolbar = h(
      "div",
      { className: "jse-query-bar" },
      reloadBtn,
      queryButton(s.hidden.length ? `Select columns (${s.hidden.length} hidden)` : "Select columns", openColumnsDialog),
      h("div", { className: "jse-query-chips" }, ...Object.entries(s.filters).map(([name, f]) => filterChip(name, f))),
      reset,
      prev,
      h("span", { className: "jse-query-status", textContent: status }),
      next,
      ...[modeNote(), modeSwitch()].filter(Boolean),
    );

    const head = h("tr", {}, ...columns.map((c) => headerCell(c)));
    const body = pageRows.map((row) =>
      h(
        "tr",
        {},
        ...row.map((v) => {
          const text = v == null ? "null" : cellText(v);
          // The title shows values cut off in narrow columns.
          return h("td", { textContent: text, title: text, className: v == null ? "jse-null" : "" });
        }),
      ),
    );
    const tableEl = h("table", { className: "jse-data" }, h("thead", {}, head), h("tbody", {}, ...body));
    wireColumnResizers(tableEl, columns);
    const parts = [toolbar];
    if (view.error) parts.push(errorBlock(view.error));
    parts.push(h("div", { className: "jse-table-wrap" }, tableEl));
    view.el.replaceChildren(...parts);
  }

  // Name (click to sort) and filter button, and type underneath.
  function headerCell(column) {
    const s = view.settings;
    const sorted = s.sort?.column === column.name;
    const name = h("span", {
      className: "jse-query-name",
      textContent: column.name,
      title: "Sort by this column (click again to reverse, a third time to stop sorting)",
    });
    if (sorted) name.append(icon(s.sort.descending ? "caret-down" : "caret-up"));
    name.addEventListener("click", () => toggleSort(column.name));
    const active = s.filters[column.name];
    // Light grey, dark when the column has a filter.
    const filterBtn = h(
      "button",
      {
        className: "jse-query-filter" + (active ? " jse-active" : ""),
        title: active ? `Filter: ${describeFilter(column.name, active)}` : "Filter",
      },
      icon("filter"),
    );
    filterBtn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openFilterDialog(column);
    });
    return h(
      "th",
      {},
      h("div", { className: "jse-query-head" }, name, filterBtn),
      h("div", { className: "jse-query-dtype", textContent: column.dtype }),
      // Drag to resize the column; double-click to go back to automatic widths.
      h("span", { className: "jse-col-resizer", title: "Drag to resize; double-click for automatic widths" }),
    );
  }

  // Remembers settings changed without fetching rows, e.g. column widths.
  function saveSettings() {
    host.request({ type: "query_save", path, settings: view.settings });
  }

  function wireColumnResizers(table, columns) {
    const hasWidths = () => Object.keys(view.settings.widths ?? {}).length > 0;
    if (hasWidths()) {
      // Columns without a remembered width (e.g. shown again) get a default.
      const widths = { ...view.settings.widths };
      for (const c of columns) widths[c.name] ??= DEFAULT_COLUMN_WIDTH;
      applyColumnWidths(table, columns, widths);
    }
    table.querySelectorAll(".jse-col-resizer").forEach((handle, i) => {
      handle.addEventListener("click", (ev) => ev.stopPropagation());
      handle.addEventListener("dblclick", (ev) => {
        ev.stopPropagation();
        view.settings.widths = {};
        saveSettings();
        draw();
      });
      handle.addEventListener("pointerdown", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (!hasWidths()) {
          // First resize: fix every column at its current automatic width.
          const cells = table.querySelectorAll("thead th");
          view.settings.widths = Object.fromEntries(columns.map((c, j) => [c.name, Math.round(cells[j].getBoundingClientRect().width)]));
        }
        const widths = view.settings.widths;
        for (const c of columns) widths[c.name] ??= DEFAULT_COLUMN_WIDTH;
        const cols = applyColumnWidths(table, columns, widths);
        const name = columns[i].name;
        const startX = ev.clientX;
        const startWidth = widths[name];
        handle.setPointerCapture(ev.pointerId);
        const move = (e) => {
          const width = Math.round(startWidth + e.clientX - startX);
          widths[name] = Math.min(MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, width));
          cols[i].style.width = `${widths[name]}px`;
          table.style.width = `${columns.reduce((sum, c) => sum + widths[c.name], 0)}px`;
        };
        const up = () => {
          handle.removeEventListener("pointermove", move);
          handle.removeEventListener("pointerup", up);
          saveSettings();
        };
        handle.addEventListener("pointermove", move);
        handle.addEventListener("pointerup", up);
      });
    });
  }

  // Ascending, then descending, then not sorted.
  function toggleSort(name) {
    const s = view.settings;
    if (s.sort?.column !== name) s.sort = { column: name, descending: false };
    else if (!s.sort.descending) s.sort = { column: name, descending: true };
    else s.sort = null;
    fetchRows(0, 0);
  }

  function nextPage() {
    if ((view.page + 1) * view.pageRows < view.rows.length) {
      view.page += 1;
      draw();
    } else if (view.more) {
      fetchRows(view.start + view.pageRows * QUERY_PAGES_PER_WINDOW, 0);
    }
  }

  function prevPage() {
    if (view.page > 0) {
      view.page -= 1;
      draw();
    } else if (view.start > 0) {
      fetchRows(Math.max(0, view.start - view.pageRows * QUERY_PAGES_PER_WINDOW), QUERY_PAGES_PER_WINDOW - 1);
    }
  }

  // Reads the data again (it may have changed, columns included), keeping the
  // settings and the position.
  async function reload() {
    view.loading = true;
    draw();
    const reply = await host.request({ type: "query_reload", path, settings: view.settings });
    if (view.disposed) return;
    if (reply.error) {
      Object.assign(view, { loading: false, error: reply.error });
      draw();
      return;
    }
    Object.assign(view, { columns: reply.columns, settings: reply.settings, mode: reply.mode });
    fetchRows(view.start, view.page);
  }

  // Removes the filters and shows all columns; the sort order stays.
  function resetQuery() {
    view.settings = { ...view.settings, filters: {}, hidden: [] };
    fetchRows(0, 0);
  }

  // An applied filter in the toolbar: click to edit it, × to remove it.
  function filterChip(name, filter) {
    const text = describeFilter(name, filter);
    const label = h("span", { className: "jse-chip-label", textContent: text, title: `Edit filter: ${text}` });
    label.addEventListener("click", () => {
      const column = view.columns.find((c) => c.name === name);
      if (column) openFilterDialog(column);
    });
    const remove = h("button", { className: "jse-chip-remove", textContent: "×", title: "Remove this filter" });
    remove.addEventListener("click", () => {
      delete view.settings.filters[name];
      fetchRows(0, 0);
    });
    return h("span", { className: "jse-chip" }, label, remove);
  }

  // `draft`: a filter the user entered but that was rejected, shown again to fix.
  async function openFilterDialog(column, draft = null) {
    const current = view.settings.filters[column.name];
    const initial = draft ?? current;
    const currentValue = initial?.value ?? "";
    const noValueOps = column.ops.filter((op) => NO_VALUE_OPS.has(op));
    const valueOps = column.ops.filter((op) => !NO_VALUE_OPS.has(op));

    const typeSelect = h(
      "select",
      { className: "jse-query-input" },
      h("option", { value: NO_VALUE_TYPE, textContent: NO_VALUE_TYPE_LABEL }),
      ...valueOps.map((op) => h("option", { value: op, textContent: OP_LABELS[op] })),
    );
    // A new filter starts with the first type that takes a value, e.g. Contains or Range.
    if (initial) typeSelect.value = NO_VALUE_OPS.has(initial.op) ? NO_VALUE_TYPE : initial.op;
    else typeSelect.value = valueOps[0] ?? NO_VALUE_TYPE;

    // The possible contents of the Value row; the type decides which is shown.
    const nullChoices = radioGroup(
      noValueOps.map((op) => [op, OP_LABELS[op]]),
      NO_VALUE_OPS.has(initial?.op) ? initial.op : "not_null",
    );
    const boolChoices = radioGroup(
      [
        ["true", "True"],
        ["false", "False"],
      ],
      ["false", "0", "no"].includes(currentValue.toLowerCase()) ? "false" : "true",
    );
    // A field for the column's kind of value; Enter applies the filter.
    const field = (value, placeholder) => {
      const input = h("input", {
        className: "jse-query-input",
        ...(INPUT_TYPES[column.input] ?? INPUT_TYPES.text),
        // Date-time fields want "2025-01-31T12:00"; remembered values may have a space.
        value: column.input === "datetime" ? value.replace(" ", "T") : value,
        placeholder,
      });
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") host.answer("apply");
      });
      return input;
    };
    const valueInput = field(currentValue, VALUE_HINTS[column.kind] ?? "");
    // Range: from and to, both included; either may be left empty.
    const minInput = field(initial?.min ?? "", "No minimum");
    const maxInput = field(initial?.max ?? "", "No maximum");
    const rangeFields = h("div", { className: "jse-query-range" }, h("span", { textContent: "From" }), minInput, h("span", { textContent: "to" }), maxInput);
    const rangeNote = h("div", { className: "jse-note", textContent: "Both ends are included; leave one empty for no limit." });
    const caseBox = h("input", { type: "checkbox", checked: initial?.case_sensitive !== false });
    const caseLabel = h("label", { className: "jse-query-case" }, caseBox, h("span", { textContent: "Case sensitive" }));
    const valueCell = h("div", { className: "jse-query-value" });

    const isNoValue = () => typeSelect.value === NO_VALUE_TYPE;
    const isRange = () => typeSelect.value === "range";
    const showValue = () => {
      let parts;
      if (isNoValue()) parts = [nullChoices.el];
      else if (column.input === "boolean") parts = [boolChoices.el];
      else if (isRange()) parts = [rangeFields, rangeNote];
      else parts = [valueInput];
      if (!isNoValue() && column.input === "text" && CASE_OPS.has(typeSelect.value)) parts.push(caseLabel);
      valueCell.replaceChildren(...parts);
    };
    typeSelect.addEventListener("change", showValue);
    showValue();

    const buttons = [{ label: "Cancel", value: null }];
    if (current) buttons.push({ label: "Clear filter", value: "clear" });
    buttons.push({ label: "Apply", value: "apply", primary: true });
    const asked = host.ask(
      [
        h("div", { className: "jse-section-title", textContent: `Filter: ${column.name}` }),
        h("div", { className: "jse-note", textContent: column.dtype }),
        h(
          "div",
          { className: "jse-query-form" },
          h("div", { className: "jse-query-row" }, h("span", { textContent: "Type" }), typeSelect),
          h("div", { className: "jse-query-row" }, h("span", { textContent: "Value" }), valueCell),
        ),
      ],
      buttons,
    );
    [valueInput, minInput, typeSelect].find((el) => el.isConnected)?.focus({ preventScroll: true });
    const choice = await asked;
    if (view.disposed || !choice) return;

    if (choice === "clear") {
      delete view.settings.filters[column.name];
      fetchRows(0, 0);
      return;
    }
    let filter;
    if (isNoValue()) {
      filter = { op: nullChoices.value() };
    } else if (column.input === "boolean") {
      filter = { op: typeSelect.value, value: boolChoices.value() };
    } else if (isRange()) {
      filter = { op: "range", min: minInput.value, max: maxInput.value };
    } else {
      filter = { op: typeSelect.value, value: valueInput.value };
    }
    if (column.input === "text" && CASE_OPS.has(filter.op)) filter.case_sensitive = caseBox.checked;

    // Check before applying: a value is given, and it fits the column (e.g. a
    // regular expression polars can compile). If not, say why and reopen the
    // dialog with what was entered.
    let problem = null;
    if (filter.op === "range" && !filter.min.trim() && !filter.max.trim()) {
      problem = "Enter a minimum, a maximum or both.";
    } else if ("value" in filter && filter.value.trim() === "") {
      problem = "Enter a value.";
    } else if (!NO_VALUE_OPS.has(filter.op)) {
      const reply = await host.request({ type: "query_check", path, column: column.name, filter });
      if (view.disposed) return;
      problem = reply.error ?? null;
    }
    if (problem) {
      await showFilterError(column, filter, problem);
      if (!view.disposed) openFilterDialog(column, filter);
      return;
    }
    view.settings.filters[column.name] = filter;
    fetchRows(0, 0);
  }

  function showFilterError(column, filter, message) {
    const title = filter.op === "regex" ? "Invalid regular expression" : "Invalid filter value";
    return host.ask(
      [
        h("div", { className: "jse-section-title jse-error-text", textContent: title }),
        h("div", { className: "jse-note", textContent: `Filter on ${column.name}` }),
        // Monospace keeps polars' marker (^) under the right character.
        h("pre", { className: "jse-text jse-filter-error", textContent: message }),
      ],
      [{ label: "OK", value: true, primary: true }],
    );
  }

  async function openColumnsDialog() {
    const boxes = view.columns.map((column) => {
      const box = h("input", { type: "checkbox", checked: !view.settings.hidden.includes(column.name) });
      const label = h("label", {}, box, h("span", { textContent: column.name }), h("span", { className: "jse-note", textContent: column.dtype }));
      return { column, box, label };
    });
    const none = h("div", { className: "jse-note", textContent: "No columns match the filter", hidden: true });
    // Filters the list by column name; "Show all" and "Hide all" act on the columns listed.
    const filter = createFilter({
      placeholder: "Filter columns",
      onChange() {
        for (const { column, label } of boxes) label.hidden = !filter.test(column.name);
        none.hidden = boxes.some(({ label }) => !label.hidden);
      },
    });
    const setAll = (checked) => boxes.forEach(({ box, label }) => !label.hidden && (box.checked = checked));
    const asked = host.ask(
      [
        h("div", { className: "jse-section-title", textContent: "Select columns" }),
        filter.el,
        h(
          "div",
          { className: "jse-query-colbar" },
          queryButton("Show all", () => setAll(true)),
          queryButton("Hide all", () => setAll(false)),
        ),
        h("div", { className: "jse-query-cols" }, ...boxes.map(({ label }) => label), none),
      ],
      confirmButtons("Apply"),
    );
    filter.focus();
    const choice = await asked;
    if (view.disposed || !choice) return;
    const hidden = boxes.filter(({ box }) => !box.checked).map(({ column }) => column.name);
    if (hidden.length === view.columns.length) {
      host.flash("Keep at least one column visible");
      return;
    }
    view.settings.hidden = hidden;
    fetchRows(0, 0);
  }

  fetchRows(0, 0);
  return {
    el: view.el,
    dispose() {
      view.disposed = true;
    },
  };
}

// A table set (TableSetView): its tables in a tree beside the data browser
// ("tree"), or on tabs below it, as a spreadsheet's sheets ("tab"), and the
// data browser on the one chosen. `data` is the kernel's TableSet.opening():
// {selector, nodes: [{label, icon, id} for tables, {label, icon, children} for groups],
// table, query (or error)}. `path` names the item in requests
// ("table_set_open"); the data browser's also name the table (query_path in
// table_set.py), so that a table no longer shown is never answered for.
// Returns {el, dispose}, as createQueryPanel.
function createTableSetPanel(host, path, data) {
  const tabs = data.selector === "tab";
  const body = h("div", { className: "jse-table-set-body" });
  const chooser = h("div", { className: tabs ? "jse-table-set-tabs" : "jse-table-set-tree", role: tabs ? "tablist" : "tree" });
  const el = h("div", { className: `jse-table-set jse-table-set-by-${data.selector}` }, ...(tabs ? [body, chooser] : [chooser, body]));
  const items = new Map(); // table id -> its row or tab
  let table = data.table;
  let panel = null;
  let disposed = false;
  let asked = 0; // the latest "table_set_open", whose reply only is shown

  function mark() {
    for (const [id, item] of items) {
      item.classList.toggle("jse-active", id === table);
      item.setAttribute("aria-selected", String(id === table));
    }
    items.get(table)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  // The table chosen: {table, query} or {table, error}.
  function show(state) {
    panel?.dispose();
    panel = null;
    table = state.table;
    mark();
    if (state.error) {
      body.replaceChildren(errorBlock(state.error));
    } else {
      panel = createQueryPanel(host, `${path}\u0000${state.table}`, state.query);
      body.replaceChildren(panel.el);
    }
  }

  async function choose(id) {
    if (id === table && panel) return;
    const mine = ++asked;
    panel?.dispose();
    panel = null;
    table = id;
    mark();
    body.replaceChildren(h("div", { className: "jse-placeholder", textContent: "Loading…" }));
    const reply = await host.request({ type: "table_set_open", path, table: id });
    if (disposed || mine !== asked) return;
    show("table" in reply ? reply : { table: id, error: reply.error });
  }

  // A node's icon (Node.icon): a table's is a spreadsheet, as a CSV file's.
  function nodeIcon(node) {
    const key = { folder: "folder", database: "database", table: "spreadsheet" }[node.icon] ?? "file";
    return h("span", { className: "jse-table-set-icon" }, fileIcon(node.label, key === "folder", key));
  }

  // A table's row in the tree, or its tab.
  function tableItem(node, depth) {
    const item = tabs
      ? h("button", { className: "jse-table-set-tab", role: "tab", textContent: visible(node.label), title: visible(node.label) })
      : h(
          "div",
          { className: "jse-table-set-row jse-table-set-leaf", role: "treeitem", title: visible(node.label) },
          h("span", { className: "jse-table-set-twisty" }),
          nodeIcon(node),
          h("span", { className: "jse-table-set-label", textContent: visible(node.label) }),
        );
    if (!tabs) item.style.paddingLeft = `${depth * 14 + 4}px`;
    item.addEventListener("click", () => choose(node.id));
    items.set(node.id, item);
    return item;
  }

  // A group's row and its nodes, open at first; clicking the row closes it.
  function groupItem(node, depth) {
    const children = h("div", { role: "group" }, ...treeItems(node.children, depth + 1));
    const twisty = h("span", { className: "jse-table-set-twisty" }, icon("caret-down"));
    const row = h(
      "div",
      { className: "jse-table-set-row jse-table-set-group", role: "treeitem", title: visible(node.label) },
      twisty,
      nodeIcon(node),
      h("span", { className: "jse-table-set-label", textContent: visible(node.label) }),
    );
    row.style.paddingLeft = `${depth * 14 + 4}px`;
    row.setAttribute("aria-expanded", "true");
    row.addEventListener("click", () => {
      children.hidden = !children.hidden;
      row.setAttribute("aria-expanded", String(!children.hidden));
      twisty.replaceChildren(icon(children.hidden ? "caret-right" : "caret-down"));
    });
    return h("div", {}, row, children);
  }

  function treeItems(nodes, depth) {
    return nodes.map((node) => (node.children ? groupItem(node, depth) : tableItem(node, depth)));
  }

  chooser.replaceChildren(...treeItems(data.nodes, 0));
  show(data);

  return {
    el,
    dispose() {
      disposed = true;
      panel?.dispose();
    },
  };
}
