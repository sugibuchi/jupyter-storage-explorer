// "Open in JupyterLab": files of Storage Explorer's storages open in
// JupyterLab's own editors and viewers (text editor, notebook, CSV and image
// viewers, ...) and save back to the storage.
//
// They are served by a drive of this extension: JupyterLab asks drives for
// the files whose paths start with their name ("StorageExplorer:..."). This
// drive asks the explorer that opened the file (an anywidget, see
// storage_explorer.js) to read or save it, through the explorer's kernel, so
// no server setup or credentials are needed beyond the explorer's own.
//
// The drive only serves the files explorers opened on this page, under the
// path it gave them, "<storage>/<path in the storage>". Anything else (a path
// typed in "Open from Path", "Save As" into the drive, new files, renames,
// deletions, listing folders) is refused: files are managed in the explorer.
// The drive is not shown in the file browser; after a page reload, documents
// left open (or reopened from "Open Recent") are refused until opened from
// an explorer again.

import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { PathExt } from '@jupyterlab/coreutils';
import { Contents, ServerConnection } from '@jupyterlab/services';
import { ISignal, Signal } from '@lumino/signaling';

const DRIVE_NAME = 'StorageExplorer';
// Where explorers find this extension (see storage_explorer.js).
const REGISTRY = Symbol.for('jupyter-storage-explorer.jupyterlab');
const REFUSED = 'Files of Storage Explorer are opened, renamed and deleted in the explorer.';

// The options JupyterLab reads a file with.
interface IGetOptions {
  contentType: string | null;
  format: string | null;
  content: boolean;
}

// A file an explorer opens (see storage_explorer.js): it reads and saves it
// through its kernel, resolving with a contents model, or rejecting.
interface IExplorerFile {
  explorer: string; // the explorer's id
  storage: string; // the storage's name in it
  path: string; // the file's path in the storage
  get(options: IGetOptions): Promise<Contents.IModel>;
  save(options: { contentType: string | null; format: string | null; content: unknown }): Promise<Contents.IModel>;
}

class StorageDrive implements Contents.IDrive {
  readonly name = DRIVE_NAME;
  private files = new Map<string, IExplorerFile>();
  private changed = new Signal<Contents.IDrive, Contents.IChangedArgs>(this);
  private disposed = false;

  constructor(readonly serverSettings: ServerConnection.ISettings) {}

  get fileChanged(): ISignal<Contents.IDrive, Contents.IChangedArgs> {
    return this.changed;
  }

  get isDisposed(): boolean {
    return this.disposed;
  }

  dispose(): void {
    this.disposed = true;
    Signal.clearData(this);
  }

  // The path a file is served under, "<storage>/<path>". The same file from
  // the same explorer keeps its path, so it opens in the tab already showing
  // it; another explorer with a storage of the same name gets "<storage> (2)".
  add(file: IExplorerFile): string {
    const inStorage = file.path.replace(/^\/+/, '');
    for (let n = 1; ; n++) {
      const storage = n === 1 ? file.storage : `${file.storage} (${n})`;
      const path = `${storage}/${inStorage}`;
      const known = this.files.get(path);
      if (!known || known.explorer === file.explorer) {
        this.files.set(path, file);
        return path;
      }
    }
  }

  private file(localPath: string): IExplorerFile {
    const file = this.files.get(localPath);
    if (!file) {
      throw new Error(`${localPath} is not open: open it from Storage Explorer.`);
    }
    return file;
  }

  async get(localPath: string, options?: Contents.IFetchOptions): Promise<Contents.IModel> {
    const model = await this.file(localPath).get({
      contentType: options?.type ?? null,
      format: options?.format ?? null,
      content: options?.content ?? true
    });
    return { ...model, name: PathExt.basename(localPath), path: localPath };
  }

  async save(localPath: string, options: Partial<Contents.IModel> = {}): Promise<Contents.IModel> {
    const model = await this.file(localPath).save({
      contentType: options.type ?? null,
      format: options.format ?? null,
      content: options.content
    });
    const saved = { ...model, name: PathExt.basename(localPath), path: localPath };
    this.changed.emit({ type: 'save', oldValue: null, newValue: saved });
    return saved;
  }

  // A checkpoint is the file itself: JupyterLab makes one when it opens a
  // file, and "Revert to Checkpoint" reads the file again.
  async createCheckpoint(localPath: string): Promise<Contents.ICheckpointModel> {
    this.file(localPath);
    return { id: 'storage', last_modified: new Date().toISOString() };
  }

  async listCheckpoints(localPath: string): Promise<Contents.ICheckpointModel[]> {
    this.file(localPath);
    return [];
  }

  async restoreCheckpoint(): Promise<void> {
    throw new Error(REFUSED);
  }

  async deleteCheckpoint(): Promise<void> {
    // Nothing kept.
  }

  async getDownloadUrl(): Promise<string> {
    throw new Error('Download files from Storage Explorer.');
  }

  async newUntitled(): Promise<Contents.IModel> {
    throw new Error(REFUSED);
  }

  async delete(): Promise<void> {
    throw new Error(REFUSED);
  }

  async rename(): Promise<Contents.IModel> {
    throw new Error(REFUSED);
  }

  async copy(): Promise<Contents.IModel> {
    throw new Error(REFUSED);
  }
}

export const filesPlugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-storage-explorer-launcher:files',
  description: "Opens Storage Explorer's files in JupyterLab's editors and viewers.",
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    const contents = app.serviceManager.contents;
    const drive = new StorageDrive(contents.serverSettings);
    contents.addDrive(drive);
    (globalThis as Record<symbol, unknown>)[REGISTRY] = {
      // Whether JupyterLab knows the type of a file of this name (e.g. CSV,
      // JSON, notebooks, images), so has an editor or viewer for it; the
      // explorer also opens the files it reads as text.
      canOpen(name: string): boolean {
        return app.docRegistry.getFileTypesForPath(name).length > 0;
      },
      async open(file: IExplorerFile): Promise<void> {
        const path = drive.add(file);
        await app.commands.execute('docmanager:open', { path: `${DRIVE_NAME}:${path}` });
      }
    };
  }
};
