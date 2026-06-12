const KEYWORDS = new Set([
  "public", "private", "protected", "static", "final", "return", "if", "else", "for",
  "while", "new", "class", "interface", "void", "extends", "implements", "import",
  "package", "throws", "throw", "try", "catch", "this", "const", "let", "var",
  "function", "def", "async", "await", "export", "func", "type", "struct",
]);

type Tok = [cls: string, text: string];

export function tokenize(line: string): Tok[] {
  const out: Tok[] = [];
  const comment = line.match(/(\/\/|#).*$/);
  let code = line;
  let trailing: Tok | null = null;
  if (comment && comment.index !== undefined) {
    code = line.slice(0, comment.index);
    trailing = ["tok-com", line.slice(comment.index)];
  }
  const re = /("[^"]*"|'[^']*')|\b(\d[\d_.]*)\b|\b([A-Za-z_]\w*)\b|([^\w"']+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code)) !== null) {
    if (m[1] !== undefined) out.push(["tok-str", m[1]]);
    else if (m[2] !== undefined) out.push(["tok-num", m[2]]);
    else if (m[3] !== undefined) {
      const word = m[3];
      const after = code.slice(re.lastIndex).trimStart();
      if (KEYWORDS.has(word)) out.push(["tok-key", word]);
      else if (/^[A-Z]/.test(word)) out.push(["tok-type", word]);
      else if (after.startsWith("(")) out.push(["tok-fn", word]);
      else out.push(["", word]);
    } else if (m[4] !== undefined) out.push(["", m[4]]);
  }
  if (trailing) out.push(trailing);
  return out;
}

export function CodeViewer({ title, meta, lines, startLine, hlLines }: {
  title: string;
  meta?: string;
  lines: string[];
  startLine: number;
  hlLines?: Set<number>;
}) {
  return (
    <div className="code-viewer">
      <div className="code-head">
        <span className="dots"><i /><i /><i /></span>
        <span>{title}</span>
        {meta && <span style={{ marginLeft: "auto", color: "var(--ink-4)" }}>{meta}</span>}
      </div>
      <div className="code-body">
        {lines.map((text, i) => {
          const n = startLine + i;
          return (
            <div key={n} className={"code-line" + (hlLines?.has(n) ? " hl" : "")}>
              <span className="ln">{n}</span>
              <span>
                {tokenize(text).map((tk, j) => (
                  <span key={j} className={tk[0]}>{tk[1]}</span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
