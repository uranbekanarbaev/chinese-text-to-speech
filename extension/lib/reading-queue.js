/**
 * Pure playback-position state machine for the reading panel. Knows nothing
 * about audio or the DOM - just tracks "which segment are we on", so the
 * next/prev/jump/play/pause logic (and the arrow-key bindings, and the
 * click-to-jump handler) all funnel through one testable place instead of
 * being scattered across DOM event handlers.
 */
(function (root) {
  class ReadingQueue {
    /** @param {string[]} segments texts to read, in order */
    constructor(segments) {
      this.segments = segments || [];
      this.index = 0;
      this.playing = false;
    }

    get current() {
      return this.segments[this.index] ?? null;
    }

    get atStart() {
      return this.index <= 0;
    }

    get atEnd() {
      return this.index >= this.segments.length - 1;
    }

    get isEmpty() {
      return this.segments.length === 0;
    }

    play() {
      if (!this.isEmpty) this.playing = true;
      return this;
    }

    pause() {
      this.playing = false;
      return this;
    }

    togglePlay() {
      return this.playing ? this.pause() : this.play();
    }

    /** Advances one segment. Returns false (and pauses) if already at the end. */
    next() {
      if (this.atEnd) {
        this.playing = false;
        return false;
      }
      this.index += 1;
      return true;
    }

    /** Moves back one segment. No-ops at the start. */
    prev() {
      if (this.atStart) return false;
      this.index -= 1;
      return true;
    }

    /** Jumps straight to a segment index (e.g. user clicked a paragraph on the page). */
    jumpTo(index) {
      if (index < 0 || index >= this.segments.length) return false;
      this.index = index;
      return true;
    }

    /** Replaces the queue with a single ad-hoc segment (e.g. a text selection) and starts reading it. */
    static forSelection(text) {
      const q = new ReadingQueue([text]);
      q.play();
      return q;
    }
  }

  const api = { ReadingQueue };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.CTTS_READING_QUEUE = api;
  }
})(typeof self !== 'undefined' ? self : globalThis);
