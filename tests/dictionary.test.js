const { segmentAndGloss, lookupWord } = require('../extension/lib/dictionary');

const DICT = {
  maxLen: 3,
  words: {
    你好: ['nǐ hǎo', 'hello', 1],
    你: ['nǐ', 'you', 1],
    好: ['hǎo', 'good', 1],
    中国: ['zhōng guó', 'China', 1],
    人: ['rén', 'person', 1],
  },
};

describe('segmentAndGloss', () => {
  test('prefers the longest matching word over shorter substrings', () => {
    const tokens = segmentAndGloss('你好', DICT);
    expect(tokens).toEqual([{ surface: '你好', py: 'nǐ hǎo', en: 'hello', level: 1 }]);
  });

  test('segments consecutive known words greedily', () => {
    const tokens = segmentAndGloss('中国人', DICT);
    expect(tokens.map((t) => t.surface)).toEqual(['中国', '人']);
  });

  test('falls back to single characters with no gloss when nothing matches', () => {
    const tokens = segmentAndGloss('你曦好', DICT);
    expect(tokens).toEqual([
      { surface: '你', py: 'nǐ', en: 'you', level: 1 },
      { surface: '曦', py: null, en: null, level: null },
      { surface: '好', py: 'hǎo', en: 'good', level: 1 },
    ]);
  });

  test('empty string yields no tokens', () => {
    expect(segmentAndGloss('', DICT)).toEqual([]);
  });
});

describe('lookupWord', () => {
  test('returns the gloss for a known word', () => {
    expect(lookupWord('你好', DICT)).toEqual({ surface: '你好', py: 'nǐ hǎo', en: 'hello', level: 1 });
  });

  test('returns null for an unknown word', () => {
    expect(lookupWord('曦', DICT)).toBeNull();
  });
});
