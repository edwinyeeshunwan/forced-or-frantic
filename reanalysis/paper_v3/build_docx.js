// Build the v3 working paper (.docx) from its canonical Markdown source.
// Usage: node build_docx.js   (run from paper_v3/; requires the `docx` npm package)
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, BorderStyle, ShadingType, ImageRun, Footer, PageNumber, LevelFormat, VerticalAlign,
} = require("docx");

const SRC = path.join(__dirname, "Open_Interest_and_Price_Recovery_v3.md");
const OUT = path.join(__dirname, "Open_Interest_and_Price_Recovery_v3.docx");
const FONT = "Times New Roman";
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134;           // A4, 2 cm margins
const CONTENT_W = PAGE_W - 2 * MARGIN;

function runs(text, base = {}) {
  // **bold** and `code` inline markup
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const tok = m[0];
    if (tok.startsWith("**")) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, ...base }));
    else out.push(new TextRun({ text: tok.slice(1, -1), font: "Courier New", size: (base.size || 22) - 3 }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}

function splitRow(line) {
  const cells = [];
  let cur = "", s = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "\\" && s[i + 1] === "|") { cur += "|"; i++; continue; }
    if (s[i] === "|") { cells.push(cur.trim()); cur = ""; continue; }
    cur += s[i];
  }
  cells.push(cur.trim());
  return cells;
}

function colWidths(rows) {
  const n = rows[0].length;
  const len = Array.from({ length: n }, (_, j) => Math.max(...rows.map(r => (r[j] || "").length)));
  const word = Array.from({ length: n }, (_, j) => Math.max(...rows.map(r => Math.max(...(r[j] || "").split(" ").map(x => x.length)))));
  const w = len.map((l, j) => Math.max(j === 0 ? 18 : 8, word[j] + 2, Math.min(l, j === 0 ? 60 : 30)));
  const tot = w.reduce((a, b) => a + b, 0);
  const dx = w.map(x => Math.floor((x / tot) * CONTENT_W));
  dx[0] += CONTENT_W - dx.reduce((a, b) => a + b, 0);
  return dx;
}

function table(rows, aligns) {
  const widths = colWidths(rows);
  const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
  const borders = { top: border, bottom: border, left: border, right: border };
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((r, i) => new TableRow({
      tableHeader: i === 0, cantSplit: true,
      children: r.map((c, j) => new TableCell({
        width: { size: widths[j], type: WidthType.DXA }, borders,
        verticalAlign: VerticalAlign.CENTER,
        shading: i === 0 ? { fill: "E8E7E3", type: ShadingType.CLEAR, color: "auto" } : undefined,
        margins: { top: 60, bottom: 60, left: 90, right: 90 },
        children: [new Paragraph({
          spacing: { after: 0, line: 250 },
          alignment: j === 0 || aligns[j] !== "right" ? AlignmentType.LEFT : AlignmentType.RIGHT,
          children: runs(c, { size: 18, bold: i === 0, font: FONT }),
        })],
      })),
    })),
  });
}

const lines = fs.readFileSync(SRC, "utf8").split("\n");
const children = [];
let i = 0, preamble = 0, section = "";
while (i < lines.length) {
  const line = lines[i].trim();
  if (!line) { i++; continue; }
  if (line.startsWith("|")) {
    const rows = []; let aligns = [];
    while (i < lines.length && lines[i].trim().startsWith("|")) {
      const cells = splitRow(lines[i]);
      if (cells.every(c => /^:?-+:?$/.test(c))) aligns = cells.map(c => (c.endsWith(":") ? "right" : "left"));
      else rows.push(cells);
      i++;
    }
    children.push(table(rows, aligns));
    children.push(new Paragraph({ spacing: { after: 80 }, children: [] }));
    continue;
  }
  const img = line.match(/^!\[(.*)\]\((.*)\)$/);
  if (img) {
    const file = path.join(__dirname, img[2]);
    const buf = fs.readFileSync(file);
    const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);          // PNG header
    const maxW = 620, scale = maxW / w;
    children.push(new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 },
      children: [new ImageRun({ type: "png", data: buf, transformation: { width: Math.round(w * scale), height: Math.round(h * scale) },
        altText: { title: img[1], description: img[1], name: path.basename(file) } })] }));
    children.push(new Paragraph({ spacing: { after: 200 }, children: runs(img[1], { size: 20, bold: true, font: FONT }) }));
    i++; continue;
  }
  if (line.startsWith("# ")) {
    children.push(new Paragraph({ heading: HeadingLevel.TITLE, spacing: { after: 200 }, children: runs(line.slice(2), { font: FONT, size: 36, bold: true }) }));
    preamble = 1;
  } else if (line.startsWith("## ")) {
    preamble = 0;
    section = line.slice(3);
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: line === "## References", children: runs(line.slice(3)) }));
  } else if (line.startsWith("### ")) {
    children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: runs(line.slice(4)) }));
  } else if (/^Table \d+ [A-Z]/.test(line) && !line.endsWith(".") && line.length < 90) {
    children.push(new Paragraph({ keepNext: true, spacing: { before: 160, after: 80 }, children: runs(line, { bold: true, size: 20, font: FONT }) }));
  } else if (line.startsWith("- ")) {
    children.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 60 }, children: runs(line.slice(2), { font: FONT }) }));
  } else if (preamble) {
    children.push(new Paragraph({ spacing: { after: 60 }, children: runs(line, { font: FONT, size: preamble === 1 ? 24 : 21, italics: preamble > 2 }) }));
    preamble++;
  } else if (section === "References") {
    children.push(new Paragraph({ indent: { left: 360, hanging: 360 }, spacing: { after: 100 }, children: runs(line, { font: FONT, size: 21 }) }));
  } else {
    const ragged = section.startsWith("Appendix") || line.includes("`");
    children.push(new Paragraph({ spacing: { after: 140, line: 276 }, alignment: ragged ? AlignmentType.LEFT : AlignmentType.JUSTIFIED,
      children: runs(line, { font: FONT }) }));
  }
  i++;
}

const doc = new Document({
  creator: "Edwin Wan",
  title: "Open Interest Contraction and Price Recovery Around Liquidation Events (version 3)",
  description: "Corrected exploratory reanalysis of BTC and ETH perpetual futures on Hyperliquid",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", run: { font: FONT, size: 36, bold: true, color: "000000" }, paragraph: { spacing: { after: 200 } } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 27, bold: true, color: "000000" }, paragraph: { spacing: { before: 300, after: 120 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 23, bold: true, italics: true, color: "000000" }, paragraph: { spacing: { before: 200, after: 100 }, keepNext: true, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], size: 18, font: FONT })] })] }) },
    children,
  }],
});
Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log("wrote", OUT); });
