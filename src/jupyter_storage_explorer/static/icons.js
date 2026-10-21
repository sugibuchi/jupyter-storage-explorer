// Icons: filled, single-colour SVGs drawn in the current text colour (CSS sets
// the grey of JupyterLab's icons, see .jse-svg), from Google's Material Design
// Icons, as JupyterLab's own are. Apache License 2.0, see vendor/README.md.
// Joined before common.js (see _static.py).

const ICON_PATHS = {
  folder: "M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z",
  file: "M6 2c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6H6zm7 7V3.5L18.5 9H13z",
  star: "M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z",
  "star-border":
    "M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28L12 15.4z",
  up: "M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z",
  tree: "M22 11V3h-7v3H9V3H2v8h7V8h2v10h4v3h7v-8h-7v3h-2V8h2v3z",
  columns: "M10 18h5V5h-5v13zm-6 0h5V5H4v13zM16 5v13h5V5h-5z",
  refresh:
    "M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z",
  "caret-right": "M10 17l5-5-5-5v10z",
  "caret-down": "M7 10l5 5 5-5z",
  "caret-up": "M7 14l5-5 5 5z",
  "chevron-left": "M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z",
  "chevron-right": "M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z",
  close: "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  eye: "M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z",
  edit: "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34a.9959.9959 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
  code: "M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0l4.6-4.6-4.6-4.6L16 6l6 6-6 6-1.4-1.4z",
  link: "M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z",
  copy: "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z",
  cut: "M9.64 7.64c.23-.5.36-1.05.36-1.64 0-2.21-1.79-4-4-4S2 3.79 2 6s1.79 4 4 4c.59 0 1.14-.13 1.64-.36L10 12l-2.36 2.36C7.14 14.13 6.59 14 6 14c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4c0-.59-.13-1.14-.36-1.64L12 14l7 7h3v-1L9.64 7.64zM6 8c-1.1 0-2-.89-2-2s.9-2 2-2 2 .89 2 2-.9 2-2 2zm0 12c-1.1 0-2-.89-2-2s.9-2 2-2 2 .89 2 2-.9 2-2 2zm6-7.5c-.28 0-.5-.22-.5-.5s.22-.5.5-.5.5.22.5.5-.22.5-.5.5zM19 3l-6 6 2 2 7-7V3z",
  paste:
    "M19 2h-4.18C14.4.84 13.3 0 12 0c-1.3 0-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm7 18H5V4h2v3h10V4h2v16z",
  "new-folder": "M20 6h-8l-2-2H4c-1.11 0-1.99.89-1.99 2L2 18c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-1 8h-3v3h-2v-3h-3v-2h3V9h2v3h3v2z",
  "open-in-new": "M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z",
  download: "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
  inbox:
    "M19 3H4.99c-1.11 0-1.98.9-1.98 2L3 19c0 1.1.88 2 1.99 2H19c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 12h-4c0 1.66-1.35 3-3 3s-3-1.34-3-3H4.99V5H19v10zm-3-5h-2V7h-4v3H8l4 4 4-4z",
  filter: "M4.25 5.61C6.27 8.2 10 13 10 13v6c0 .55.45 1 1 1h2c.55 0 1-.45 1-1v-6s3.72-4.8 5.74-7.39c.51-.66.04-1.61-.79-1.61H5.04c-.83 0-1.3.95-.79 1.61z",
  search:
    "M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  settings:
    "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
  info: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z",
  check: "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
  memory:
    "M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z",
};

// An icon by name (ICON_PATHS), as an inline SVG element of the class
// "jse-svg", 16 pixels unless CSS says otherwise.
function icon(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `jse-svg jse-svg-${name}`);
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICON_PATHS[name]);
  svg.append(path);
  return svg;
}

// A button showing an icon, e.g. iconButton("refresh", "Refresh").
function iconButton(name, title, className = "") {
  return h("button", { className: `jse-btn jse-icon-btn ${className}`.trim(), title, ariaLabel: title }, icon(name));
}

