/**
 * Pure URL-building + Chinese-detection logic, extracted out of
 * background.js so it's unit-testable without mocking the `chrome.*` MV3
 * service-worker APIs. This extension is deliberately a thin launcher,
 * see the top-level README for why, so this is genuinely most of its
 * business logic.
 */
(function (root) {
  const CHINESE_RE = /[一-鿿㐀-䶿]/;

  function containsChinese(text) {
    return CHINESE_RE.test(text);
  }

  /** Opens the shared TTS web app, optionally pre-filled with selected text. */
  function buildListenUrl(baseUrl, text) {
    if (!text) return baseUrl;
    return `${baseUrl}?text=${encodeURIComponent(text)}`;
  }

  /** Welcome page carries the Amplitude device_id so the install funnel
   * (extension install -> web app first open) tracks as one user. */
  function buildWelcomeUrl(welcomeUrl, deviceId) {
    return `${welcomeUrl}?amp_did=${encodeURIComponent(deviceId)}`;
  }

  function buildUninstallUrl(uninstallUrl, deviceId) {
    return `${uninstallUrl}?amp_device_id=${encodeURIComponent(deviceId)}`;
  }

  const api = { CHINESE_RE, containsChinese, buildListenUrl, buildWelcomeUrl, buildUninstallUrl };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.TTS_URL_LIB = api;
  }
})(typeof self !== 'undefined' ? self : globalThis);
