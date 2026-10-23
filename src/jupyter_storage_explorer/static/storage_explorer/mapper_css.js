// How the storages look: their mappers' CSS (FileSystemMapper.css, scoped
// by the kernel to the explorer showing one of their storages: its
// data-fs-mapper, the mapper of the storage shown). Each mapper's is on the
// page once, in a <style> of the page's head, whichever explorers show its
// storages; a later explorer's replaces it, e.g. from a newer kernel.

function createMapperCss(x) {
  const { model, el } = x;

  function render() {
    el.dataset.fsMapper = model.get("_fs_mapper");
    const styles = model.get("_mapper_css");
    const onPage = new Map([...document.head.querySelectorAll("style[data-jse-mapper]")].map((s) => [s.dataset.jseMapper, s]));
    for (const [key, css] of Object.entries(styles)) {
      let style = onPage.get(key);
      if (!style) {
        style = h("style");
        style.dataset.jseMapper = key;
        document.head.append(style);
      }
      if (style.textContent !== css) style.textContent = css;
    }
  }

  return { render };
}
