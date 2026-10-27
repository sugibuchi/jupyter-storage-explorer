// "View in a new tab": Storage Explorer's views in JupyterLab tabs of their
// own.
//
// The tab opens at once, showing that the view loads: the explorer's kernel
// reads it in a worker thread, which can take minutes (e.g. a Spark session
// starting). The kernel then creates a widget of the view, a DataExplorer, a
// TableSetTab or a ViewTab, and tells its model id (see
// static/storage_explorer/jupyterlab.js, `openViewTab`), or why it failed.
// A view asking the user first comes as the widget of its prompt, which the
// tab shows until the view's widget replaces it.
// The tab shows that widget with the output renderers of the notebook or
// console holding the explorer, as JupyterLab's "Create New View for Output"
// does: ipywidgets ties widgets to that document's kernel connection, so the
// tab cannot render them with any other. The tab closes when that document
// closes or its kernel changes or restarts, which loses the widget; closing
// the tab tells the kernel to let the widget go, or to drop the view loading.
// Tabs are not restored after a page reload.

import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { MainAreaWidget } from '@jupyterlab/apputils';
import type { IRenderMimeRegistry } from '@jupyterlab/rendermime';
import { spreadsheetIcon } from '@jupyterlab/ui-components';
import { BoxPanel, Widget } from '@lumino/widgets';

import { registry, visible } from './common';

const WIDGET_MIME = 'application/vnd.jupyter.widget-view+json';
const TAB_CLASS = 'jse-query-tab';
// The owner's kernel statuses in which the tab's widget is gone: restarted
// from the Kernel menu ("restarting"), by the server ("autorestarting") or by
// another client (only "starting"), or dead.
const KERNEL_GONE = ['restarting', 'autorestarting', 'starting', 'dead'];

// A tab an explorer asks for.
interface IViewTab {
  title: string;
  caption: string; // the item's URL
  owner: HTMLElement; // the explorer's element, in a notebook or a console
  onClose(): void;
}

// What the explorer does with the tab once the kernel has answered.
interface IViewTabHandle {
  show(modelId: string): Promise<void>; // the widget's model id; replaces the one shown
  fail(message: string): void;
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

// The notebook or console holding the explorer's element: a tab of the main
// area, or the side panel's console (sidePanel.ts, `explorerConsole`).
function ownerOf(app: JupyterFrontEnd, node: HTMLElement): IOwner | undefined {
  for (const area of ['main', 'left'] as const) {
    for (const widget of app.shell.widgets(area)) {
      if (widget.node.contains(node)) {
        return ((widget as { explorerConsole?: IOwner | null }).explorerConsole ??
          widget) as IOwner;
      }
    }
  }
  return undefined;
}

function openTab(app: JupyterFrontEnd, tab: IViewTab): IViewTabHandle {
  const owner = ownerOf(app, tab.owner);
  const rendermime = owner?.content?.rendermime ?? owner?.console?.rendermime;
  if (!owner || !rendermime?.mimeTypes.includes(WIDGET_MIME)) {
    throw new Error('the explorer is not in a notebook or console tab of this page');
  }
  // "Loading…" until the kernel answers, then the widget, or the error.
  const message = new Widget();
  message.addClass('jse-view-tab-message');
  message.node.textContent = 'Loading…';
  const content = new BoxPanel();
  content.addWidget(message);
  const panel = new MainAreaWidget({ content });
  panel.id = `jse-query-tab-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  panel.addClass(TAB_CLASS);
  // No toolbar: the views have their own heads. Hidden through Lumino, which
  // lays the tab out again (hidden with CSS, it would keep its room).
  panel.toolbar.hide();
  panel.title.label = visible(tab.title);
  panel.title.caption = visible(tab.caption);
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
    if (KERNEL_GONE.includes(status)) {
      close();
    }
  });
  // Beside the owner's tab; for the side panel's, beside the tab shown.
  const inMain = Array.from(app.shell.widgets('main')).includes(owner);
  app.shell.add(panel, 'main', inMain ? { mode: 'tab-after', ref: owner.id } : {});
  app.shell.activateById(panel.id);
  // The widget shown: a prompt's is replaced by its view's (see `show`).
  let shown: Widget | null = null;
  return {
    async show(modelId: string): Promise<void> {
      if (panel.isDisposed) {
        return;
      }
      const renderer = rendermime.createRenderer(WIDGET_MIME);
      await renderer.renderModel({
        data: { [WIDGET_MIME]: { model_id: modelId, version_major: 2, version_minor: 1 } },
        metadata: {},
        trusted: true,
        setData: () => undefined
      });
      if (panel.isDisposed) {
        renderer.dispose();
        return;
      }
      message.dispose();
      shown?.dispose();
      shown = renderer;
      content.addWidget(renderer);
      BoxPanel.setStretch(renderer, 1);
    },
    fail(error: string): void {
      if (message.isDisposed) {
        return;
      }
      // Its first line says what went wrong (see error_text in the
      // explorer's _explorer/common.py); the rest, e.g. a Java stack trace,
      // is folded under "Details".
      const [summary, ...rest] = error.replace(/\t/g, '    ').split(/\r?\n/).map(visible);
      message.node.textContent = summary;
      const more = rest.join('\n').trim();
      if (more) {
        const details = document.createElement('details');
        const label = document.createElement('summary');
        label.textContent = 'Details';
        const pre = document.createElement('pre');
        pre.textContent = more;
        details.append(label, pre);
        message.node.append(details);
      }
      message.addClass('jse-mod-error');
    }
  };
}

export const queryTabsPlugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-storage-explorer-launcher:query-tabs',
  description: "Opens Storage Explorer's views in tabs of their own.",
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    registry().openViewTab = (tab: IViewTab) => openTab(app, tab);
  }
};
