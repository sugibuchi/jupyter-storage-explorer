// "About", in the settings menu: the explorer's name, version and icon, and
// the plugins installed (the kernel's "about"), those not used greyed out,
// each with its description, authors and license in the tooltip of an info
// icon. Names link to their packages' home pages.

function createAbout(x) {
  // A package's name, a link to its home page if it has one: http(s) only
  // (the kernel keeps only those too), opened in a new browser tab.
  function nameEl(name, homepage, className) {
    if (!/^https?:\/\//i.test(homepage || "")) return h("span", { className, textContent: name });
    return h("a", {
      className: `${className} jse-about-link`,
      textContent: name,
      href: homepage,
      target: "_blank",
      rel: "noopener noreferrer",
      title: homepage,
    });
  }

  // "By A, B" and "License: MIT", for those given.
  function credits(item) {
    return [item.authors?.length ? `By ${item.authors.join(", ")}` : "", item.license ? `License: ${item.license}` : ""].filter(Boolean);
  }

  function pluginRow(plugin) {
    const tooltip = [plugin.description || "No description", ...credits(plugin), plugin.note].filter(Boolean).join("\n");
    return h(
      "li",
      { className: "jse-about-plugin" + (plugin.enabled ? "" : " jse-disabled") },
      nameEl(plugin.name, plugin.homepage, "jse-about-plugin-name"),
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
        nameEl(reply.name, reply.homepage, "jse-about-name"),
        h("div", { className: "jse-about-version", textContent: reply.version ? `Version ${reply.version}` : "" }),
        ...credits(reply).map((line) => h("div", { className: "jse-about-version", textContent: line })),
      ),
    );
    const plugins = reply.plugins.length
      ? h("ul", { className: "jse-about-plugins" }, ...reply.plugins.map(pluginRow))
      : h("div", { className: "jse-note", textContent: "No plugins installed" });
    x.modal.show("About", [head, h("div", { className: "jse-section-title", textContent: "Plugins" }), plugins]);
  }

  return { show };
}
