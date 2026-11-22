import { Fragment, type ReactNode } from "react";

// A small, safe Markdown renderer for the assistant's text: paragraphs, bullet and numbered
// lists, **bold**, *italic*, `code`, and headings shown as bold lines. It builds React
// elements (never HTML strings), so a model's output cannot inject markup or scripts.
// It also renders incomplete text while it streams.

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const k = `${key}-${i++}`;
    if (token.startsWith("**")) out.push(<strong key={k} className="font-semibold text-ink">{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) out.push(<code key={k} className="rounded bg-tint px-1 py-0.5 font-mono text-[0.9em]">{token.slice(1, -1)}</code>);
    else out.push(<em key={k}>{token.slice(1, -1)}</em>);
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block = { kind: "p" | "ul" | "ol" | "h"; lines: string[] };

function blocks(text: string): Block[] {
  const result: Block[] = [];
  for (const raw of text.replace(/\r/g, "").split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^\s*#{1,4}\s+(.*)$/.exec(line);
    const last = result[result.length - 1];
    if (!line.trim()) {
      result.push({ kind: "p", lines: [] });
    } else if (bullet) {
      if (last?.kind === "ul") last.lines.push(bullet[1]);
      else result.push({ kind: "ul", lines: [bullet[1]] });
    } else if (numbered) {
      if (last?.kind === "ol") last.lines.push(numbered[1]);
      else result.push({ kind: "ol", lines: [numbered[1]] });
    } else if (heading) {
      result.push({ kind: "h", lines: [heading[1]] });
    } else if (last?.kind === "p" && last.lines.length) {
      last.lines.push(line.trim());
    } else {
      result.push({ kind: "p", lines: [line.trim()] });
    }
  }
  return result.filter((b) => b.lines.length);
}

export default function Markdown({ text, className = "", caret = false }: { text: string; className?: string; caret?: boolean }) {
  const parts = blocks(text);
  return (
    <div className={`space-y-3 ${className}`}>
      {parts.map((b, i) => {
        const end = caret && i === parts.length - 1 ? <span className="caret" aria-hidden="true" /> : null;
        if (b.kind === "ul" || b.kind === "ol") {
          const List = b.kind === "ul" ? "ul" : "ol";
          return (
            <List key={i} className={`space-y-1.5 pl-5 ${b.kind === "ul" ? "list-disc" : "list-decimal"} marker:text-ink-3`}>
              {b.lines.map((l, j) => (
                <li key={j}>
                  {inline(l, `${i}-${j}`)}
                  {j === b.lines.length - 1 && end}
                </li>
              ))}
            </List>
          );
        }
        if (b.kind === "h") {
          return (
            <p key={i} className="font-display font-semibold text-ink">
              {inline(b.lines[0], `${i}`)}
              {end}
            </p>
          );
        }
        return (
          <p key={i}>
            {b.lines.map((l, j) => (
              <Fragment key={j}>
                {j > 0 && " "}
                {inline(l, `${i}-${j}`)}
              </Fragment>
            ))}
            {end}
          </p>
        );
      })}
      {parts.length === 0 && caret && <span className="caret" aria-hidden="true" />}
    </div>
  );
}
