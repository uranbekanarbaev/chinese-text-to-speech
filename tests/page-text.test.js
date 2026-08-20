const {
  hasChinese,
  nodesToParagraphs,
  splitIntoSentences,
  extractSegments,
  MAX_SEGMENT_LEN,
} = require('../extension/lib/page-text');

describe('hasChinese', () => {
  test('true when the string contains any CJK character', () => {
    expect(hasChinese('你好')).toBe(true);
    expect(hasChinese('mixed 中文 text')).toBe(true);
  });

  test('false for non-Chinese or empty strings', () => {
    expect(hasChinese('hello')).toBe(false);
    expect(hasChinese('')).toBe(false);
  });
});

describe('nodesToParagraphs', () => {
  test('drops empty, whitespace-only, and non-Chinese blocks', () => {
    const nodes = [
      { textContent: '你好，世界。' },
      { textContent: '   ' },
      { textContent: 'English only, no Chinese here.' },
      { textContent: '' },
    ];
    expect(nodesToParagraphs(nodes)).toEqual(['你好，世界。']);
  });

  test('collapses internal whitespace/newlines and trims', () => {
    const nodes = [{ textContent: '  你好 \n 世界  ' }];
    expect(nodesToParagraphs(nodes)).toEqual(['你好 世界']);
  });

  test('drops exact duplicates from nested-element matches', () => {
    const nodes = [{ textContent: '你好，世界。' }, { textContent: '你好，世界。' }];
    expect(nodesToParagraphs(nodes)).toEqual(['你好，世界。']);
  });
});

describe('splitIntoSentences', () => {
  test('splits on Chinese sentence-final punctuation, keeping the punctuation', () => {
    expect(splitIntoSentences('你好。今天天气不错！你觉得呢？')).toEqual([
      '你好。',
      '今天天气不错！',
      '你觉得呢？',
    ]);
  });

  test('a paragraph with no terminal punctuation stays one sentence', () => {
    expect(splitIntoSentences('没有标点的一段话')).toEqual(['没有标点的一段话']);
  });

  test('keeps short sentences separate rather than merging them - each stays its own click/highlight target', () => {
    const short = '你好。'.repeat(3);
    const result = splitIntoSentences(short);
    expect(result).toEqual(['你好。', '你好。', '你好。']);
  });

  test('hard-splits a single sentence longer than MAX_SEGMENT_LEN', () => {
    const oneLongSentence = '很'.repeat(MAX_SEGMENT_LEN * 2 + 5) + '。';
    const result = splitIntoSentences(oneLongSentence);
    expect(result.length).toBeGreaterThan(1);
    for (const chunk of result) {
      expect(chunk.length).toBeLessThanOrEqual(MAX_SEGMENT_LEN);
    }
    expect(result.join('')).toBe(oneLongSentence);
  });

  test('empty paragraph yields no sentences', () => {
    expect(splitIntoSentences('')).toEqual([]);
  });
});

describe('extractSegments', () => {
  test('produces flat segments tagged with their source paragraph index', () => {
    const nodes = [
      { textContent: '第一段第一句。第一段第二句。' },
      { textContent: 'not chinese, skipped' },
      { textContent: '第二段唯一一句。' },
    ];
    const segments = extractSegments(nodes);
    // paragraphIndex is over the *filtered* Chinese paragraphs, not the raw node list -
    // the skipped non-Chinese node doesn't consume an index.
    expect(segments).toEqual([
      { text: '第一段第一句。', paragraphIndex: 0 },
      { text: '第一段第二句。', paragraphIndex: 0 },
      { text: '第二段唯一一句。', paragraphIndex: 1 },
    ]);
  });

  test('empty node list yields no segments', () => {
    expect(extractSegments([])).toEqual([]);
  });
});
