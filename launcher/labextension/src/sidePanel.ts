// Storage Explorer in JupyterLab's left side bar: a panel holding a console
// whose kernel runs `launch(sidebar=True)` (see index.ts), the narrow explorer
// without tree or preview panel; items it views open in new tabs.
//
// Its console is made as an explorer tab is (`console:create`, with a session
// name of its own), which gives it ipywidgets' widget manager, and then moved
// from the main area into the panel. Its kernel starts the first time the
// panel is shown, not with the page. JupyterLab restores consoles in the main
// area after a page reload: the side panel's is taken back (`adopt`).

import type { JupyterFrontEnd } from '@jupyterlab/application';
import type { ConsolePanel } from '@jupyterlab/console';
import type { LabIcon } from '@jupyterlab/ui-components';
import { BoxPanel, Widget } from '@lumino/widgets';
import type { Message } from '@lumino/messaging';

// Marks the panel, for its styles (style/index.css).
const PANEL_CLASS = 'jse-side-panel';

// Makes the side panel's console: `options` for console:create (e.g. `path`
// and `kernelPreference` of the console it replaces). Resolves once the
// console is in the shell.
export type CreateConsole = (options?: { [key: string]: any }) => Promise<ConsolePanel>;

export class ExplorerSidePanel extends BoxPanel {
  // The console showing the explorer, once there is one.
  private current: ConsolePanel | null = null;
  // While a console is being made for the panel (open).
  private opening: Promise<void> | null = null;
  // Restored consoles about to be moved here (adopt): the panel shown meanwhile
  // waits for them rather than make another.
  private adopting = new Set<ConsolePanel>();

  constructor(
    private app: JupyterFrontEnd,
    private createConsole: CreateConsole,
    icon: LabIcon,
    caption: string
  ) {
    super();
    this.id = 'jupyter-storage-explorer-side-panel';
    this.addClass(PANEL_CLASS);
    this.title.icon = icon;
    this.title.caption = caption;
  }

  // The console holding the explorer, for queryTabs.ts: its widgets render
  // with that console's renderers only.
  get explorerConsole(): ConsolePanel | null {
    return this.current;
  }

  // Whether a console is being made for the panel: index.ts leaves it to
  // `open` to take it in.
  get isOpening(): boolean {
    return this.opening !== null;
  }

  // Shown (its side bar icon, the command): the explorer starts there once
  // JupyterLab has restored its consoles, of which the panel's may be one.
  protected onAfterShow(msg: Message): void {
    super.onAfterShow(msg);
    void this.app.restored.then(() => this.openIfEmpty());
  }

  private openIfEmpty(): void {
    if (!this.current && !this.opening && !this.adopting.size && this.isVisible) {
      void this.open();
    }
  }

  // A new console in the panel, in place of the one it has, if any (which
  // the caller disposes of).
  async open(options: { [key: string]: any } = {}): Promise<void> {
    const opening = (async () => {
      const panel = await this.createConsole({ activate: false, ...options });
      this.adoptNow(panel);
    })();
    this.opening = opening;
    try {
      await opening;
    } finally {
      if (this.opening === opening) {
        this.opening = null;
      }
    }
  }

  // A console of the panel's session name restored by JupyterLab: moved here
  // once JupyterLab has put it in the main area. A second one (e.g. restored
  // with another workspace's) is closed, its kernel with it.
  adopt(panel: ConsolePanel): void {
    this.adopting.add(panel);
    void this.app.restored.then(async () => {
      await placed(panel);
      this.adopting.delete(panel);
      if (this.current && this.current !== panel && !this.current.isDisposed) {
        panel.dispose();
      } else if (!panel.isDisposed) {
        this.adoptNow(panel);
      }
      this.openIfEmpty(); // e.g. the console was closed meanwhile
    });
  }

  private adoptNow(panel: ConsolePanel): void {
    this.current = panel;
    // No toolbar (kernel status, debugger): the side bar is narrow, and the
    // explorer has its own. Hidden through Lumino, which lays it out again.
    panel.toolbar.hide();
    this.addWidget(panel);
    BoxPanel.setStretch(panel, 1);
    // Added to the main area without being activated, it was a hidden tab there.
    panel.show();
    panel.disposed.connect(() => {
      if (this.current === panel) {
        this.current = null;
      }
    });
  }
}

// Resolves once `panel` has a parent (the shell has added it), or after a
// while: JupyterLab adds a console to the shell after its tracker announces
// it, so moving it before would leave it in the main area.
async function placed(panel: Widget): Promise<void> {
  for (let i = 0; i < 100 && !panel.parent && !panel.isDisposed; i++) {
    await new Promise(resolve => setTimeout(resolve, 20));
  }
}
