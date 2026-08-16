importScripts('amplitude.js', 'lib/tts-url.js');
const { containsChinese, buildListenUrl, buildWelcomeUrl, buildUninstallUrl } = TTS_URL_LIB;

const TTS_URL       = 'https://uranbekanarbaev.dev';
const WELCOME_URL   = 'https://uranbekanarbaev.dev/welcome-page/chinese-text-to-speech';
const UNINSTALL_URL = 'https://uranbekanarbaev.dev/uninstall-page/chinese-text-to-speech';

// Toolbar click → open TTS page
chrome.action.onClicked.addListener(async () => {
  await ampTrack('Расш_иконка_нажата');
  chrome.tabs.create({ url: TTS_URL });
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

// Context menu
chrome.contextMenus.onClicked.addListener((data) => {
  if (data.menuItemId !== 'ctts_listen') return;
  const text = (data.selectionText || '').trim();
  if (!text) return;

  ampTrack('Расш_контекстное_меню_нажато', {
    длина_текста:  text.length,
    есть_китайский: containsChinese(text),
  });

  chrome.tabs.create({ url: buildListenUrl(TTS_URL, text) });
});
