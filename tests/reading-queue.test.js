const { ReadingQueue } = require('../extension/lib/reading-queue');

describe('ReadingQueue navigation', () => {
  test('starts paused at index 0', () => {
    const q = new ReadingQueue(['a', 'b', 'c']);
    expect(q.index).toBe(0);
    expect(q.playing).toBe(false);
    expect(q.current).toBe('a');
  });

  test('next() advances and reports success until the end', () => {
    const q = new ReadingQueue(['a', 'b']);
    expect(q.next()).toBe(true);
    expect(q.current).toBe('b');
    expect(q.next()).toBe(false); // already at end
    expect(q.current).toBe('b'); // did not move past the end
  });

  test('next() past the end pauses playback', () => {
    const q = new ReadingQueue(['a']).play();
    expect(q.playing).toBe(true);
    q.next();
    expect(q.playing).toBe(false);
  });

  test('prev() moves back and no-ops at the start', () => {
    const q = new ReadingQueue(['a', 'b', 'c']);
    q.jumpTo(2);
    expect(q.prev()).toBe(true);
    expect(q.index).toBe(1);
    q.jumpTo(0);
    expect(q.prev()).toBe(false);
    expect(q.index).toBe(0);
  });

  test('jumpTo() validates bounds', () => {
    const q = new ReadingQueue(['a', 'b', 'c']);
    expect(q.jumpTo(1)).toBe(true);
    expect(q.index).toBe(1);
    expect(q.jumpTo(99)).toBe(false);
    expect(q.jumpTo(-1)).toBe(false);
    expect(q.index).toBe(1); // unchanged after invalid jumps
  });

  test('togglePlay flips playing state; play()/pause() are no-ops on an empty queue', () => {
    const empty = new ReadingQueue([]);
    empty.play();
    expect(empty.playing).toBe(false);

    const q = new ReadingQueue(['a']);
    expect(q.togglePlay().playing).toBe(true);
    expect(q.togglePlay().playing).toBe(false);
  });

  test('atStart/atEnd/isEmpty flags', () => {
    const q = new ReadingQueue(['a', 'b']);
    expect(q.atStart).toBe(true);
    expect(q.atEnd).toBe(false);
    q.next();
    expect(q.atStart).toBe(false);
    expect(q.atEnd).toBe(true);
    expect(new ReadingQueue([]).isEmpty).toBe(true);
  });

  test('forSelection() builds a single-segment queue and starts playing', () => {
    const q = ReadingQueue.forSelection('选中的文字');
    expect(q.segments).toEqual(['选中的文字']);
    expect(q.playing).toBe(true);
    expect(q.atStart && q.atEnd).toBe(true); // single segment: both start and end
  });
});
