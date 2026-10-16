// Files dragged from Storage Explorer onto JupyterLab's file browser are
// downloaded to the Jupyter server, into the folder dropped on (a folder row)
// or the one the browser shows, after asking the user.
//
// The explorer (an anywidget, see static/storage_explorer/transfers.js) marks its drags with
// DOWNLOAD_MIME and puts the drag, with a `download` function that asks its
// kernel to copy the files, in a page-wide registry: drag data can only be
// text. The file browser handles native drops itself (uploads from the
// computer), so these are caught first, on the listing, in the capture phase.

import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { Dialog, Notification, showDialog } from '@jupyterlab/apputils';
import { DirListing, FileBrowser, IFileBrowserFactory } from '@jupyterlab/filebrowser';

const DOWNLOAD_MIME = 'application/x-jupyter-storage-explorer-download';
const DRAG_REGISTRY = Symbol.for('jupyter-storage-explorer.drag');
// JupyterLab's classes for a highlighted folder row, and the whole listing.
const DROP_TARGET_CLASS = 'jp-mod-dropTarget';
const LISTING_DROP_CLASS = 'jp-mod-native-drop';

type IfExists = 'ask' | 'overwrite' | 'skip';

interface IDownloadResult {
  conflicts?: string[];
  copied?: string[];
  skipped?: string[];
  errors?: string[];
}

// The drag the explorer registers (see static/storage_explorer/transfers.js).
interface IExplorerDrag {
  names: string[];
  // `dest`: a folder relative to the Jupyter server's.
  download(dest: string, ifExists: IfExists): Promise<IDownloadResult>;
}

function describeFiles(names: string[]): string {
  return names.length === 1 ? names[0] : `${names.length} files`;
}

const isExplorerDrag = (ev: DragEvent): boolean =>
  Array.from(ev.dataTransfer?.types ?? []).includes(DOWNLOAD_MIME);

// Asks, downloads, then asks again for files that already exist.
async function download(
  browser: FileBrowser,
  drag: IExplorerDrag,
  dir: string,
  localDir: string
): Promise<void> {
  const where = `/${localDir}`;
  const confirm = await showDialog({
    title: 'Download to Jupyter',
    body: `Download ${describeFiles(drag.names)} from Storage Explorer to ${where}?`,
    buttons: [Dialog.cancelButton(), Dialog.okButton({ label: 'Download' })]
  });
  if (!confirm.button.accept) {
    return;
  }
  const run = async (ifExists: IfExists): Promise<IDownloadResult | null> => {
    const result = await drag.download(localDir, ifExists);
    if (!result.conflicts?.length) {
      return result;
    }
    const exist = result.conflicts.length === 1 ? 'exists' : 'exist';
    const choice = await showDialog({
      title: 'Download to Jupyter',
      body: `${describeFiles(result.conflicts)} already ${exist} in ${where}.`,
      buttons: [
        Dialog.cancelButton(),
        Dialog.createButton({ label: 'Skip existing', actions: ['skip'] }),
        Dialog.warnButton({ label: 'Overwrite', actions: ['overwrite'] })
      ]
    });
    const action = choice.button.actions.find(a => a === 'skip' || a === 'overwrite');
    return action ? run(action as IfExists) : null;
  };
  const result = await run('ask');
  if (result === null) {
    return;
  }
  const { copied = [], skipped = [], errors = [] } = result;
  if (copied.length) {
    // Show the new files (when the browser still shows that folder).
    if (browser.model.path === dir) {
      await browser.model.refresh();
    }
    Notification.success(`Downloaded ${describeFiles(copied)} to ${where}`, { autoClose: 5000 });
  }
  if (skipped.length) {
    Notification.info(`Skipped ${describeFiles(skipped)}: already in ${where}`, { autoClose: 5000 });
  }
  for (const error of errors) {
    Notification.error(`Download failed: ${error}`);
  }
}

// Makes `browser`'s listing a drop target for the explorer's files.
function acceptDownloads(browser: FileBrowser, app: JupyterFrontEnd): void {
  // `listing` is protected: subclasses use it, and so does this extension.
  const listing = (browser as unknown as { listing: DirListing }).listing;
  let highlighted: HTMLElement | null = null;

  const highlight = (el: HTMLElement | null): void => {
    if (el === highlighted) {
      return;
    }
    highlighted?.classList.remove(DROP_TARGET_CLASS, LISTING_DROP_CLASS);
    highlighted = el;
    highlighted?.classList.add(el === listing.node ? LISTING_DROP_CLASS : DROP_TARGET_CLASS);
  };

  // The folder under the pointer: a folder row, else the folder shown.
  const target = (ev: DragEvent): { dir: string; el: HTMLElement } => {
    const row = ev.target instanceof Element ? ev.target.closest<HTMLElement>('.jp-DirListing-item') : null;
    if (row && listing.contentNode.contains(row)) {
      const index = Array.prototype.indexOf.call(listing.contentNode.children, row);
      const item = Array.from(listing.sortedItems())[index];
      if (item?.type === 'directory') {
        return { dir: item.path, el: row };
      }
    }
    return { dir: browser.model.path, el: listing.node };
  };

  const onDragOver = (ev: DragEvent): void => {
    if (!isExplorerDrag(ev)) {
      return;
    }
    ev.preventDefault(); // allows the drop
    ev.stopPropagation(); // keeps the listing's own (upload) handling out
    if (ev.dataTransfer) {
      ev.dataTransfer.dropEffect = 'copy';
    }
    highlight(target(ev).el);
  };
  listing.node.addEventListener('dragenter', onDragOver, true);
  listing.node.addEventListener('dragover', onDragOver, true);
  listing.node.addEventListener(
    'dragleave',
    ev => {
      if (!isExplorerDrag(ev)) {
        return;
      }
      ev.stopPropagation();
      if (!(ev.relatedTarget instanceof Node && listing.node.contains(ev.relatedTarget))) {
        highlight(null);
      }
    },
    true
  );
  listing.node.addEventListener(
    'drop',
    ev => {
      if (!isExplorerDrag(ev)) {
        return;
      }
      ev.preventDefault();
      ev.stopPropagation();
      highlight(null);
      const drag = (globalThis as Record<symbol, unknown>)[DRAG_REGISTRY] as IExplorerDrag | undefined;
      if (!drag) {
        return;
      }
      const { dir } = target(ev);
      // Without the drive prefix (e.g. "RTC:"): relative to the server's folder.
      const localDir = app.serviceManager.contents.localPath(dir);
      download(browser, drag, dir, localDir).catch(error =>
        Notification.error(`Download failed: ${error}`)
      );
    },
    true
  );
}

export const downloadPlugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-storage-explorer-launcher:download',
  description: 'Downloads files dragged from Storage Explorer onto the file browser.',
  autoStart: true,
  requires: [IFileBrowserFactory],
  activate: (app: JupyterFrontEnd, factory: IFileBrowserFactory) => {
    factory.tracker.forEach(browser => acceptDownloads(browser, app));
    factory.tracker.widgetAdded.connect((_, browser) => acceptDownloads(browser, app));
  }
};