// The file browser's icons: JupyterLab's own (from @jupyterlab/ui-components,
// BSD-3-Clause, see vendor/README.md), coloured as there. Their classes (e.g.
// "jp-icon3") are JupyterLab's, so its theme recolours them, and CSS whitens
// them in selected rows (see .jse-icon in storage_explorer.css), as JupyterLab
// does.
const FILE_ICON_SVGS = {
  folder:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#616161" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8z" class="jp-icon3 jp-icon-selectable"/></svg>',
  file: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><path fill="#616161" d="m19.3 8.2-5.5-5.5c-.3-.3-.7-.5-1.2-.5H3.9c-.8.1-1.6.9-1.6 1.8v14.1c0 .9.7 1.6 1.6 1.6h14.2c.9 0 1.6-.7 1.6-1.6V9.4c.1-.5-.1-.9-.4-1.2m-5.8-3.3 3.4 3.6h-3.4zm3.9 12.7H4.7c-.1 0-.2 0-.2-.2V4.7c0-.2.1-.3.2-.3h7.2v4.4s0 .8.3 1.1 1.1.3 1.1.3h4.3v7.2s-.1.2-.2.2" class="jp-icon3 jp-icon-selectable"/></svg>',
  notebook:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><g fill="#EF6C00" class="jp-notebook-icon-color jp-icon-selectable"><path d="M18.7 3.3v15.4H3.3V3.3zm1.5-1.5H1.8v18.3h18.3z"/><path d="m16.5 16.5-5.4-4.3-5.6 4.3v-11h11z"/></g></svg>',
  markdown:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><path fill="#7B1FA2" d="M5 14.9h12l-6.1 6zm9.4-6.8c0-1.3-.1-2.9-.1-4.5-.4 1.4-.9 2.9-1.3 4.3l-1.3 4.3h-2L8.5 7.9c-.4-1.3-.7-2.9-1-4.3-.1 1.6-.1 3.2-.2 4.6L7 12.4H4.8l.7-11h3.3L10 5c.4 1.2.7 2.7 1 3.9.3-1.2.7-2.6 1-3.9l1.2-3.7h3.3l.6 11h-2.4z" class="jp-icon-contrast0 jp-icon-selectable"/></svg>',
  pdf: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><path fill="#FF2A2A" d="m17.933 13.667 3.987 3.987-1.117 1.117-2.51-2.51-1.066 1.067 2.36 2.36-1.117 1.117-2.36-2.36-2.43 2.429-1.477-1.478zm-6.163-3.93-3.496 3.496.53.53q.905.906 1.83.932.929.031 1.784-.825.852-.852.822-1.773t-.94-1.83zm-.36-2.594 1.557 1.558q1.305 1.305 1.754 2.13.456.825.468 1.727.015.79-.296 1.493-.31.702-.951 1.343-.649.648-1.355.963-.702.31-1.493.295-.905-.015-1.738-.472-.829-.46-2.118-1.75L5.68 12.874zm-5.76-5.76L8.1 3.835Q9.195 4.93 9.291 6q.103 1.07-.795 1.968-.901.902-1.976.802-1.067-.1-2.16-1.193l-.975-.975L1.397 8.59-.08 7.113Zm.406 2.548-1.6 1.6.817.818q.43.43.871.457.445.023.829-.361t.357-.825-.457-.871z" class="jp-icon-selectable"/></svg>',
  python:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 -10 131.161 132.389"><path fill="#306998" d="M54.919 0c-4.584.022-8.961.413-12.813 1.095C30.76 3.099 28.7 7.295 28.7 15.032v10.219h26.813v3.406H18.638c-7.793 0-14.616 4.684-16.75 13.594-2.462 10.213-2.571 16.586 0 27.25 1.905 7.938 6.457 13.594 14.25 13.594h9.218v-12.25c0-8.85 7.657-16.657 16.75-16.657h26.782c7.454 0 13.406-6.138 13.406-13.625v-25.53c0-7.267-6.13-12.726-13.406-13.938C64.282.328 59.502-.02 54.918 0m-14.5 8.22c2.77 0 5.031 2.298 5.031 5.125 0 2.816-2.262 5.093-5.031 5.093-2.78 0-5.031-2.277-5.031-5.093 0-2.827 2.251-5.125 5.03-5.125" class="jp-icon-selectable"/><path fill="#ffd43b" d="M85.638 28.657v11.906c0 9.231-7.826 17-16.75 17H42.106c-7.336 0-13.406 6.279-13.406 13.625V96.72c0 7.266 6.319 11.54 13.406 13.625 8.488 2.495 16.627 2.946 26.782 0 6.75-1.955 13.406-5.888 13.406-13.625V86.5H55.513v-3.405H95.7c7.793 0 10.696-5.436 13.406-13.594 2.8-8.399 2.68-16.476 0-27.25-1.925-7.758-5.604-13.594-13.406-13.594zM70.575 93.313c2.78 0 5.031 2.278 5.031 5.094 0 2.827-2.251 5.125-5.031 5.125-2.77 0-5.031-2.298-5.031-5.125 0-2.816 2.261-5.094 5.031-5.094" class="jp-icon-selectable"/></svg>',
  json: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><g fill="#F9A825" class="jp-json-icon-color jp-icon-selectable"><path d="M20.2 11.8c-1.6 0-1.7.5-1.7 1 0 .4.1.9.1 1.3.1.5.1.9.1 1.3 0 1.7-1.4 2.3-3.5 2.3h-.9v-1.9h.5c1.1 0 1.4 0 1.4-.8 0-.3 0-.6-.1-1 0-.4-.1-.8-.1-1.2 0-1.3 0-1.8 1.3-2-1.3-.2-1.3-.7-1.3-2 0-.4.1-.8.1-1.2.1-.4.1-.7.1-1 0-.8-.4-.7-1.4-.8h-.5V4.1h.9c2.2 0 3.5.7 3.5 2.3 0 .4-.1.9-.1 1.3-.1.5-.1.9-.1 1.3 0 .5.2 1 1.7 1zM1.8 10.1c1.6 0 1.7-.5 1.7-1 0-.4-.1-.9-.1-1.3-.1-.5-.1-.9-.1-1.3 0-1.6 1.4-2.3 3.5-2.3h.9v1.9h-.5c-1 0-1.4 0-1.4.8 0 .3 0 .6.1 1 0 .2.1.6.1 1 0 1.3 0 1.8-1.3 2C6 11.2 6 11.7 6 13c0 .4-.1.8-.1 1.2-.1.3-.1.7-.1 1 0 .8.3.8 1.4.8h.5v1.9h-.9c-2.1 0-3.5-.6-3.5-2.3 0-.4.1-.9.1-1.3.1-.5.1-.9.1-1.3 0-.5-.2-1-1.7-1z"/><circle cx="11" cy="13.8" r="2.1"/><circle cx="11" cy="8.2" r="2.1"/></g></svg>',
  julia:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 325 300"><path fill="#cb3c33" d="M150.898 225c0 41.422-33.578 75-75 75s-75-33.578-75-75 33.579-75 75-75 75 33.578 75 75" class="jp-brand0 jp-icon-selectable"/><path fill="#389826" d="M237.5 75c0 41.422-33.578 75-75 75s-75-33.578-75-75 33.578-75 75-75 75 33.578 75 75" class="jp-brand0 jp-icon-selectable"/><path fill="#9558b2" d="M324.102 225c0 41.422-33.579 75-75 75s-75-33.578-75-75 33.578-75 75-75 75 33.578 75 75" class="jp-brand0 jp-icon-selectable"/></svg>',
  spreadsheet:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><path fill="#4CAF50" d="M2.2 2.2v17.6h17.6V2.2zm15.4 7.7h-5.5V4.4h5.5zM9.9 4.4v5.5H4.4V4.4zm-5.5 7.7h5.5v5.5H4.4zm7.7 5.5v-5.5h5.5v5.5z" class="jp-icon-contrast1 jp-icon-selectable"/></svg>',
  "r-kernel":
    '<svg xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" viewBox="0 0 724 561"><path class="jp-icon-selectable" d="M361.453,485.937 C162.329,485.937 0.906,377.828 0.906,244.469 C0.906,111.109 162.329,3.000 361.453,3.000 C560.578,3.000 722.000,111.109 722.000,244.469 C722.000,377.828 560.578,485.937 361.453,485.937 ZM416.641,97.406 C265.289,97.406 142.594,171.314 142.594,262.484 C142.594,353.654 265.289,427.562 416.641,427.562 C567.992,427.562 679.687,377.033 679.687,262.484 C679.687,147.971 567.992,97.406 416.641,97.406 Z" fill="rgb(179,179,179)" fill-rule="evenodd"/><path class="jp-icon-selectable" d="M550.000,377.000 C550.000,377.000 571.822,383.585 584.500,390.000 C588.899,392.226 596.510,396.668 602.000,402.500 C607.378,408.212 610.000,414.000 610.000,414.000 L696.000,559.000 L557.000,559.062 L492.000,437.000 C492.000,437.000 478.690,414.131 470.500,407.500 C463.668,401.969 460.755,400.000 454.000,400.000 C449.298,400.000 420.974,400.000 420.974,400.000 L421.000,558.974 L298.000,559.026 L298.000,152.938 L545.000,152.938 C545.000,152.938 657.500,154.967 657.500,262.000 C657.500,369.033 550.000,377.000 550.000,377.000 ZM496.500,241.024 L422.037,240.976 L422.000,310.026 L496.500,310.002 C496.500,310.002 531.000,309.895 531.000,274.877 C531.000,239.155 496.500,241.024 496.500,241.024 Z" fill="rgb(52,101,176)" fill-rule="evenodd"/></svg>',
  yaml: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><g fill="#D81B60" class="jp-icon-contrast2 jp-icon-selectable"><path d="M7.2 18.6v-5.4L3 5.6h3.3l1.4 3.1c.3.9.6 1.6 1 2.5.3-.8.6-1.6 1-2.5l1.4-3.1h3.4l-4.4 7.6v5.5z"/><circle cx="17.6" cy="16.5" r="2.1"/><circle cx="17.6" cy="11" r="2.1"/></g></svg>',
  image:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22"><path fill="#FFF" d="M2.2 2.2h17.5v17.5H2.2z" class="jp-icon-brand4 jp-icon-selectable-inverse"/><path fill="#3F51B5" d="M2.2 2.2v17.5h17.5l.1-17.5zm12.1 2.2c1.2 0 2.2 1 2.2 2.2s-1 2.2-2.2 2.2-2.2-1-2.2-2.2 1-2.2 2.2-2.2M4.4 17.6l3.3-8.8 3.3 6.6 2.2-3.2 4.4 5.4z" class="jp-icon-brand0 jp-icon-selectable"/></svg>',
  audio:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path class="jp-icon3 jp-icon-selectable" fill="#616161" d="M13,4V20a1,1,0,0,1-2,0V4a1,1,0,0,1,2,0ZM8,5A1,1,0,0,0,7,6V18a1,1,0,0,0,2,0V6A1,1,0,0,0,8,5ZM4,7A1,1,0,0,0,3,8v8a1,1,0,0,0,2,0V8A1,1,0,0,0,4,7ZM16,5a1,1,0,0,0-1,1V18a1,1,0,0,0,2,0V6A1,1,0,0,0,16,5Zm4,2a1,1,0,0,0-1,1v8a1,1,0,0,0,2,0V8A1,1,0,0,0,20,7Z"/></svg>',
  video:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path class="jp-icon3 jp-icon-selectable" fill="#616161" d="M18 3v2h-2V3H8v2H6V3H4v18h2v-2h2v2h8v-2h2v2h2V3h-2zM8 17H6v-2h2v2zm0-4H6v-2h2v2zm0-4H6V7h2v2zm10 8h-2v-2h2v2zm0-4h-2v-2h2v2zm0-4h-2V7h2v2z"/><path d="M0 0h24v24H0z" fill="none"/></svg>',
  html5:
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><path fill="#000" d="M108.4 0h23v22.8h21.2V0h23v69h-23V46h-21v23h-23.2M206 23h-20.3V0h63.7v23H229v46h-23m53.5-69h24.1l14.8 24.3L313.2 0h24.1v69h-23V34.8l-16.1 24.8-16.1-24.8V69h-22.6m89.2-69h23v46.2h32.6V69h-55.6" class="jp-icon0 jp-icon-selectable"/><path fill="#e44d26" d="m107.6 471-33-370.4h362.8l-33 370.2L255.7 512" class="jp-icon-selectable"/><path fill="#f16529" d="M256 480.5V131h148.3L376 447" class="jp-icon-selectable"/><path fill="#ebebeb" d="M142 176.3h114v45.4h-64.2l4.2 46.5h60v45.3H154.4m2 22.8H202l3.2 36.3 50.8 13.6v47.4l-93.2-26" class="jp-icon-selectable-inverse"/><path fill="#fff" d="M369.6 176.3H255.8v45.4h109.6m-4.1 46.5H255.8v45.4h56l-5.3 59-50.7 13.6v47.2l93-25.8" class="jp-icon-selectable-inverse"/></svg>',
};

