/**
 * In-page reading panel: injected UI (not a native toolbar popup, on
 * purpose - a native popup closes the instant you click anywhere on the
 * page, which is incompatible with "click any part of the page text to
 * jump reading there" and "keep reading while the panel stays open").
 *
 * Talks to the shared HSK Tutor backend directly (no separate API), uses
 * pinyin-pro (vendor/pinyin-pro.js) for pronunciation and the bundled HSK
 * 1-6 word list (lib/dictionary.js + data/hsk-dictionary.json) for
 * word-level English glosses - not a full sentence translation, see
 * extension/README for why.
 */
(function () {
  const API_BASE = 'https://api.hsk-tutor.com';
  const SITE_URL = 'https://uranbekanarbaev.dev';
  const { extractSegments } = self.CTTS_PAGE_TEXT;
  const { segmentAndGloss } = self.CTTS_DICTIONARY;
  const { ReadingQueue } = self.CTTS_READING_QUEUE;

  const VOICES = [
    ['x_xiaoyan', 'Xiaoyan (female, default)'],
    ['x_xiaolin', 'Xiaolin'],
    ['x_xiaomei', 'Xiaomei'],
    ['x_xiaoxue', 'Xiaoxue'],
    ['x_xiaoxi', 'Xiaoxi'],
    ['x_xiaoyuan', 'Xiaoyuan'],
    ['x_xiaofeng', 'Xiaofeng (male)'],
    ['x_yifeng', 'Yifeng (male)'],
    ['x_laoma', 'Laoma (male)'],
  ];
  const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

  let dict = null; // { maxLen, words } loaded lazily from data/hsk-dictionary.json
  let queue = new ReadingQueue([]);
  let currentAudio = null;
  let pageSegments = []; // full extractSegments() output for "read whole page"
  let settings = { voice: 'x_xiaoyan', volume: 1, speed: 1 };
  let readingMode = false; // true once page text has been wrapped in clickable spans

  // ---- settings persistence ----------------------------------------------

  function loadSettings() {
    return new Promise((resolve) => {
      chrome.storage.local.get('ctts_settings', (res) => {
        if (res && res.ctts_settings) settings = Object.assign(settings, res.ctts_settings);
        resolve(settings);
      });
    });
  }

  function saveSettings() {
    chrome.storage.local.set({ ctts_settings: settings });
  }

  // ---- dictionary loading --------------------------------------------------

  async function ensureDictionary() {
    if (dict) return dict;
    const url = chrome.runtime.getURL('data/hsk-dictionary.json');
    const res = await fetch(url);
    dict = await res.json();
    return dict;
  }

  // ---- TTS fetch ------------------------------------------------------------

  /** Always requests at native rate - speed is applied client-side via
   *  audio.playbackRate, which also means every user's request for the same
   *  text hits the same server-side cache entry regardless of their speed setting. */
  async function fetchTTS(text) {
    const res = await fetch(`${API_BASE}/api/voice/tts/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, rate: 1, voice: settings.voice }),
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (_) { /* body wasn't JSON */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.blob();
  }

  // ---- panel DOM --------------------------------------------------------

  let root = null;
  let els = {};

  function buildPanel() {
    root = document.createElement('div');
    root.id = 'ctts-panel-root';
    root.innerHTML = `
      <div class="ctts-panel" role="region" aria-label="Chinese Text to Speech">
        <div class="ctts-header">
          <span class="ctts-title">🗣️ Chinese TTS</span>
          <div class="ctts-header-actions">
            <button type="button" class="ctts-icon-btn" data-action="upload" title="Read a .txt/.pdf/.docx file">📄</button>
            <button type="button" class="ctts-icon-btn" data-action="settings" title="Settings">⚙️</button>
            <button type="button" class="ctts-icon-btn" data-action="close" title="Close">✕</button>
          </div>
        </div>

        <div class="ctts-settings" hidden>
          <label>Voice
            <select data-field="voice"></select>
          </label>
          <label>Volume
            <input type="range" min="0" max="1" step="0.05" data-field="volume">
          </label>
        </div>

        <div class="ctts-reading">
          <div class="ctts-text" data-empty="Click ▶ to read this page, or select text on the page."></div>
          <div class="ctts-pinyin"></div>
          <div class="ctts-gloss"></div>
        </div>

        <div class="ctts-status" hidden></div>

        <div class="ctts-controls">
          <button type="button" class="ctts-icon-btn" data-action="prev" title="Previous sentence (←)">⏮</button>
          <button type="button" class="ctts-icon-btn ctts-play" data-action="play" title="Play/Pause (Space)">▶</button>
          <button type="button" class="ctts-icon-btn" data-action="next" title="Next sentence (→)">⏭</button>
          <select data-field="speed" title="Playback speed"></select>
          <button type="button" class="ctts-icon-btn" data-action="read-page" title="Read the whole page">📖</button>
        </div>

        <div class="ctts-footer">
          <button type="button" class="ctts-link-btn" data-action="scroll-top">↑ Back to page</button>
          <button type="button" class="ctts-link-btn" data-action="open-site">Paste text &amp; download MP3 ↗</button>
        </div>

        <input type="file" data-field="file-input" accept=".txt,.pdf,.docx" hidden>
      </div>
    `;
    document.documentElement.appendChild(root);

    els = {
      panel: root.querySelector('.ctts-panel'),
      settingsPanel: root.querySelector('.ctts-settings'),
      voiceSelect: root.querySelector('[data-field="voice"]'),
      volumeInput: root.querySelector('[data-field="volume"]'),
      speedSelect: root.querySelector('[data-field="speed"]'),
      text: root.querySelector('.ctts-text'),
      pinyin: root.querySelector('.ctts-pinyin'),
      gloss: root.querySelector('.ctts-gloss'),
      status: root.querySelector('.ctts-status'),
      playBtn: root.querySelector('.ctts-play'),
      fileInput: root.querySelector('[data-field="file-input"]'),
    };

    VOICES.forEach(([value, label]) => {
      const opt = document.createElement('option');
      opt.value = value;
      opt.textContent = label;
      els.voiceSelect.appendChild(opt);
    });
    SPEEDS.forEach((s) => {
      const opt = document.createElement('option');
      opt.value = String(s);
      opt.textContent = `${s}x`;
      els.speedSelect.appendChild(opt);
    });
    els.voiceSelect.value = settings.voice;
    els.volumeInput.value = String(settings.volume);
    els.speedSelect.value = String(settings.speed);

    root.addEventListener('click', onPanelClick);
    els.voiceSelect.addEventListener('change', () => {
      settings.voice = els.voiceSelect.value;
      saveSettings();
    });
    els.volumeInput.addEventListener('input', () => {
      settings.volume = parseFloat(els.volumeInput.value);
      if (currentAudio) currentAudio.volume = settings.volume;
      saveSettings();
    });
    els.speedSelect.addEventListener('change', () => {
      settings.speed = parseFloat(els.speedSelect.value);
      if (currentAudio) currentAudio.playbackRate = settings.speed;
      saveSettings();
    });
    els.fileInput.addEventListener('change', onFileChosen);
  }

  function showStatus(message, isError) {
    els.status.hidden = !message;
    els.status.textContent = message || '';
    els.status.classList.toggle('ctts-status-error', !!isError);
  }

  function onPanelClick(e) {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'close') return closePanel();
    if (action === 'settings') return void (els.settingsPanel.hidden = !els.settingsPanel.hidden);
    if (action === 'upload') return els.fileInput.click();
    if (action === 'play') return togglePlay();
    if (action === 'prev') return goPrev();
    if (action === 'next') return goNext();
    if (action === 'read-page') return readWholePage();
    if (action === 'scroll-top') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
      exitReadingMode();
      return;
    }
    if (action === 'open-site') {
      window.open(SITE_URL, '_blank', 'noopener');
      return;
    }
    // segment word click - jump to that word's sentence
    if (btn.classList.contains('ctts-seg') && btn.dataset.idx !== undefined) {
      jumpTo(parseInt(btn.dataset.idx, 10));
    }
  }

  // ---- file upload (phase 1: plain text only) ----------------------------

  async function onFileChosen() {
    const file = els.fileInput.files[0];
    els.fileInput.value = '';
    if (!file) return;

    if (file.type === 'text/plain' || /\.txt$/i.test(file.name)) {
      const text = await file.text();
      startReadingText(text);
      return;
    }
    showStatus('PDF/Word support is coming in the next update - for now, .txt files only.', true);
  }

  function startReadingText(rawText) {
    const segments = self.CTTS_PAGE_TEXT.splitIntoSentences(rawText.replace(/\s+/g, ' ').trim())
      .filter(self.CTTS_PAGE_TEXT.hasChinese);
    if (segments.length === 0) {
      showStatus('No Chinese text found in that file.', true);
      return;
    }
    pageSegments = segments.map((text) => ({ text, paragraphIndex: -1 }));
    queue = new ReadingQueue(segments);
    exitReadingMode(); // this text isn't tied to the current page's DOM
    jumpTo(0);
    play();
  }

  // ---- reading the current page -------------------------------------------

  const BLOCK_SELECTOR = 'p, li, h1, h2, h3, h4, blockquote, td, dd, figcaption';

  function readWholePage() {
    const nodes = Array.from(document.querySelectorAll(BLOCK_SELECTOR)).filter(
      (el) => !root.contains(el) && el.offsetParent !== null // skip our own panel and hidden elements
    );
    pageSegments = extractSegments(nodes);
    if (pageSegments.length === 0) {
      showStatus('No Chinese text found on this page.', true);
      return;
    }
    queue = new ReadingQueue(pageSegments.map((s) => s.text));
    enterReadingMode(nodes);
    jumpTo(0);
    play();
  }

  /**
   * Wraps the same nodes readWholePage() just extracted segments from in
   * clickable spans on the page itself. Takes the exact same `nodes` array
   * (rather than re-querying) so this walk can't drift out of sync with
   * pageSegments/queue if the DOM changes between the two calls.
   */
  function enterReadingMode(nodes) {
    if (readingMode) exitReadingMode();
    readingMode = true;
    let segIdx = 0;
    const paragraphs = self.CTTS_PAGE_TEXT.nodesToParagraphs(nodes);
    // Re-walk in the same order extractSegments used, wrapping each matched node's text.
    let paraCursor = 0;
    for (const node of nodes) {
      const text = (node.textContent || '').replace(/\s+/g, ' ').trim();
      if (!text || !self.CTTS_PAGE_TEXT.hasChinese(text)) continue;
      if (paragraphs[paraCursor] !== text) continue; // dedup skip, mirrors nodesToParagraphs
      node.dataset.cttsOriginalHtml = node.innerHTML;
      node.dataset.cttsWrapped = 'true';
      const parts = self.CTTS_PAGE_TEXT.splitIntoSentences(text);
      node.innerHTML = parts
        .map((s) => {
          const span = `<span class="ctts-page-seg" data-action="jump" data-idx="${segIdx}">${escapeHtml(s)}</span>`;
          segIdx += 1;
          return span;
        })
        .join(' ');
      node.querySelectorAll('.ctts-page-seg').forEach((span) => {
        span.addEventListener('click', () => jumpTo(parseInt(span.dataset.idx, 10)));
      });
      paraCursor += 1;
      if (paraCursor >= paragraphs.length) break;
    }
  }

  function exitReadingMode() {
    if (!readingMode) return;
    readingMode = false;
    document.querySelectorAll('[data-ctts-wrapped="true"]').forEach((node) => {
      node.innerHTML = node.dataset.cttsOriginalHtml;
      delete node.dataset.cttsWrapped;
      delete node.dataset.cttsOriginalHtml;
    });
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function highlightPageSegment(idx) {
    document.querySelectorAll('.ctts-page-seg.ctts-page-seg-active').forEach((n) =>
      n.classList.remove('ctts-page-seg-active')
    );
    const active = document.querySelector(`.ctts-page-seg[data-idx="${idx}"]`);
    if (active) {
      active.classList.add('ctts-page-seg-active');
      active.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  // ---- selection capture --------------------------------------------------

  // A single click-and-drag (or double/triple click) selection fires several
  // `mouseup` events as the browser grows word -> sentence -> paragraph, each
  // with a different selection. Debounce so only the final, settled selection
  // triggers one TTS request instead of one per intermediate mouseup.
  let selectionDebounceTimer = null;
  let lastSelectionText = '';

  function onMouseUp() {
    clearTimeout(selectionDebounceTimer);
    selectionDebounceTimer = setTimeout(handleSettledSelection, 150);
  }

  function handleSettledSelection() {
    const sel = window.getSelection();
    const text = sel ? sel.toString().trim() : '';
    if (!text || text === lastSelectionText || !self.CTTS_PAGE_TEXT.hasChinese(text) || root.contains(sel.anchorNode)) {
      return;
    }
    lastSelectionText = text;
    openPanel();
    exitReadingMode();
    pageSegments = [{ text, paragraphIndex: -1 }];
    queue = ReadingQueue.forSelection(text);
    renderCurrent();
    playCurrentSegment();
  }

  // ---- playback -------------------------------------------------------------

  function jumpTo(idx) {
    queue.jumpTo(idx);
    renderCurrent();
    if (readingMode) highlightPageSegment(idx);
    if (queue.playing || currentAudio) playCurrentSegment();
  }

  function goNext() {
    if (queue.next()) {
      renderCurrent();
      if (readingMode) highlightPageSegment(queue.index);
      playCurrentSegment();
    } else {
      showStatus('End of text.');
      updatePlayButton();
    }
  }

  function goPrev() {
    if (queue.prev()) {
      renderCurrent();
      if (readingMode) highlightPageSegment(queue.index);
      playCurrentSegment();
    }
  }

  function togglePlay() {
    if (queue.isEmpty) return;
    if (queue.playing) {
      queue.pause();
      currentAudio?.pause();
    } else {
      play();
    }
    updatePlayButton();
  }

  function play() {
    queue.play();
    updatePlayButton();
    playCurrentSegment();
  }

  function updatePlayButton() {
    els.playBtn.textContent = queue.playing ? '⏸' : '▶';
  }

  async function playCurrentSegment() {
    const text = queue.current;
    if (!text) return;
    currentAudio?.pause();
    showStatus('Loading audio…');
    try {
      const blob = await fetchTTS(text);
      const audio = new Audio(URL.createObjectURL(blob));
      audio.volume = settings.volume;
      audio.playbackRate = settings.speed;
      audio.onended = () => {
        if (queue.playing) goNext();
      };
      currentAudio = audio;
      showStatus('');
      updatePlayButton();
      if (queue.playing) await audio.play();
    } catch (err) {
      if (err.status === 429) {
        showStatus(`${err.message} — sign in on the full site for unlimited use.`, true);
      } else {
        showStatus(`Couldn't read this: ${err.message}`, true);
      }
      queue.pause();
      updatePlayButton();
    }
  }

  // ---- rendering: current segment + pinyin + gloss ----------------------

  async function renderCurrent() {
    const text = queue.current;
    if (!text) {
      els.text.innerHTML = '';
      els.pinyin.textContent = '';
      els.gloss.textContent = '';
      return;
    }
    await ensureDictionary();
    const tokens = segmentAndGloss(text, dict);

    els.text.innerHTML = tokens
      .map(
        (t, i) =>
          `<span class="ctts-seg" data-action="jump-word" data-idx="${queue.index}" title="${
            t.py ? escapeHtml(t.py) : ''
          }">${escapeHtml(t.surface)}</span>`
      )
      .join('');

    // pinyin-pro gives accurate whole-sentence pinyin (tone sandhi etc.),
    // which is more reliable than stitching together our per-word dict lookups.
    try {
      els.pinyin.textContent = self.pinyinPro.pinyin(text, { toneType: 'symbol', type: 'string' });
    } catch (_) {
      els.pinyin.textContent = tokens.map((t) => t.py || '').join(' ');
    }

    const glosses = tokens.filter((t) => t.en).map((t) => t.en);
    els.gloss.textContent = glosses.length ? glosses.join(' · ') : '(no HSK 1-6 words recognized in this sentence)';
  }

  // ---- panel open/close -----------------------------------------------------

  function openPanel() {
    root.hidden = false;
  }

  function closePanel() {
    currentAudio?.pause();
    queue.pause();
    root.hidden = true;
  }

  function isPanelOpen() {
    return root && !root.hidden;
  }

  // ---- keyboard nav (only while panel is open and focus isn't editable) ----

  function isEditableTarget(el) {
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function onKeyDown(e) {
    if (!isPanelOpen() || isEditableTarget(e.target)) return;
    if (e.key === 'ArrowRight') { e.preventDefault(); goNext(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev(); }
    else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  }

  // ---- messages from background.js -----------------------------------------

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'CTTS_TOGGLE_PANEL') {
      if (isPanelOpen()) closePanel();
      else openPanel();
      sendResponse({ ok: true });
      return true;
    }
    if (msg.type === 'CTTS_READ_SELECTION') {
      openPanel();
      exitReadingMode();
      pageSegments = [{ text: msg.text, paragraphIndex: -1 }];
      queue = ReadingQueue.forSelection(msg.text);
      renderCurrent();
      playCurrentSegment();
      sendResponse({ ok: true });
      return true;
    }
  });

  // ---- init -------------------------------------------------------------

  (async function init() {
    await loadSettings();
    buildPanel();
    closePanel(); // start hidden; icon click / selection / context menu opens it
    document.addEventListener('mouseup', onMouseUp);
    document.addEventListener('keydown', onKeyDown);
    // Selection collapsed (user clicked away) - allow the same text to trigger a fresh read next time.
    document.addEventListener('selectionchange', () => {
      if (!window.getSelection()?.toString().trim()) lastSelectionText = '';
    });
  })();
})();
