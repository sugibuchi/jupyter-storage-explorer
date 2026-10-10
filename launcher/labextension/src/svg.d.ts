// SVG files imported by the extension are bundled as their source text.
declare module '*.svg' {
  const svgstr: string;
  export default svgstr;
}
