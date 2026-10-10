// --- Data browser ("Query data"): pages through a polars query in the kernel ---
// The kernel applies the settings (filters, sort, hidden columns) and returns
// QUERY_WINDOW rows at a time; pages of QUERY_PAGE rows are shown from that
// window. The kernel also remembers the settings per dataset.

const QUERY_WINDOW = 1000;
const QUERY_PAGE = 100;
const OP_LABELS = {
  not_null: "Not null",
  null: "Null",
  eq: "=",
  contains: "Contains",
  regex: "Regex",
  not_empty: "Not empty",
  empty: "Empty",
  gt: ">",
  lt: "<",
  ge: ">=",
  le: "<=",
};
const NO_VALUE_OPS = new Set(["not_null", "null", "not_empty", "empty"]);
const VALUE_HINTS = { numeric: "e.g. 10", temporal: "e.g. 2025-01-31", boolean: "true or false", text: "" };

// Column header filter icons: SVG, drawn in the text colour (currentColor);
// CSS fills them in when the column has a filter. FILTER_ICON is the one used.
const FUNNEL_ICON =
  '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' +
  '<path d="M1.5 2.5h13l-5 6v5l-3-1.5v-3.5z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';
const SEARCH_ICON =
  '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">' +
  '<circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" stroke-width="1.5"/>' +
  '<path d="M10 10l4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
const FILTER_ICON = FUNNEL_ICON;

// Column widths: automatic until a column is resized, then fixed. Part of the
// dataset's settings ("widths": {column name: px}), so the kernel remembers
// them with the filters.
const MIN_COLUMN_WIDTH = 40;
const DEFAULT_COLUMN_WIDTH = 120;

// The filter types that take no value (Null, Not null, Empty, Not empty) are
// one type in the dialog, chosen between with radio buttons.
const NO_VALUE_TYPE = "null_or_empty";
const NO_VALUE_TYPE_LABEL = "Null / empty";

// Text filters with a "Case sensitive" option.
const CASE_OPS = new Set(["eq", "contains", "regex"]);
// Browser field for each kind of value ("input" from the kernel).
const INPUT_TYPES = {
  text: { type: "text" },
  number: { type: "number", step: "any" },
  date: { type: "date" },
  datetime: { type: "datetime-local", step: "1" },
  time: { type: "time", step: "1" },
};

function queryButton(label, onClick, title = "") {
  const btn = h("button", { className: "jse-btn", textContent: label, title });
  btn.addEventListener("click", onClick);
  return btn;
}

// e.g. "quantity >= 8", "product contains tea (any case)", "comment: Not null".
function describeFilter(name, filter) {
  if (NO_VALUE_OPS.has(filter.op)) return `${name}: ${OP_LABELS[filter.op]}`;
  const label = filter.op === "contains" || filter.op === "regex" ? OP_LABELS[filter.op].toLowerCase() : OP_LABELS[filter.op];
  return `${name} ${label} ${filter.value}` + (filter.case_sensitive === false ? " (any case)" : "");
}

