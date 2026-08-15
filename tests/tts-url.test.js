const {
  containsChinese,
  buildListenUrl,
  buildWelcomeUrl,
  buildUninstallUrl,
} = require('../extension/lib/tts-url');

describe('containsChinese', () => {
  test('detects Chinese characters', () => {
    expect(containsChinese('你好')).toBe(true);
    expect(containsChinese('read this: 中文')).toBe(true);
  });

  test('false for non-Chinese text', () => {
    expect(containsChinese('hello world')).toBe(false);
    expect(containsChinese('')).toBe(false);
  });
});

describe('buildListenUrl', () => {
  const BASE = 'https://uranbekanarbaev.dev';

  test('no text falls back to the bare base URL', () => {
    expect(buildListenUrl(BASE, '')).toBe(BASE);
  });

  test('appends the text as an encoded query param', () => {
    expect(buildListenUrl(BASE, '你好')).toBe(`${BASE}?text=%E4%BD%A0%E5%A5%BD`);
  });

  test('encodes special characters that would otherwise break the URL', () => {
    const text = '50% off & free shipping?';
    const url = buildListenUrl(BASE, text);
    expect(url).toBe(`${BASE}?text=${encodeURIComponent(text)}`);
    // Round-trips cleanly back to the original selected text.
    expect(decodeURIComponent(url.split('?text=')[1])).toBe(text);
  });
});

describe('buildWelcomeUrl', () => {
  test('appends amp_did for the install funnel', () => {
    const url = buildWelcomeUrl('https://uranbekanarbaev.dev/welcome-page/chinese-text-to-speech', 'abc 123');
    expect(url).toBe('https://uranbekanarbaev.dev/welcome-page/chinese-text-to-speech?amp_did=abc%20123');
  });
});

describe('buildUninstallUrl', () => {
  test('appends amp_device_id so the uninstall funnel ties back to the same user', () => {
    const url = buildUninstallUrl('https://uranbekanarbaev.dev/uninstall-page/chinese-text-to-speech', 'device-42');
    expect(url).toBe('https://uranbekanarbaev.dev/uninstall-page/chinese-text-to-speech?amp_device_id=device-42');
  });
});
