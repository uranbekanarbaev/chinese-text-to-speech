/**
 * Pure text-extraction/segmentation logic for "read the whole page" mode.
 * Deliberately DOM-decoupled (works against plain {tagName, textContent}
 * objects, not just live nodes) so it's testable without jsdom.
 */
(function (root) {
  const CJK_RE = /[一-鿿㐀-䶿]/;
  const SENTENCE_END_RE = /([。！？；\n])/;
  const MAX_SEGMENT_LEN = 400; // keeps each TTS request comfortably under the backend's per-request cap

  /** True if the string contains at least one CJK character. */
  function hasChinese(text) {
    return CJK_RE.test(text);
  }

  /**
   * Turns a flat list of block-level nodes into cleaned paragraph strings:
   * trims whitespace, drops empty/non-Chinese blocks, and drops exact
   * duplicates that show up when a broad selector matches nested elements
   * (e.g. a <li> and the <p> inside it).
   * @param {Array<{textContent: string}>} nodes
   */
  function nodesToParagraphs(nodes) {
    const seen = new Set();
    const out = [];
    for (const node of nodes) {
      const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text || !hasChinese(text) || seen.has(text)) continue;
      seen.add(text);
      out.push(text);
    }
    return out;
  }

  /**
   * Splits one paragraph into sentence-level chunks on Chinese sentence
   * punctuation. One sentence = one segment (= one click target = one
   * highlight unit) - segments are never merged back together, since that
   * would let a click land on more than the sentence the user actually
   * clicked. A single sentence longer than MAX_SEGMENT_LEN (no punctuation
   * for a long stretch) is hard-split so it still fits one TTS request.
   * @param {string} paragraph
   * @returns {string[]}
   */
  function splitIntoSentences(paragraph) {
    const parts = paragraph.split(SENTENCE_END_RE);
    const sentences = [];
    for (let i = 0; i < parts.length; i += 2) {
      const body = parts[i] || '';
      const punct = parts[i + 1] || '';
      const sentence = (body + punct).trim();
      if (!sentence) continue;
      if (sentence.length <= MAX_SEGMENT_LEN) {
        sentences.push(sentence);
      } else {
        for (let j = 0; j < sentence.length; j += MAX_SEGMENT_LEN) {
          sentences.push(sentence.slice(j, j + MAX_SEGMENT_LEN));
        }
      }
    }
    return sentences;
  }

  /**
   * Full pipeline: block-level nodes -> flat list of readable segments,
   * each still tagged with the source paragraph index so the caller can
   * scroll/highlight the right element on the page.
   * @param {Array<{textContent: string}>} nodes
   * @returns {Array<{text: string, paragraphIndex: number}>}
   */
  function extractSegments(nodes) {
    const paragraphs = nodesToParagraphs(nodes);
    const segments = [];
    paragraphs.forEach((paragraph, paragraphIndex) => {
      for (const sentence of splitIntoSentences(paragraph)) {
        segments.push({ text: sentence, paragraphIndex });
      }
    });
    return segments;
  }

  const api = { hasChinese, nodesToParagraphs, splitIntoSentences, extractSegments, MAX_SEGMENT_LEN };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.CTTS_PAGE_TEXT = api;
  }
})(typeof self !== 'undefined' ? self : globalThis);