// The icons of folders a storage's structure makes more than folders (their
// level: FileSystemMapper.levels, the explorer's _fs_levels), drawn as the folder icon above,
// in JupyterLab's grey: from Material Design Icons (filled; Apache License
// 2.0), the bucket and the hard disk from Pictogrammers' Material Design Icons
// (Apache License 2.0), see vendor/README.md. Not the clouds' own pictograms,
// whose licences cover diagrams and documents only.
const LEVEL_ICON_PATHS = {
  // An Azure account; the top of S3 or GCS, holding the buckets.
  cloud:
    "M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z",
  // Material's inventory_2: a box, for an Azure container.
  box: "M20 2H4c-1 0-2 .9-2 2v3.01c0 .72.43 1.34 1 1.69V20c0 1.1 1.1 2 2 2h14c.9 0 2-.9 2-2V8.7c.57-.35 1-.97 1-1.69V4c0-1.1-1-2-2-2zm-5 12H9v-2h6v2zm5-7H4V4h16v3z",
  bucket: "M3 4H21V7H20L17.5 21H6.5L4 7H3V4Z",
  // Material's dns: a server, for an SFTP host.
  server:
    "M20 13H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zM7 19c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zM20 3H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1V4c0-.55-.45-1-1-1zM7 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z",
  harddisk:
    "M6,2H18A2,2 0 0,1 20,4V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2M12,4A6,6 0 0,0 6,10C6,13.31 8.69,16 12.1,16L11.22,13.77C10.95,13.29 11.11,12.68 11.59,12.4L12.45,11.9C12.93,11.63 13.54,11.79 13.82,12.27L15.74,14.69C17.12,13.59 18,11.9 18,10A6,6 0 0,0 12,4M12,9A1,1 0 0,1 13,10A1,1 0 0,1 12,11A1,1 0 0,1 11,10A1,1 0 0,1 12,9M7,18A1,1 0 0,0 6,19A1,1 0 0,0 7,20A1,1 0 0,0 8,19A1,1 0 0,0 7,18M12.09,13.27L14.58,19.58L17.17,18.08L12.95,12.77L12.09,13.27Z",
  // Material's memory: a chip, for fsspec's memory filesystem.
  chip: "M15 9H9v6h6V9zm-2 4h-2v-2h2v2zm8-2V9h-2V7c0-1.1-.9-2-2-2h-2V3h-2v2h-2V3H9v2H7c-1.1 0-2 .9-2 2v2H3v2h2v2H3v2h2v2c0 1.1.9 2 2 2h2v2h2v-2h2v2h2v-2h2c1.1 0 2-.9 2-2v-2h2v-2h-2v-2h2zm-4 6H7V7h10v10z",
  // Databricks (DatabricksMapper.level). Unity Catalog: its catalogs (MDI's
  // bookshelf), a catalog (Material Symbols' book_2), a schema (MDI's
  // database), a volume (Material Symbols' files); /Workspace (Material's work).
  bookshelf: "M9 3V18H12V3H9M12 5L16 18L19 17L15 4L12 5M5 5V18H8V5H5M3 19V21H21V19H3Z",
  book2:
    "M290-80q-54 0-92-38t-38-92v-540q0-54 38-92t92-38h510v600q-26 0-43 21t-17 49q0 28 17 49t43 21v60H290Zm30-260h60v-480h-60v480Zm-30 200h409q-9-15-14-33t-5-37q0-20 5-37.5t15-32.5H290q-29 0-49.5 20.5T220-210q0 29 20.5 49.5T290-140Z",
  files:
    "M140-160q-24.75 0-42.37-17.63Q80-195.25 80-220v-160h360q24.75 0 42.38-17.63Q500-415.25 500-440v-360h320q24.75 0 42.38 17.62Q880-764.75 880-740v520q0 24.75-17.62 42.37Q844.75-160 820-160H140ZM80-406v-254q0-24.75 17.63-42.38Q115.25-720 140-720h254L80-406Zm119-34 241-241v241H199Z",
  work: "M20 6h-4V4c0-1.11-.89-2-2-2h-4c-1.11 0-2 .89-2 2v2H4c-1.11 0-1.99.89-1.99 2L2 19c0 1.11.89 2 2 2h16c1.11 0 2-.89 2-2V8c0-1.11-.89-2-2-2zm-6 0h-4V4h4v2z",
  database:
    "M12,3C7.58,3 4,4.79 4,7C4,9.21 7.58,11 12,11C16.42,11 20,9.21 20,7C20,4.79 16.42,3 12,3M4,9V12C4,14.21 7.58,16 12,16C16.42,16 20,14.21 20,12V9C20,11.21 16.42,13 12,13C7.58,13 4,11.21 4,9M4,14V17C4,19.21 7.58,21 12,21C16.42,21 20,19.21 20,17V14C20,16.21 16.42,18 12,18C7.58,18 4,16.21 4,14Z",
  // Workspace files: Material's group, person and folder_shared;
  // MDI's source-repository(-multiple) for Repos and a repository.
  group:
    "M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z",
  person: "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
  "folder-shared":
    "M20 6h-8l-2-2H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-5 3c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2zm4 8h-8v-1c0-1.33 2.67-2 4-2s4 .67 4 2v1z",
  repositories:
    "M8,0H20A2,2 0 0,1 22,2V18A2,2 0 0,1 20,20H8A2,2 0 0,1 6,18V2A2,2 0 0,1 8,0M14.75,11.5C17.5,11.5 18.24,9.47 18.43,8.4C19.34,8.11 20,7.26 20,6.25C20,5 19,4 17.75,4C16.5,4 15.5,5 15.5,6.25C15.5,7.19 16.07,8 16.89,8.33C16.67,9 16,10 14,10C12.62,10 11.66,10.35 11,10.84V6.87C11.87,6.56 12.5,5.73 12.5,4.75C12.5,3.5 11.5,2.5 10.25,2.5C9,2.5 8,3.5 8,4.75C8,5.73 8.63,6.56 9.5,6.87V13.13C8.63,13.44 8,14.27 8,15.25C8,16.5 9,17.5 10.25,17.5C11.5,17.5 12.5,16.5 12.5,15.25C12.5,14.32 11.94,13.5 11.13,13.18C11.41,12.5 12.23,11.5 14.75,11.5M10.25,14.5A0.75,0.75 0 0,1 11,15.25A0.75,0.75 0 0,1 10.25,16A0.75,0.75 0 0,1 9.5,15.25A0.75,0.75 0 0,1 10.25,14.5M10.25,4A0.75,0.75 0 0,1 11,4.75A0.75,0.75 0 0,1 10.25,5.5A0.75,0.75 0 0,1 9.5,4.75A0.75,0.75 0 0,1 10.25,4M17.75,5.5A0.75,0.75 0 0,1 18.5,6.25A0.75,0.75 0 0,1 17.75,7A0.75,0.75 0 0,1 17,6.25A0.75,0.75 0 0,1 17.75,5.5M16,22V24H4A2,2 0 0,1 2,22V6H4V22H16Z",
  repository:
    "M6,2H18A2,2 0 0,1 20,4V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V4A2,2 0 0,1 6,2M12.75,13.5C15.5,13.5 16.24,11.47 16.43,10.4C17.34,10.11 18,9.26 18,8.25C18,7 17,6 15.75,6C14.5,6 13.5,7 13.5,8.25C13.5,9.19 14.07,10 14.89,10.33C14.67,11 14,12 12,12C10.62,12 9.66,12.35 9,12.84V8.87C9.87,8.56 10.5,7.73 10.5,6.75C10.5,5.5 9.5,4.5 8.25,4.5C7,4.5 6,5.5 6,6.75C6,7.73 6.63,8.56 7.5,8.87V15.13C6.63,15.44 6,16.27 6,17.25C6,18.5 7,19.5 8.25,19.5C9.5,19.5 10.5,18.5 10.5,17.25C10.5,16.32 9.94,15.5 9.13,15.18C9.41,14.5 10.23,13.5 12.75,13.5M8.25,16.5A0.75,0.75 0 0,1 9,17.25A0.75,0.75 0 0,1 8.25,18A0.75,0.75 0 0,1 7.5,17.25A0.75,0.75 0 0,1 8.25,16.5M8.25,6A0.75,0.75 0 0,1 9,6.75A0.75,0.75 0 0,1 8.25,7.5A0.75,0.75 0 0,1 7.5,6.75A0.75,0.75 0 0,1 8.25,6M15.75,7.5A0.75,0.75 0 0,1 16.5,8.25A0.75,0.75 0 0,1 15.75,9A0.75,0.75 0 0,1 15,8.25A0.75,0.75 0 0,1 15.75,7.5Z",
  // Legacy DBFS's top folders: MDI's folder-clock.
  "folder-clock":
    "M3,4C1.89,4 1,4.89 1,6V18A2,2 0 0,0 3,20H10.26C11.57,21.88 13.71,23 16,23A7,7 0 0,0 23,16C23,14.17 22.28,12.42 21,11.11V8C21,6.89 20.1,6 19,6H11L9,4H3M16,11A5,5 0 0,1 21,16A5,5 0 0,1 16,21A5,5 0 0,1 11,16A5,5 0 0,1 16,11M15,12V17L18.61,19.16L19.36,17.94L16.5,16.25V12H15Z",
};

