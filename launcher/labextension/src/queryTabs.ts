// "Query data in new tab": Storage Explorer's data browser in a JupyterLab
// tab of its own.
//
// The explorer's kernel creates a DataExplorer widget of the same query and
// tells its model id (see storage_explorer.js, `openQueryTab`). The tab shows
// that widget with the output renderers of the notebook or console holding the
// explorer, as JupyterLab's "Create New View for Output" does: ipywidgets ties
// widgets to that document's kernel connection, so the tab cannot render them
// with any other. The tab closes when that document closes or its kernel
// changes or restarts, which loses the widget; closing the tab tells the
// kernel to let the widget go. Tabs are not restored after a page reload.

import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { MainAreaWidget } from '@jupyterlab/apputils';
import type { IRenderMimeRegistry } from '@jupyterlab/rendermime';
import { spreadsheetIcon } from '@jupyterlab/ui-components';
import type { Widget } from '@lumino/widgets';

// Where explorers find this extension's functions (see storage_explorer.js).
const REGISTRY = Symbol.for('jupyter-storage-explorer.jupyterlab');
const WIDGET_MIME = 'application/vnd.jupyter.widget-view+json';
const TAB_CLASS = 'jse-query-tab';

// A tab an explorer asks for.
interface IQueryTab {
  modelId: string; // the DataExplorer widget's model id
  title: string;
  caption: string; // the data's URL
  owner: HTMLElement; // the explorer's element, in a notebook or a console
  onClose(): void;
}

// What the tab needs of the notebook or console holding the explorer.
interface IOwner extends Widget {
  content?: { rendermime?: IRenderMimeRegistry }; // a notebook panel
  console?: { rendermime?: IRenderMimeRegistry }; // a console panel
  sessionContext?: {
    kernelChanged: { connect(fn: () => void): void };
    statusChanged: { connect(fn: (_: unknown, status: string) => void): void };
  };
}

function ownerOf(app: JupyterFrontEnd, node: HTMLElement): IOwner | undefined {
  for (const widget of app.shell.widgets('main')) {
    if (widget.node.contains(node)) {
      return widget as IOwner;
    }
  }
  return undefined;
}

async function openTab(app: JupyterFrontEnd, tab: IQueryTab): Promise<void> {
  const owner = ownerOf(app, tab.owner);
  const rendermime = owner?.content?.rendermime ?? owner?.console?.rendermime;
  if (!owner || !rendermime?.mimeTypes.includes(WIDGET_MIME)) {
    throw new Error('the explorer is not in a notebook or console tab of this page');
  }
  const renderer = rendermime.createRenderer(WIDGET_MIME);
  await renderer.renderModel({
    data: { [WIDGET_MIME]: { model_id: tab.modelId, version_major: 2, version_minor: 1 } },
    metadata: {},
    trusted: true,
    setData: () => undefined
  });
  const panel = new MainAreaWidget({ content: renderer });
  panel.id = `jse-query-tab-${tab.modelId}`;
  panel.addClass(TAB_CLASS);
  // No toolbar: the data browser has its own. Hidden through Lumino, which
  // lays the tab out again (hidden with CSS, it would keep its room).
  panel.toolbar.hide();
  panel.title.label = tab.title;
  panel.title.caption = tab.caption;
  panel.title.icon = spreadsheetIcon;
  panel.title.closable = true;
  panel.disposed.connect(() => tab.onClose());
  // The widget lives in the owner's kernel: gone with it.
  const close = (): void => {
    if (!panel.isDisposed) {
      panel.dispose();
    }
  };
  owner.disposed.connect(close);
  owner.sessionContext?.kernelChanged.connect(close);
  owner.sessionContext?.statusChanged.connect((_, status) => {
    if (['restarting', 'autorestarting', 'dead'].includes(status)) {
      close();
    }
  });
  app.shell.add(panel, 'main', { mode: 'tab-after', ref: owner.id });
  app.shell.activateById(panel.id);
}

export const queryTabsPlugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-storage-explorer-launcher:query-tabs',
  description: "Opens Storage Explorer's data browser in tabs of their own.",
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    const registry = ((globalThis as Record<symbol, any>)[REGISTRY] ??= {});
    registry.openWidget = (tab: IQueryTab) => openTab(app, tab);
  }
};
