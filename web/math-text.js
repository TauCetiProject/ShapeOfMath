/* Typeset the script notation used in collection prose, without changing data.
 * This intentionally handles superscripts/subscripts, not arbitrary LaTeX.
 * All source characters become text nodes; none are interpreted as HTML.
 */
window.MathText = (() => {
  const selectors = 'h1,h2,.concept-summary p,.focus-node p,.concept-row p,.concept-row strong,' +
    '.source-intro,.cone-description,.cone-list-title,.cone-list-node p,.cone-list-node li a,' +
    '.record-item strong,.node-main strong,.source-card strong,.context-link,.report-table td:nth-child(2)';

  function fragment(text, depth = 0) {
    const out = document.createDocumentFragment();
    let plain = '';
    const flush = () => { if (plain) out.append(document.createTextNode(plain)); plain = ''; };
    for (let i = 0; i < text.length; i++) {
      const marker = text[i];
      if (depth < 16 && (marker === '^' || marker === '_') && i > 0 && !/\s/.test(text[i - 1])) {
        let end = i + 1, content;
        if (text[end] === '{' || text[end] === '(') {
          const close = { '{': '}', '(': ')', '[': ']' }, stack = [close[text[end]]];
          for (end++; end < text.length && stack.length; end++) {
            const token = text[end];
            if (close[token]) stack.push(close[token]);
            else if ('})]'.includes(token)) {
              if (stack.pop() !== token) { end = text.length + 1; break; }
            }
          }
          if (!stack.length && end <= text.length) content = text.slice(i + 2, end - 1);
        } else if (end < text.length) {
          const token = text.slice(end).match(/^[+−-]?(?:\d+(?:\.\d+)?|[\p{L}\p{N}∞∗*±])/u)?.[0];
          if (token) { content = token; end += token.length; }
        }
        if (content) {
          flush();
          const script = document.createElement(marker === '^' ? 'sup' : 'sub');
          script.className = 'math-script';
          script.append(fragment(content, depth + 1));
          out.append(script);i = end - 1;continue;
        }
      }
      plain += marker;
    }
    flush();return out;
  }

  function render(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        return /[_^]/.test(node.data) && parent?.closest(selectors) &&
          !parent.closest('svg,sup,sub,code,pre,script,style,textarea,input,.formalizations')
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      }
    });
    const nodes = [];while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const result = fragment(node.data);
      if (result.querySelector('sup,sub')) node.replaceWith(result);
    }
    // Keep downloaded diagrams native SVG, with the same typography as prose.
    function svgContent(node) {
      if (node.nodeType === Node.TEXT_NODE) return node.cloneNode();
      const span = document.createElementNS('http://www.w3.org/2000/svg', 'tspan');
      span.setAttribute('baseline-shift', node.tagName === 'SUP' ? 'super' : 'sub');
      span.setAttribute('font-size', '75%');
      for (const child of node.childNodes) span.append(svgContent(child));
      return span;
    }
    for (const text of root.querySelectorAll('.cone-node text')) {
      if (text.children.length || !/[_^]/.test(text.textContent)) continue;
      const result = fragment(text.textContent);
      if (result.querySelector('sup,sub')) text.replaceChildren(...[...result.childNodes].map(svgContent));
    }
  }

  document.addEventListener('DOMContentLoaded', () => render(document.body));
  return { render };
})();
