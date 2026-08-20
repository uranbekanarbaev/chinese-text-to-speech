importScripts('amplitude.js', 'lib/tts-url.js');
const { containsChinese, buildListenUrl, buildWelcomeUrl, buildUninstallUrl } = TTS_URL_LIB;

const TTS_URL       = 'https://uranbekanarbaev.dev';
const WELCOME_URL   = 'https://uranbekanarbaev.dev/welcome-page/chinese-text-to-speech';
const UNINSTALL_URL = 'https://uranbekanarbaev.dev/uninstall-page/chinese-text-to-speech';

/**
 * Tries to toggle the in-page reading panel via the content script.
 * Falls back to opening the companion site when there's no content script
 * to talk to - chrome:// pages, the Chrome Web Store, PDF viewer tabs, or
 * a tab that was already open before install/update (content scripts only
 * attach to tabs loaded after the extension registers).
 */
async function toggleOrFallback(tabId, message, fallbackUrl) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, message);
    if (!response || !response.ok) throw new Error('no panel in this tab');
  } catch (e) {
    chrome.tabs.create({ url: fallbackUrl });
  }
}

// Toolbar click → toggle the in-page panel (falls back to the site)
chrome.action.onClicked.addListener(async (tab) => {
  await ampTrack('Расш_иконка_нажата');
  await toggleOrFallback(tab.id, { type: 'CTTS_TOGGLE_PANEL' }, TTS_URL);
});

// Install / Update
chrome.runtime.onInstalled.addListener(async (details) => {
  chrome.contextMenus.create({
    id: 'ctts_listen',
    title: '🔊 ' + chrome.i18n.getMessage('contextMenuListen'),
    contexts: ['selection']
  });

  if (details.reason === 'install') {
    const ampDid = await _ampDeviceId();
    await ampTrack('Расш_расширение_установлено', {
      версия:  chrome.runtime.getManifest().version,
      язык:    chrome.i18n.getUILanguage(),
    });
    // Прокидываем device_id в welcome page для сквозной воронки
    chrome.tabs.create({ url: buildWelcomeUrl(WELCOME_URL, ampDid) });
  }

  if (details.reason === 'update') {
    await ampTrack('Расш_расширение_обновлено', {
      предыдущая_версия: details.previousVersion,
      новая_версия:      chrome.runtime.getManifest().version,
    });
  }

  const uninstallDid = await _ampDeviceId();
  chrome.runtime.setUninstallURL(buildUninstallUrl(UNINSTALL_URL, uninstallDid));
});

// Context menu → read the selection in-panel (falls back to the site)
chrome.contextMenus.onClicked.addListener(async (data, tab) => {
  if (data.menuItemId !== 'ctts_listen') return;
  const text = (data.selectionText || '').trim();
  if (!text) return;

  ampTrack('Расш_контекстное_меню_нажато', {
    длина_текста:  text.length,
    есть_китайский: containsChinese(text),
  });

  await toggleOrFallback(
    tab.id,
    { type: 'CTTS_READ_SELECTION', text },
    buildListenUrl(TTS_URL, text)
  );
});
