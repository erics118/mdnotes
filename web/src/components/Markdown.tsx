import { useEffect, useRef } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import katex from "katex";

// render markdown + KaTeX for the transcribed-text fallback view
export function Markdown({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    // transcribed note text is untrusted; sanitize before it reaches the DOM
    const html = marked.parse(text, { async: false }) as string;
    ref.current.innerHTML = DOMPurify.sanitize(html);
    renderMath(ref.current);
  }, [text]);
  return <div className="md" ref={ref} />;
}

function renderMath(el: HTMLElement) {
  const re = /\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  let n: Node | null;
  while ((n = walker.nextNode())) texts.push(n as Text);
  for (const t of texts) {
    const s = t.nodeValue || "";
    if (!s.includes("$")) continue;
    const frag = document.createDocumentFragment();
    let last = 0;
    let m: RegExpExecArray | null;
    re.lastIndex = 0;
    while ((m = re.exec(s))) {
      if (m.index > last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
      const span = document.createElement("span");
      try {
        katex.render(m[1] ?? m[2] ?? "", span, { throwOnError: false, displayMode: !!m[1] });
      } catch { span.textContent = m[0]; }
      frag.appendChild(span);
      last = m.index + m[0].length;
    }
    if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
    t.replaceWith(frag);
  }
}
