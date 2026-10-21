// Storage Explorer in the JupyterLab launcher: the item opens a new tab with
// the explorer. The tab is a code console whose prompt and input are hidden:
// consoles get a widget manager from ipywidgets, so the explorer (an
// anywidget) renders there. The console runs `launch()` from the Python
// package jupyter_storage_explorer_launcher, which shows the explorer the
// launcher.py files describe (see there). The kernel is shut down when the
// tab closes.
//
// JupyterLab restores open consoles when the page is reloaded, reconnected to
// their kernels (or, after a server restart, with new ones) but without their
// outputs. Explorer tabs are recognised by their session name and set up
// again, running `launch()` once more. A tab whose session is lost while the
// page stays open (the server restarted), or whose kernel is changed or
// restarted, is replaced by a new one in its place: ipywidgets binds a
// console's widgets to its first kernel, and they do not survive a restart,
// so the explorer could not be shown there again.
//
// Each tab's view (the storage shown, the folder of each storage) is kept in
// JupyterLab's state database, which is saved with the workspace on the
// server: the explorer reports it with a DOM event, and `launch()` gets it
// back, so the tab reopens where it was.
//
// The side panel (sidePanel.ts) is such a console too, of a session name of
// its own, moved into a panel of JupyterLab's left side bar, where it runs
// `launch(sidebar=True)`: the narrow explorer, without tree or preview panel.
//
// A second plugin (download.ts) downloads files dragged from any explorer,
// in a tab or a notebook, onto JupyterLab's file browser; a third (files.ts)
// opens the explorers' files in JupyterLab's own editors and viewers; a
// fourth (queryTabs.ts) opens their data browser in tabs of its own.