// Icons drawn on Material Symbols' grid; the others on the 24-pixel one.
const LEVEL_ICON_VIEWBOXES = { book2: "0 -960 960 960", files: "0 -960 960 960" };

// A level of the predefined mappers -> its icon. Other levels (a mapper's own) keep
// the folder icon; CSS can give them one ([data-fs-level], DEVELOPMENT.md).
const LEVEL_ICONS = {
  account: "cloud",
  endpoint: "cloud",
  container: "box",
  bucket: "bucket",
  host: "server",
  drive: "harddisk",
  memory: "chip",
  // Databricks: a workspace's files.
  workspace: "cloud",
  volumes: "bookshelf",
  catalog: "book2",
  schema: "database",
  volume: "files",
  "workspace-files": "work",
  repos: "repositories",
  users: "group",
  user: "person",
  shared: "folder-shared",
  repository: "repository",
  legacy: "folder-clock",
};

// A folder's icon by its level, or null for the folder icon.
function levelIcon(level) {
  const name = level && Object.hasOwn(LEVEL_ICONS, level) ? LEVEL_ICONS[level] : null;
  if (!name) return null;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", LEVEL_ICON_VIEWBOXES[name] ?? "0 0 24 24");
  // jse-level-svg: in its storage's colour (--jse-storage-color, the CSS).
  svg.setAttribute("class", "jse-svg jse-file-svg jse-level-svg");
  svg.setAttribute("aria-hidden", "true");
  svg.dataset.icon = name;
  const path = document.createElementNS(ns, "path");
  path.setAttribute("fill", "#616161");
  // JupyterLab's classes, as the folder icon's: its theme recolours them.
  path.setAttribute("class", "jp-icon3 jp-icon-selectable");
  path.setAttribute("d", LEVEL_ICON_PATHS[name]);
  svg.append(path);
  return svg;
}

