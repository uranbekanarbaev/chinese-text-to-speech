/**
 * Word-level gloss lookup for the reading panel, backed by the HSK 1-6
 * vocabulary list already used by the sibling HSK Tutor product
 * (extension/data/hsk-dictionary.json, ~5.3k words). Not full CC-CEDICT —
 * deliberately scoped to HSK vocabulary since that's the audience the
 * Amplitude data shows actually uses this product (short word/phrase
 * lookups, not paragraph translation). Unknown words return no gloss
 * rather than a wrong one.
 */
(function (root) {
  /**
   * Greedy longest-match segmenter: walks the text left to right, at each
   * position tries the longest dictionary entry that matches, falling back
   * to a single character (with or without a gloss) if nothing matches.
   * @param {string} text
   * @param {{maxLen: number, words: Object<string, [string,string,number]>}} dict
   * @returns {Array<{surface: string, py: string|null, en: string|null, level: number|null}>}
   */
  function segmentAndGloss(text, dict) {
    const tokens = [];
    const { maxLen, words } = dict;
    let i = 0;
    const n = text.length;
    while (i < n) {
      let matched = null;
      const upper = Math.min(maxLen, n - i);
      for (let len = upper; len >= 1; len--) {
        const candidate = text.slice(i, i + len);
        if (Object.prototype.hasOwnProperty.call(words, candidate)) {
          matched = candidate;
          break;
        }
      }
      if (matched) {
        const [py, en, level] = words[matched];
        tokens.push({ surface: matched, py, en, level });
        i += matched.length;
      } else {
        tokens.push({ surface: text[i], py: null, en: null, level: null });
        i += 1;
      }
    }
    return tokens;
  }

  /** Single-word/phrase lookup, used for click-on-a-word or hover. */
  function lookupWord(word, dict) {
    const entry = dict.words[word];
    if (!entry) return null;
    const [py, en, level] = entry;
    return { surface: word, py, en, level };
  }

  const api = { segmentAndGloss, lookupWord };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.CTTS_DICTIONARY = api;
  }
})(typeof self !== 'undefined' ? self : globalThis);
