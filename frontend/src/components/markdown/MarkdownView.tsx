function renderMarkdownBlock(block: string, index: number) {
  const lines = block.split("\n");
  const first = lines[0] ?? "";
  if (first.startsWith("# ")) return <h1 key={index}>{inlineMarkdown(first.slice(2))}</h1>;
  if (first.startsWith("## ")) return <h2 key={index}>{inlineMarkdown(first.slice(3))}</h2>;
  if (first.startsWith("### ")) return <h3 key={index}>{inlineMarkdown(first.slice(4))}</h3>;
  if (lines.every((line) => line.startsWith("- "))) {
    return <ul key={index}>{lines.map((line) => <li key={line}>{inlineMarkdown(line.slice(2))}</li>)}</ul>;
  }
  if (lines.every((line) => line.startsWith(">"))) {
    return <blockquote key={index}>{lines.map((line) => line.replace(/^>\s?/, "")).join(" ")}</blockquote>;
  }
  if (lines.length >= 2 && lines[0].startsWith("|") && lines[1].includes("---")) {
    const header = tableCells(lines[0]);
    const body = lines.slice(2).filter((line) => line.startsWith("|")).map(tableCells);
    return (
      <div className="markdown-table-wrap" key={index}>
        <table>
          <thead><tr>{header.map((cell) => <th key={cell}>{inlineMarkdown(cell)}</th>)}</tr></thead>
          <tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{inlineMarkdown(cell)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    );
  }
  return <p key={index}>{inlineMarkdown(lines.join(" "))}</p>;
}

function tableCells(line: string): string[] {
  return line.split("|").slice(1, -1).map((cell) => cell.trim());
}

function inlineMarkdown(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    return <span key={index}>{part}</span>;
  });
}

export function MarkdownView({ content }: { content: string }) {
  const blocks = content.split(/\n{2,}/).filter(Boolean);
  return (
    <article className="markdown-view">
      {blocks.map((block, index) => renderMarkdownBlock(block, index))}
    </article>
  );
}