// The icons of files no format of the explorer sets one for (their
// DataFormat.file_icon, e.g. CSV and Parquet files' "spreadsheet"): by
// extension, JupyterLab's default file types (@jupyterlab/docregistry, and
// the HTML viewer's), plus the old Excel files (.xls) with its CSV icon.
// Others get the plain file icon.
const FILE_ICON_EXTENSIONS = {
  ".xls": "spreadsheet",
  ".ipynb": "notebook",
  ".pdf": "pdf",
  ".py": "python",
  ".jl": "julia",
  ".r": "r-kernel",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".html": "html5",
  ".tif": "image",
  ".tiff": "image",
  ".aac": "audio",
  ".midi": "audio",
  ".mid": "audio",
  ".mp3": "audio",
  ".wav": "audio",
  ".ogg": "audio",
  ".m4a": "audio",
  ".flac": "audio",
  ".opus": "audio",
  ".mp4": "video",
  ".mpeg": "video",
  ".webm": "video",
  ".ogv": "video",
  ".avi": "video",
  ".mov": "video",
};

// The icon of an item, as an SVG element: `formatIcon`, the file_icon of the
// file's format if it has one, else the one JupyterLab's file browser shows.
// An icon of the format's own comes with its SVG `markup`: shown as an
// image, in which its scripts, if any, never run. A folder of a `level`
// (FileSystemMapper.levels, e.g. "bucket") gets that level's icon.
function fileIcon(name, isDir, formatIcon = null, markup = null, level = null) {
  if (isDir && level) {
    const svg = levelIcon(level);
    if (svg) return svg;
  }
  if (!isDir && formatIcon && markup) {
    const img = h("img", { className: "jse-svg jse-file-svg", alt: "", src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}` });
    img.setAttribute("aria-hidden", "true");
    img.dataset.icon = formatIcon;
    return img;
  }
  let key = "file";
  if (isDir) key = "folder";
  else if (formatIcon && Object.hasOwn(FILE_ICON_SVGS, formatIcon)) key = formatIcon;
  else {
    const dot = name.lastIndexOf(".");
    if (dot > 0) key = FILE_ICON_EXTENSIONS[name.slice(dot).toLowerCase()] ?? "file";
  }
  const box = document.createElement("template");
  box.innerHTML = FILE_ICON_SVGS[key]; // constants above, not user data
  const svg = box.content.firstElementChild;
  svg.setAttribute("class", "jse-svg jse-file-svg");
  svg.setAttribute("aria-hidden", "true");
  svg.dataset.icon = key; // e.g. "spreadsheet", for tests
  return svg;
}