// Radio buttons, one per [value, label]; returns the group and a getter.
function radioGroup(choices, selected) {
  const name = `jse-radio-${Math.random().toString(36).slice(2)}`;
  const inputs = choices.map(([value]) => h("input", { type: "radio", name, value, checked: value === selected }));
  if (!inputs.some((i) => i.checked)) inputs[0].checked = true;
  const el = h(
    "div",
    { className: "jse-query-radios" },
    ...choices.map(([, label], i) => h("label", {}, inputs[i], h("span", { textContent: label }))),
  );
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
    start: 0, // first row of the fetched window
    rows: [],
    more: false,
    page: 0, // page within the window
    loading: false,
    error: "",
    disposed: false,
    el: h("div", { className: "jse-query" }),
  };

  async function fetchRows(start, page) {
    view.loading = true;
    draw();
    const reply = await host.request({ type: "query_rows", path, settings: view.settings, offset: start, window: QUERY_WINDOW });
    if (view.disposed) return;
    view.loading = false;
    if (reply.settings) view.settings = reply.settings;
    if (reply.error) {
      Object.assign(view, { error: reply.error, rows: [], more: false, start: 0, page: 0 });
    } else {
      Object.assign(view, { error: "", start: reply.offset, rows: reply.rows, more: reply.more, page });
    }
    draw();
  }

  function draw() {
    const s = view.settings;
    const columns = view.columns.filter((c) => !s.hidden.includes(c.name));
    const pageRows = view.rows.slice(view.page * QUERY_PAGE, (view.page + 1) * QUERY_PAGE);
    const first = view.start + view.page * QUERY_PAGE;
    const hasNext = (view.page + 1) * QUERY_PAGE < view.rows.length || view.more;
    const resettable = Object.keys(s.filters).length > 0 || s.hidden.length > 0;

    let status;
    if (view.loading) status = "Loading…";
    else if (!pageRows.length) status = "No rows";
    else {
      const total = view.more ? "" : ` of ${(view.start + view.rows.length).toLocaleString()}`;
      status = `Rows ${(first + 1).toLocaleString()}–${(first + pageRows.length).toLocaleString()}${total}`;
    }

    const prev = queryButton("◀", prevPage, "Previous page");
    prev.disabled = view.loading || first === 0;
    const next = queryButton("▶", nextPage, "Next page");
    next.disabled = view.loading || !hasNext;
    const reset = queryButton("Reset", resetQuery, "Remove all filters and show all columns");
    reset.disabled = !resettable;
    const toolbar = h(
      "div",
      { className: "jse-query-bar" },
      queryButton(s.hidden.length ? `Select columns (${s.hidden.length} hidden)` : "Select columns", openColumnsDialog),
      h("div", { className: "jse-query-chips" }, ...Object.entries(s.filters).map(([name, f]) => filterChip(name, f))),
      reset,
      prev,
      h("span", { className: "jse-query-status", textContent: status }),
      next,
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
    if (view.error) parts.push(h("div", { className: "jse-preview-error", textContent: view.error }));
    parts.push(h("div", { className: "jse-table-wrap" }, tableEl));
    view.el.replaceChildren(...parts);
  }

  // Name (click to sort) and filter button, and type underneath.
  function headerCell(column) {
    const s = view.settings;
    const sorted = s.sort?.column === column.name;
    const name = h("span", {
      className: "jse-query-name",
      textContent: column.name + (sorted ? (s.sort.descending ? " ▼" : " ▲") : ""),
      title: "Sort by this column (click again to reverse, a third time to stop sorting)",
    });
    name.addEventListener("click", () => toggleSort(column.name));
    const active = s.filters[column.name];
    const filterBtn = h("button", {
      className: "jse-query-filter" + (active ? " jse-active" : ""),
      innerHTML: FILTER_ICON,
      title: active ? `Filter: ${describeFilter(column.name, active)}` : "Filter",
    });
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
          widths[name] = Math.max(MIN_COLUMN_WIDTH, Math.round(startWidth + e.clientX - startX));
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
    if ((view.page + 1) * QUERY_PAGE < view.rows.length) {
      view.page += 1;
      draw();
    } else if (view.more) {
      fetchRows(view.start + QUERY_WINDOW, 0);
    }
  }

  function prevPage() {
    if (view.page > 0) {
      view.page -= 1;
      draw();
    } else if (view.start > 0) {
      fetchRows(Math.max(0, view.start - QUERY_WINDOW), QUERY_WINDOW / QUERY_PAGE - 1);
    }
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
    const currentValue = initial && !NO_VALUE_OPS.has(initial.op) ? initial.value : "";
    const noValueOps = column.ops.filter((op) => NO_VALUE_OPS.has(op));
    const valueOps = column.ops.filter((op) => !NO_VALUE_OPS.has(op));

    const typeSelect = h(
      "select",
      { className: "jse-query-input" },
      ...valueOps.map((op) => h("option", { value: op, textContent: OP_LABELS[op] })),
      h("option", { value: NO_VALUE_TYPE, textContent: NO_VALUE_TYPE_LABEL }),
    );
    if (initial) typeSelect.value = NO_VALUE_OPS.has(initial.op) ? NO_VALUE_TYPE : initial.op;
    else typeSelect.value = valueOps.includes("eq") ? "eq" : (valueOps[0] ?? NO_VALUE_TYPE);

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
    const valueInput = h("input", {
      className: "jse-query-input",
      ...(INPUT_TYPES[column.input] ?? INPUT_TYPES.text),
      // Date-time fields want "2025-01-31T12:00"; remembered values may have a space.
      value: column.input === "datetime" ? currentValue.replace(" ", "T") : currentValue,
      placeholder: VALUE_HINTS[column.kind] ?? "",
    });
    valueInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") host.answer("apply");
    });
    const caseBox = h("input", { type: "checkbox", checked: initial?.case_sensitive !== false });
    const caseLabel = h("label", { className: "jse-query-case" }, caseBox, h("span", { textContent: "Case sensitive" }));
    const valueCell = h("div", { className: "jse-query-value" });

    const isNoValue = () => typeSelect.value === NO_VALUE_TYPE;
    const showValue = () => {
      if (isNoValue()) valueCell.replaceChildren(nullChoices.el);
      else if (column.input === "boolean") valueCell.replaceChildren(boolChoices.el);
      else if (column.input === "text" && CASE_OPS.has(typeSelect.value)) valueCell.replaceChildren(valueInput, caseLabel);
      else valueCell.replaceChildren(valueInput);
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
    (valueInput.isConnected ? valueInput : typeSelect).focus({ preventScroll: true });
    const choice = await asked;
    if (view.disposed || !choice) return;

    if (choice === "clear") {
      delete view.settings.filters[column.name];
      fetchRows(0, 0);
      return;
    }
    let filter;
    if (isNoValue()) {
      filter = { op: nullChoices.value(), value: "" };
    } else if (column.input === "boolean") {
      filter = { op: typeSelect.value, value: boolChoices.value() };
    } else {
      filter = { op: typeSelect.value, value: valueInput.value };
      if (column.input === "text" && CASE_OPS.has(filter.op)) filter.case_sensitive = caseBox.checked;
    }

    // Check before applying: a value is given, and it fits the column (e.g. a
    // regular expression polars can compile). If not, say why and reopen the
    // dialog with what was entered.
    let problem = null;
    if (!NO_VALUE_OPS.has(filter.op) && filter.value.trim() === "") {
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
    const boxes = view.columns.map((column) => ({
      column,
      box: h("input", { type: "checkbox", checked: !view.settings.hidden.includes(column.name) }),
    }));
    const setAll = (checked) => boxes.forEach(({ box }) => (box.checked = checked));
    const choice = await host.ask(
      [
        h("div", { className: "jse-section-title", textContent: "Select columns" }),
        h("div", { className: "jse-query-colbar" }, queryButton("Show all", () => setAll(true)), queryButton("Hide all", () => setAll(false))),
        h(
          "div",
          { className: "jse-query-cols" },
          ...boxes.map(({ column, box }) =>
            h("label", {}, box, h("span", { textContent: column.name }), h("span", { className: "jse-note", textContent: column.dtype })),
          ),
        ),
      ],
      [
        { label: "Cancel", value: null },
        { label: "Apply", value: true, primary: true },
      ],
    );
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
