/**
 * Amplitude: обёртка для Chrome Extension (MV3 Service Worker).
 * Публичный API-ключ только пишет события, не читает данные.
 */
const _AMP_KEY      = "add6712822e25838a568f00fd75f234f";
const _AMP_ENDPOINT = "https://api2.amplitude.com/2/httpapi";

/** Возвращает постоянный device_id, хранится в chrome.storage.local */
async function _ampDeviceId() {
  const KEY = "_amp_did";
  const s = await chrome.storage.local.get(KEY);
  if (s[KEY]) return s[KEY];
  const id = "ext_" + Date.now() + "_" + Math.random().toString(36).slice(2, 10);
  await chrome.storage.local.set({ [KEY]: id });
  return id;
}

/**
 * Отправить событие в Amplitude.
 * @param {string} eventType  имя события (по-русски, префикс Расш_)
 * @param {object} properties произвольные свойства
 */
async function ampTrack(eventType, properties = {}) {
  try {
    const deviceId = await _ampDeviceId();
    const manifest = chrome.runtime.getManifest();
    fetch(_AMP_ENDPOINT, {
      method: "POST", headers: { "Content-Type": "application/json" }, keepalive: true,
      body: JSON.stringify({
        api_key: _AMP_KEY,
        events: [{
          event_type: eventType, device_id: deviceId,
          platform: "Chrome Extension", app_version: manifest.version,
          os_name: "Chrome", time: Date.now(), event_properties: properties,
        }],
      }),
    }).catch(() => {});
  } catch (e) {
    console.debug("[Analytics]", e);
  }
}
