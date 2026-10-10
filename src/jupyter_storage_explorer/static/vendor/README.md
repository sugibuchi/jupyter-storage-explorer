# Vendored JavaScript libraries

Used to render Markdown previews in the browser. They are loaded on demand:
the widget asks the kernel for a file's source (only the files listed in
`storage_explorer.py`'s `_VENDOR_FILES`) and imports it as a module.

| File | Library | Version | License |
|---|---|---|---|
| `marked.esm.js` | [marked](https://github.com/markedjs/marked) (the Markdown parser JupyterLab uses) | 16.4.2 | MIT, see `marked.LICENSE.md` |
| `purify.es.mjs` | [DOMPurify](https://github.com/cure53/DOMPurify) (removes scripts etc. from the HTML) | 3.4.16 | Apache-2.0 or MPL-2.0, see `dompurify.LICENSE` |

Downloaded unmodified from jsDelivr (`npm/marked@16.4.2/lib/marked.esm.js`,
`npm/dompurify@3/dist/purify.es.mjs`), except that the trailing
`//# sourceMappingURL=` line was removed, as the source maps are not included.
