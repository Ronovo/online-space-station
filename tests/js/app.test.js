import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const listeners = [];
let server;
let browser;

beforeEach(() => {
  vi.useFakeTimers();
  for (const target of [window, document]) {
    const listen = target.addEventListener;
    vi.spyOn(target, 'addEventListener').mockImplementation(function track(type, listener, options) {
      listeners.push([target, type, listener, options]);
      return listen.call(this, type, listener, options);
    });
  }
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
});

afterEach(() => {
  for (const [target, type, listener, options] of listeners.splice(0)) target.removeEventListener(type, listener, options);
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function reply(body, { status = 200, redirected = false, url = '', type = 'application/json' } = {}) {
  return { ok: status >= 200 && status < 300, status, redirected, url, headers: { get: () => type },
    json: async () => body };
}

/* A fake /api/act: answers each request with the next queued reply, or a quiet tick. */
function fakeServer() {
  const calls = [];
  const replies = [];
  const fetch = vi.fn(async (url, options) => {
    calls.push({ url, headers: options.headers, ...JSON.parse(options.body) });
    const next = replies.shift();
    if (typeof next === 'function') return next();
    return next || reply({ hash: 'same', title: 'Space Station Explorer', choice: null });
  });
  vi.stubGlobal('fetch', fetch);
  return { calls, replies, fetch };
}

/* The play page as Flask renders it: the screen, the modal and the initial state. */
async function boot(screenHtml = '', initial = {}) {
  document.head.innerHTML = '<meta name="csrf-token" content="token-1">';
  document.body.innerHTML = `
    <div id="connection" class="connection hidden">Connection lost. Retrying…</div>
    <div class="game-window" id="screen" data-act-url="/api/act" data-home-url="/home">${screenHtml}</div>
    <div id="modal" class="modal hidden"><div class="modal-box">
      <h3 id="modal-title"></h3><p id="modal-message"></p><div id="modal-buttons" class="button-row"></div>
    </div></div>
    <script id="initial-state" type="application/json">${JSON.stringify({ hash: 'h0', choice: null,
      ...initial })}</script>`;
  server = fakeServer();
  browser = { href: '' };
  vi.stubGlobal('location', browser);
  vi.resetModules();
  await import('../../space_online/webapp/static/app.js');
}

const settle = () => vi.advanceTimersByTimeAsync(0);
const $ = (id) => document.getElementById(id);
const modalShown = () => !$('modal').classList.contains('hidden');
const modalButtons = () => [...$('modal-buttons').querySelectorAll('button')].map((b) => b.textContent);
const actions = () => server.calls.map((call) => call.action);

async function click(element) {
  element.click();
  await settle();
}

async function tickTo(html, hash = 'h1', fields = {}) {
  server.replies.push(reply({ hash, html, choice: null, ...fields }));
  await vi.advanceTimersByTimeAsync(1000);
}

const pick = { id: 'c1', title: 'Drop', message: 'Sure?', buttons: ['Yes', 'No'] };

describe('choices', () => {
  it('answers a choice and keeps it closed until the answer is back', async () => {
    await boot('', { choice: pick });
    expect([$('modal-title').textContent, $('modal-message').textContent, modalButtons()]).toEqual(
      ['Drop', 'Sure?', ['Yes', 'No']]);
    expect(document.activeElement.textContent).toBe('Yes');
    let answer;
    server.replies.push(() => new Promise((resolve) => { answer = resolve; }));
    await click($('modal-buttons').querySelectorAll('button')[1]);
    expect(modalShown()).toBe(false);
    expect(server.calls.at(-1)).toMatchObject({ action: 'game.choose', args: { id: 'c1', index: 1 }, hash: 'h0' });
    answer(reply({ hash: 'h0', choice: { id: 'c2', title: 'Next', message: 'And this?', buttons: ['OK'] } }));
    await settle();
    expect($('modal-title').textContent).toBe('Next');
  });

  it('ignores a choice from replies sent before the answer', async () => {
    await boot('', { choice: pick });
    let tick;
    server.replies.push(() => new Promise((resolve) => { tick = resolve; }));
    await vi.advanceTimersByTimeAsync(1000);
    await click($('modal-buttons').querySelector('button'));
    tick(reply({ hash: 'h0', choice: pick }));
    await settle();
    expect(modalShown()).toBe(false);
    expect(actions()).toEqual(['tick', 'game.choose']);
  });

  it('leaves a choice that is already showing as it is', async () => {
    await boot('', { choice: pick });
    const yes = $('modal-buttons').querySelector('button');
    server.replies.push(reply({ hash: 'h0', choice: pick }));
    await vi.advanceTimersByTimeAsync(1000);
    expect($('modal-buttons').querySelector('button')).toBe(yes);
  });

  it('shows a new choice from the server', async () => {
    await boot();
    server.replies.push(reply({ hash: 'h0', choice: { id: 'c2', title: 'Drop', message: 'Sure?',
      buttons: ['Yes'] } }));
    await vi.advanceTimersByTimeAsync(1000);
    expect([$('modal-title').textContent, modalButtons()]).toEqual(['Drop', ['Yes']]);
    await vi.advanceTimersByTimeAsync(1000);
    expect(modalShown()).toBe(false);
  });
});

describe('the clock', () => {
  it('ticks every second while nothing else is waiting', async () => {
    await boot();
    let slow;
    server.replies.push(() => new Promise((resolve) => { slow = resolve; }));
    await vi.advanceTimersByTimeAsync(3000);
    expect(actions()).toEqual(['tick']);
    slow(reply({ hash: 'h0', choice: null }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(actions()).toEqual(['tick', 'tick']);
    expect(server.calls[0]).toMatchObject({ args: {}, hash: 'h0', headers: { 'X-CSRF-Token': 'token-1' } });
  });

  it('swaps in a new screen and title and sends the new hash back', async () => {
    await boot('<p>old</p>');
    await tickTo('<p>new</p>', 'h1', { title: 'Bar' });
    expect([$('screen').innerHTML, document.title]).toEqual(['<p>new</p>', 'Bar']);
    await vi.advanceTimersByTimeAsync(1000);
    expect(server.calls[1].hash).toBe('h1');
    expect($('screen').innerHTML).toBe('<p>new</p>');
  });

  it('keeps what the player typed, their cursor and scroll position through a tick', async () => {
    const form = (value) => `<div data-scroll-key="list" id="list"></div><input id="reason" value="${value}">
      <input id="shares" type="number" value="1"><input id="level" type="range" value="3">`;
    await boot(form(''));
    $('reason').value = 'Theft';
    $('reason').focus();
    $('reason').setSelectionRange(1, 3);
    $('list').scrollTop = 40;
    await tickTo(`${form('')}<div data-scroll-key="new" id="new"></div>`);
    expect([$('reason').value, document.activeElement.id, $('reason').selectionStart, $('reason').selectionEnd])
      .toEqual(['Theft', 'reason', 1, 3]);
    expect([$('list').scrollTop, $('new').scrollTop]).toEqual([40, 0]);
    $('shares').focus();
    await tickTo(form(''), 'h2');
    expect(document.activeElement.id).toBe('shares');
  });

  it('keeps the option picked in a dropdown through a tick', async () => {
    const form = '<select id="kind"><option value="healer">Healer</option><option value="warper">Warper</option></select>';
    await boot(form);
    $('kind').value = 'warper';
    await tickTo(form);
    expect($('kind').value).toBe('warper');
  });

  it('remembers where a list was scrolled while another panel covers it, until every panel closes', async () => {
    const crewPanel = '<section class="panel"><div data-scroll-key="crew" id="crew"></div></section>';
    await boot(crewPanel);
    $('crew').scrollTop = 60;
    for (const html of ['<section class="panel"><p>charge</p></section>', crewPanel]) await tickTo(html, html);
    expect($('crew').scrollTop).toBe(60);
    for (const html of ['<p>hallway</p>', crewPanel]) await tickTo(html, html);
    expect($('crew').scrollTop).toBe(0);
  });

  it('forgets inputs that are gone after the swap and leaves fields outside the screen alone', async () => {
    await boot('<input id="reason">');
    document.body.insertAdjacentHTML('beforeend', '<input id="outside" value="kept">');
    $('reason').value = 'Theft';
    $('reason').focus();
    await tickTo('<p>panel closed</p>');
    expect($('reason')).toBeNull();
    $('outside').focus();
    await tickTo('<input id="outside">', 'h2');
    expect([$('outside').value, document.activeElement.value]).toEqual(['', 'kept']);
  });

  it('puts the window back where it was scrolled', async () => {
    await boot('<p>old</p>');
    window.scrollY = 120;
    await tickTo('<p>new</p>');
    expect(window.scrollTo).toHaveBeenLastCalledWith(0, 120);
  });

  it('keeps focus on fields and buttons that have no text selection', async () => {
    const screen = '<input id="email" type="email"><button type="button" id="pick">Pick</button>';
    await boot(screen);
    Object.defineProperty($('email'), 'selectionStart', {
      get() { throw new DOMException('Selection is not supported on this input type.', 'InvalidStateError'); },
    });
    $('email').focus();
    await tickTo(screen);
    expect(document.activeElement.id).toBe('email');
    $('pick').focus();
    await tickTo(screen, 'h2');
    expect(document.activeElement.id).toBe('pick');
  });

  it('waits to swap the screen while a slider is being dragged', async () => {
    await boot('<input id="level" type="range" value="3">');
    $('level').dispatchEvent(new Event('pointerdown', { bubbles: true }));
    await tickTo('<p>new</p>');
    expect($('level')).not.toBeNull();
    document.dispatchEvent(new Event('pointerup'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(server.calls[1].hash).toBe('h0');
    document.dispatchEvent(new Event('pointerdown'));
    $('level').dispatchEvent(new Event('pointerdown', { bubbles: true }));
    document.dispatchEvent(new Event('pointercancel'));
    await tickTo('<p>new</p>', 'h2');
    expect($('screen').innerHTML).toBe('<p>new</p>');
  });
});

describe('player actions', () => {
  it('sends a button action with its arguments and its form fields', async () => {
    await boot(`<form><input name="reason" value="Theft">
      <button type="button" id="go" data-action="panel.confirm" data-args='{"amount": "5"}'>Go</button></form>
      <button type="button" id="bad" data-action="room.exit" data-args="{not json">Exit</button>
      <button type="button" id="off" data-action="room.exit" disabled>Off</button>`);
    await click($('go'));
    expect(server.calls.at(-1)).toMatchObject({ action: 'panel.confirm', args: { reason: 'Theft', amount: '5' } });
    await click($('bad'));
    expect(server.calls.at(-1)).toMatchObject({ action: 'room.exit', args: {} });
    await click($('off'));
    expect(server.calls).toHaveLength(2);
  });

  it('applies the reply to a button straight away and focuses its autofocus field', async () => {
    await boot('<button type="button" id="go" data-action="room.storage">Storage</button>');
    server.replies.push(reply({ hash: 'h1', html: '<input id="field" autofocus>'
      + '<button type="button" id="close" data-action="game.close_panel">Close</button>', choice: null }));
    await click($('go'));
    expect(document.activeElement.id).toBe('field');
    server.replies.push(reply({ hash: 'h2', html: '<p>Quarters</p>', choice: null }));
    await click($('close'));
    expect($('screen').innerHTML).toBe('<p>Quarters</p>');
  });

  it('applies a reply that leaves out the choice', async () => {
    await boot('<p>old</p>');
    server.replies.push(reply({ hash: 'h1', html: '<p>new</p>' }));
    await vi.advanceTimersByTimeAsync(1000);
    expect([$('screen').innerHTML, modalShown()]).toEqual(['<p>new</p>', false]);
  });

  it('leaves clicks on plain elements, fields, forms and anything outside the screen alone', async () => {
    await boot('<p id="text">Hello</p><form id="form" data-action="x"></form><input id="field" data-action="x">');
    document.body.insertAdjacentHTML('beforeend', '<button id="outside" data-action="room.exit">Out</button>');
    for (const id of ['text', 'form', 'field', 'outside']) await click($(id));
    expect(server.calls).toEqual([]);
  });

  it('sends a form submission with its arguments and fields', async () => {
    await boot(`<form id="search" data-action="panel.search" data-args='{"page": 1}'><input name="query" value="gin">
      </form><form id="plain"><input name="x"></form>`);
    $('search').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    const plain = new Event('submit', { bubbles: true, cancelable: true });
    $('plain').dispatchEvent(plain);
    await settle();
    expect(server.calls.map(({ action, args }) => [action, args])).toEqual([['panel.search', { page: 1, query: 'gin' }]]);
    expect(plain.defaultPrevented).toBe(true);
    document.body.insertAdjacentHTML('beforeend', '<form id="away" data-action="x"></form>');
    const away = new Event('submit', { bubbles: true, cancelable: true });
    $('away').dispatchEvent(away);
    expect(away.defaultPrevented).toBe(false);
  });

  it('sends slider and radio changes', async () => {
    await boot(`<input id="level" type="range" value="7" data-action="panel.set_level" data-args='{"system": "life_support"}'>
      <input id="high" type="radio" name="mode" data-action="panel.set_power_mode" data-args='{"mode": "high"}'>
      <input id="text" type="text" data-action="panel.search"><input id="plain" type="range">`);
    $('level').dispatchEvent(new Event('change', { bubbles: true }));
    $('high').dispatchEvent(new Event('change', { bubbles: true }));
    $('high').checked = true;
    $('high').dispatchEvent(new Event('change', { bubbles: true }));
    $('text').dispatchEvent(new Event('change', { bubbles: true }));
    $('plain').dispatchEvent(new Event('change', { bubbles: true }));
    document.body.insertAdjacentHTML('beforeend', '<input id="away" type="range" data-action="x">');
    $('away').dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(server.calls.map(({ action, args }) => [action, args])).toEqual([
      ['panel.set_level', { system: 'life_support', value: '7' }], ['panel.set_power_mode', { mode: 'high' }]]);
  });

  it('shows a slider value as it moves', async () => {
    await boot('<input id="level" type="range" value="4"><output for="level">4</output><input id="lone" type="range">'
      + '<input id="note" type="text" value="hi"><output for="note">-</output><output for="away">-</output>');
    $('level').value = '9';
    $('level').dispatchEvent(new Event('input', { bubbles: true }));
    $('lone').dispatchEvent(new Event('input', { bubbles: true }));
    $('note').dispatchEvent(new Event('input', { bubbles: true }));
    document.body.insertAdjacentHTML('beforeend', '<input id="away" type="range" value="2">');
    $('away').dispatchEvent(new Event('input', { bubbles: true }));
    expect([...document.querySelectorAll('output')].map((output) => output.textContent)).toEqual(['9', '-', '-']);
  });
});

describe('getting hurt', () => {
  const bar = (health) => `<span data-health="${health}">Health ${health}%</span>`;
  const hurt = () => $('screen').classList.contains('hurt');

  it('flashes the screen when the health shown drops, and not when it holds or rises', async () => {
    await boot(bar(90));
    expect(hurt()).toBe(false);
    await tickTo(bar(90));
    expect(hurt()).toBe(false);
    await tickTo(bar(72), 'h2');
    expect(hurt()).toBe(true);
    $('screen').classList.remove('hurt');
    await tickTo(bar(100), 'h3');
    expect(hurt()).toBe(false);
  });

  it('does not flash when a screen has no health readout', async () => {
    await boot(bar(90));
    await tickTo('<p>no bar</p>');
    await tickTo(bar(10), 'h2');
    expect(hurt()).toBe(false);
  });
});

describe('share trading', () => {
  const panel = `<input id="shares-input" data-share-input data-price="12.5" data-credits="100" data-owned="3" value="">
    <span data-share-total>Total: 0.00</span><button data-share-buy>Buy</button><button data-share-sell>Sell</button>
    <button type="button" id="max" data-set-input="shares-input" data-value="8">Max Buy</button>
    <button type="button" id="nowhere" data-set-input="missing" data-value="1">Broken</button>`;
  const totals = () => [document.querySelector('[data-share-total]').textContent,
    document.querySelector('[data-share-buy]').disabled, document.querySelector('[data-share-sell]').disabled];

  async function type(value) {
    $('shares-input').value = value;
    $('shares-input').dispatchEvent(new Event('input', { bubbles: true }));
  }

  it('totals the shares and allows only the trades the player can make', async () => {
    await boot(panel);
    expect(totals()).toEqual(['Total: 0.00', true, true]);
    await type('3');
    expect(totals()).toEqual(['Total: 37.50', false, false]);
    await type('9');
    expect(totals()).toEqual(['Total: 112.50', true, true]);
    await type('1.5');
    expect(totals()).toEqual(['Total: 0.00', true, true]);
  });

  it('fills in the maximum with one click', async () => {
    await boot(panel);
    await click($('max'));
    expect([$('shares-input').value, ...totals()]).toEqual(['8', 'Total: 100.00', false, true]);
    await click($('nowhere'));
    expect(server.calls).toEqual([]);
  });
});

describe('the connection', () => {
  it('follows a redirect the server asks for', async () => {
    await boot();
    server.replies.push(reply({ redirect: '/character/new' }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(browser.href).toBe('/character/new');
  });

  it('goes where a redirected request ended up, or home when the reply is not JSON', async () => {
    await boot();
    server.replies.push(reply({}, { redirected: true, url: '/login' }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(browser.href).toBe('/login');
    server.replies.push(reply({}, { type: 'text/html' }));
    await vi.advanceTimersByTimeAsync(1000);
    expect(browser.href).toBe('/home');
  });

  it('reads a reply with no content type as not JSON', async () => {
    await boot();
    server.replies.push({ ok: true, status: 200, redirected: false, headers: { get: () => null } });
    await vi.advanceTimersByTimeAsync(1000);
    expect(browser.href).toBe('/home');
  });

  it('warns while the server fails and clears the warning when it answers', async () => {
    await boot();
    server.replies.push(reply({ error: 'boom' }, { status: 500 }), () => Promise.reject(new TypeError('offline')));
    await vi.advanceTimersByTimeAsync(1000);
    expect($('connection').classList.contains('hidden')).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect($('connection').classList.contains('hidden')).toBe(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect($('connection').classList.contains('hidden')).toBe(true);
  });

  it('shows the choice again when the answer could not be sent', async () => {
    await boot('', { choice: pick });
    server.replies.push(() => Promise.reject(new TypeError('offline')), reply({ hash: 'h0', choice: pick }));
    await click($('modal-buttons').querySelector('button'));
    await vi.advanceTimersByTimeAsync(1000);
    expect(modalButtons()).toEqual(['Yes', 'No']);
  });
});
