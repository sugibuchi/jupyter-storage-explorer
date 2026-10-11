// Storage Explorer in the JupyterLab launcher: the item opens a new tab with
// the explorer. The tab is a code console whose prompt and input are hidden:
// consoles get a widget manager from ipywidgets, so the explorer (an
// anywidget) renders there. The console runs `launch()` from the Python
// package jupyter_storage_explorer_launcher, which calls the user's
// launcher.py (see there) and displays the widget it returns. The kernel is
// shut down when the tab closes.
//
// JupyterLab restores open consoles when the page is reloaded, reconnected to
// their kernels but without their outputs. Explorer tabs are recognised by
// their session name and set up again, running `launch()` once more.
//
// A second plugin (download.ts) downloads files dragged from any explorer,
// in a tab or a notebook, onto JupyterLab's file browser.

import { JupyterFrontEnd, JupyterFrontEndPlugin } from '@jupyterlab/application';
import { ICommandPalette } from '@jupyterlab/apputils';
import { ConsolePanel, IConsoleTracker } from '@jupyterlab/console';
import { ILauncher } from '@jupyterlab/launcher';
import { LabIcon } from '@jupyterlab/ui-components';

import { downloadPlugin } from './download';
import iconSvg from '../style/storage-explorer.svg';

const COMMAND = 'storage-explorer:open';
const TITLE = 'Storage Explorer';
// Session name of explorer tabs; it survives page reloads, so it identifies them.
const SESSION_NAME = TITLE;
// Marks the console as an explorer tab, for the styles hiding its prompt and input.
const PANEL_CLASS = 'jse-launcher-panel';
// Run in the tab's kernel.
const CODE = 'from jupyter_storage_explorer_launcher import launch as __jse_launch\n__jse_launch()';

export const storageExplorerIcon = new LabIcon({
  name: 'jupyter-storage-explorer-launcher:icon',
  svgstr: iconSvg
});

// `cwd`: the launcher's folder (the one shown in the file browser), where the
// kernel starts, so "." in launcher.py is that folder. Without it (e.g. from
// the command palette), the console uses the file browser's folder itself.
// The new console is then set up by `showExplorer`, like a restored one.
async function openExplorer(app: JupyterFrontEnd, cwd?: string): Promise<ConsolePanel> {
  const specs = app.serviceManager.kernelspecs;
  await specs.ready;
  return app.commands.execute('console:create', {
    ...(cwd !== undefined ? { basePath: cwd } : {}),
    name: SESSION_NAME,
    activate: true,
    kernelPreference: { name: specs.specs?.default, shouldStart: true }
  });
}

// Turns a console with the explorer's session name, new or restored, into an
// explorer tab and runs `launch()` in it. Other consoles are left alone.
async function showExplorer(panel: ConsolePanel): Promise<void> {
  const session = panel.sessionContext;
  if (session.name !== SESSION_NAME) {
    return;
  }
  panel.addClass(PANEL_CLASS);
  panel.title.label = TITLE;
  panel.title.icon = storageExplorerIcon;
  // The kernel only serves this tab (restored consoles lose this preference).
  session.kernelPreference = { ...session.kernelPreference, shutdownOnDispose: true };
  await session.ready;
  if (!panel.isDisposed) {
    await panel.console.inject(CODE);
  }
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-storage-explorer-launcher:plugin',
  description: 'Opens Storage Explorer in a new tab from the launcher.',
  autoStart: true,
  requires: [IConsoleTracker],
  optional: [ILauncher, ICommandPalette],
  activate: (
    app: JupyterFrontEnd,
    consoles: IConsoleTracker,
    launcher: ILauncher | null,
    palette: ICommandPalette | null
  ) => {
    // Connected before JupyterLab restores the layout, so restored tabs are seen too.
    consoles.widgetAdded.connect((_, panel) => void showExplorer(panel));
    app.commands.addCommand(COMMAND, {
      label: TITLE,
      caption: 'Browse storage and query data in a new tab',
      icon: args => (args['isPalette'] ? undefined : storageExplorerIcon),
      execute: args => openExplorer(app, args['cwd'] as string | undefined)
    });
    launcher?.add({ command: COMMAND, category: 'Other', rank: 0 });
    palette?.addItem({ command: COMMAND, category: TITLE });
  }
};

export default [plugin, downloadPlugin];
