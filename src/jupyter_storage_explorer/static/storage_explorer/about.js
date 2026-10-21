// "About", in the settings menu: the explorer's name, version and icon, and
// the plugins installed (the kernel's "about"), those not used greyed out,
// each with its description in the tooltip of an info icon.

function createAbout(x) {
  function pluginRow(plugin) {
    const tooltip = [plugin.description || "No description", plugin.note].filter(Boolean).join("\n");
    return h(
      "li",
      { className: "jse-about-plugin" + (plugin.enabled ? "" : " jse-disabled") },
      h("span", { className: "jse-about-plugin-name", textContent: plugin.name }),
      h("span", { className: "jse-about-version", textContent: plugin.version }),
      h("span", { className: "jse-about-info", title: tooltip, ariaLabel: tooltip }, icon("info")),
    );
  }

  async function show() {
    const reply = await x.request({ type: "about" });
    if (reply.error) {
      x.flash(`About: ${reply.error}`);
      return;
    }
    const head = h(
      "div",
      { className: "jse-about-head" },
      // An <img>, as the files' icons of formats: its scripts never run.
      h("img", { className: "jse-about-icon", src: reply.icon, alt: "" }),
      h(
        "div",
        {},
        h("div", { className: "jse-about-name", textContent: reply.name }),
        h("div", { className: "jse-about-version", textContent: reply.version ? `Version ${reply.version}` : "" }),
      ),
    );
    const plugins = reply.plugins.length
      ? h("ul", { className: "jse-about-plugins" }, ...reply.plugins.map(pluginRow))
      : h("div", { className: "jse-note", textContent: "No plugins installed" });
    x.modal.show("About", [head, h("div", { className: "jse-section-title", textContent: "Plugins" }), plugins]);
  }

  return { show };
}