import { ILayoutRestorer, JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { ICommandPalette } from '@jupyterlab/apputils';
import { ConsolePanel, IConsoleTracker } from '@jupyterlab/console';
import { ILauncher } from '@jupyterlab/launcher';
import { IStateDB } from '@jupyterlab/statedb';
import { LabIcon } from '@jupyterlab/ui-components';

import { downloadPlugin } from './download';
import { filesPlugin } from './files';
import { queryTabsPlugin } from './queryTabs';
import { ExplorerSidePanel } from './sidePanel';
import iconSvg from '../style/storage-explorer.svg';

const PLUGIN_ID = 'jupyter-storage-explorer-launcher:plugin';
const COMMAND = 'storage-explorer:open';
const SIDE_PANEL_COMMAND = 'storage-explorer:show-side-panel';
const TITLE = 'Storage Explorer';
// Session names of explorer tabs and of the side panel's console; they
// survive page reloads, so they identify them.
const SESSION_NAME = TITLE;
const SIDE_SESSION_NAME = `${TITLE} (side panel)`;
// Marks the console as an explorer tab, for the styles hiding its prompt and input.
const PANEL_CLASS = 'jse-launcher-panel';
// Dispatched by an explorer (static/storage_explorer.js) on its element, and
// bubbling up to the tab, when the storage or folder shown changes:
// {filesystem, folder}.
const VIEW_EVENT = 'jupyter-storage-explorer:view';

// A tab's view as saved: the storage shown, and the folder of each storage
// shown so far, for when the user switches to it.
interface IView {
  filesystem: string;
  folders: { [filesystem: string]: string };
}

export const storageExplorerIcon = new LabIcon({
  name: 'jupyter-storage-explorer-launcher:icon',
  svgstr: iconSvg
});

// The icon of explorer tabs, sized for a tab. JupyterLab binds this style to a
// widget's icon only when the widget is added to the shell; a tab whose icon is
// set afterwards (e.g. a restored console, which ExplorerTab sets up when it is
// already there) would otherwise show the SVG at its own size, 128px.
const tabIcon = storageExplorerIcon.bindprops({ stylesheet: 'mainAreaTab' });
// The same in the side bar.
const sideBarIcon = storageExplorerIcon.bindprops({ stylesheet: 'sideBar' });

// The view saved for the tab whose console session has path `path`.
const viewKey = (path: string): string => `${PLUGIN_ID}:view:${path}`;

// `cwd`: the launcher's folder (the one shown in the file browser), where the
// kernel starts, so "." in launcher.py is that folder. Without it (e.g. from
// the command palette), the console uses the file browser's folder itself.
// The new console is then set up by `ExplorerTab`, like a restored one.
// `options`: more for console:create, e.g. where to open (`ref`, `insertMode`).
async function openExplorer(
  app: JupyterFrontEnd,
  cwd?: string,
  options: { [key: string]: any } = {}
): Promise<ConsolePanel> {
  const specs = app.serviceManager.kernelspecs;
  await specs.ready;
  return app.commands.execute('console:create', {
    ...(cwd !== undefined ? { basePath: cwd } : {}),
    name: SESSION_NAME,
    activate: true,
    kernelPreference: { name: specs.specs?.default, shouldStart: true },
    ...options
  });
}

// A console with the explorer's session name, new or restored, as an
// explorer tab: `launch()` runs in its kernel, with its saved view. With
// `side`, the side panel's console instead, which it holds.
class ExplorerTab {
  // The kernel `launch()` last ran in, so that it runs once per kernel.
  private launchedIn: string | null = null;
  // Set once a new tab replaces this one, which keeps its saved view.
  private replaced = false;

  constructor(
    private app: JupyterFrontEnd,
    private panel: ConsolePanel,
    private state: IStateDB | null,
    private side: ExplorerSidePanel | null = null
  ) {
    const session = panel.sessionContext;
    panel.addClass(PANEL_CLASS);
    this.decorate();
    // The kernel only serves this tab (restored consoles lose this preference).
    session.kernelPreference = { ...session.kernelPreference, shutdownOnDispose: true };
    session.kernelChanged.connect((_, change) => {
      if (this.launchedIn !== null && change.newValue && change.newValue.id !== this.launchedIn) {
        void this.replace(); // the kernel was changed
      } else {
        void this.launch();
      }
    });
    session.sessionChanged.connect((_, change) => {
      // JupyterLab names a console after its session, or "Console" without one.
      this.decorate();
      if (change.newValue === null) {
        void this.replace(); // e.g. the server restarted
      }
    });
    session.statusChanged.connect((_, status) => {
      // The kernel restarts (the Kernel menu: "restarting"; the server, e.g.
      // after a crash: "autorestarting"; another client: only "starting"),
      // losing the explorer, and the console's widgets do not come back with
      // it: a new tab, with a new kernel.
      const restarting = ['restarting', 'autorestarting', 'starting'].includes(status);
      if (restarting && this.launchedIn !== null) {
        void this.replace();
      }
    });
    panel.node.addEventListener(VIEW_EVENT, ev => void this.saveView(ev as CustomEvent));
    // Closed by the user (not on page unloads, which do not dispose widgets).
    panel.disposed.connect(() => {
      if (!this.replaced) {
        void this.state?.remove(this.stateKey);
      }
    });
    void session.ready.then(() => this.launch());
  }

  // Per tab: the console's session path, which restoration keeps.
  private get stateKey(): string {
    return viewKey(this.panel.sessionContext.path);
  }

  private decorate(): void {
    this.panel.title.label = TITLE;
    this.panel.title.icon = tabIcon;
  }

  // Runs `launch()` in the tab's kernel, once per kernel, with the saved view.
  private async launch(): Promise<void> {
    const kernel = this.panel.sessionContext.session?.kernel;
    if (!kernel || this.panel.isDisposed || this.launchedIn === kernel.id) {
      return;
    }
    this.launchedIn = kernel.id;
    this.decorate();
    const view = await this.fetchView();
    // The view as a Python string (JSON is valid Python string syntax), parsed by launch().
    const args = [
      ...(view ? [`view=${JSON.stringify(JSON.stringify(view))}`] : []),
      ...(this.side ? ['sidebar=True'] : [])
    ];
    await this.panel.console.inject(
      `from jupyter_storage_explorer_launcher import launch as __jse_launch\n__jse_launch(${args.join(', ')})`
    );
  }

  // Opens a new explorer tab in place of this one, with its view, and closes
  // this one. The new console gets a path of its own, under which the view
  // is saved before it opens.
  private async replace(): Promise<void> {
    const panel = this.panel;
    const session = panel.sessionContext;
    if (this.replaced || panel.isDisposed || session.isDisposed || session.isTerminating) {
      return;
    }
    this.replaced = true;
    const oldPath = session.path;
    const dir = oldPath.includes('/') ? oldPath.slice(0, oldPath.lastIndexOf('/')) : '';
    const name = `storage-explorer-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
    const path = dir ? `${dir}/${name}` : name;
    const view = await this.fetchView();
    if (view && this.state) {
      await this.state.save(viewKey(path), view as any);
    }
    const kernelPreference = { name: session.kernelPreference.name, shouldStart: true };
    if (this.side) {
      await this.side.open({ path, kernelPreference });
    } else {
      await openExplorer(this.app, undefined, {
        path,
        ref: panel.id,
        insertMode: 'tab-after',
        activate: panel.isVisible,
        kernelPreference
      });
    }
    await this.state?.remove(this.stateKey);
    panel.dispose();
  }

  private async fetchView(): Promise<IView | undefined> {
    try {
      return (await this.state?.fetch(this.stateKey)) as IView | undefined;
    } catch {
      return undefined;
    }
  }

  // Keeps the folder of every storage shown so far, and which one is shown.
  private async saveView(ev: CustomEvent): Promise<void> {
    const { filesystem, folder } = ev.detail ?? {};
    if (!this.state || typeof filesystem !== 'string' || typeof folder !== 'string') {
      return;
    }
    const saved = await this.fetchView();
    const view: IView = { filesystem, folders: { ...saved?.folders, [filesystem]: folder } };
    await this.state.save(this.stateKey, view as any);
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: PLUGIN_ID,
  description: 'Opens Storage Explorer in a new tab from the launcher.',
  autoStart: true,
  requires: [IConsoleTracker],
  optional: [ILauncher, ICommandPalette, IStateDB, ILayoutRestorer],
  activate: (
    app: JupyterFrontEnd,
    consoles: IConsoleTracker,
    launcher: ILauncher | null,
    palette: ICommandPalette | null,
    state: IStateDB | null,
    restorer: ILayoutRestorer | null
  ) => {
    // The side panel, in the left side bar; its console is made when it is first shown.
    const side = new ExplorerSidePanel(
      app,
      options => openExplorer(app, undefined, { name: SIDE_SESSION_NAME, ...options }),
      sideBarIcon,
      TITLE
    );
    app.shell.add(side, 'left', { rank: 300 });
    // Reopened after a page reload if it was open.
    restorer?.add(side, side.id);
    // Connected before JupyterLab restores the layout, so restored tabs are seen too.
    consoles.widgetAdded.connect((_, panel) => {
      if (panel.sessionContext.name === SESSION_NAME) {
        new ExplorerTab(app, panel, state);
      } else if (panel.sessionContext.name === SIDE_SESSION_NAME) {
        new ExplorerTab(app, panel, state, side);
        // Restored by JupyterLab, in the main area: back into the panel. One
        // the panel is making, it takes in itself.
        if (!side.isOpening) {
          side.adopt(panel);
        }
      }
    });
    app.commands.addCommand(COMMAND, {
      label: TITLE,
      caption: 'Browse storage and query data in a new tab',
      icon: args => (args['isPalette'] ? undefined : storageExplorerIcon),
      execute: args => openExplorer(app, args['cwd'] as string | undefined)
    });
    app.commands.addCommand(SIDE_PANEL_COMMAND, {
      label: 'Show Storage Explorer in the Side Bar',
      caption: 'Browse storage in the left side bar',
      execute: () => app.shell.activateById(side.id)
    });
    launcher?.add({ command: COMMAND, category: 'Other', rank: 0 });
    palette?.addItem({ command: COMMAND, category: TITLE });
    palette?.addItem({ command: SIDE_PANEL_COMMAND, category: TITLE });
  }
};

export default [plugin, downloadPlugin, filesPlugin, queryTabsPlugin];
