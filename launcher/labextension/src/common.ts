// What the extension's plugins share with each other, and with the explorer's
// own frontend (static/common.js).

// Where explorers find this extension's functions (see static/storage_explorer/jupyterlab.js).
const REGISTRY = Symbol.for('jupyter-storage-explorer.jupyterlab');

// The page-wide object explorers find this extension's functions in.
export function registry(): Record<string, unknown> {
  return ((globalThis as Record<symbol, any>)[REGISTRY] ??= {});
}

// Characters that change how the text around them reads, or are not seen, as
// the explorer's `visible()` shows them (static/common.js): a name cannot then
// pass for another.
const HIDDEN_CHARACTERS =
  // eslint-disable-next-line no-control-regex
  /[\u0000-\u001f\u007f-\u009f­؜᠎​-‏‪-‮⁠-⁯﻿￹-￻]/g;

// `text` (a file name, a path, a message naming files) as users should read
// it, with HIDDEN_CHARACTERS shown as \uXXXX escapes. Only for display.
export function visible(text: string): string {
  return String(text).replace(
    HIDDEN_CHARACTERS,
    c => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`
  );
}
