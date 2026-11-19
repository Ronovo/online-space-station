import { afterEach, describe, expect, it, vi } from 'vitest';

const NAMES = ['Alex Chen', 'Morgan Yu'];

afterEach(() => {
  vi.restoreAllMocks();
});

/* The lobby as Flask renders it: the chooser, the career and single-round panels with their Back buttons, the
   round mode drop-down, and the two name fields with their Random buttons. */
async function load({ chooser = true, mode = true } = {}) {
  document.body.innerHTML = `
    ${
      chooser
        ? `<div id="lobby-chooser">
      <button type="button" data-lobby-choose="career">Career</button>
      <button type="button" data-lobby-choose="single">Single Round</button></div>`
        : ''
    }
    <div class="hidden" data-lobby-panel="career"><button type="button" data-lobby-back>Back</button></div>
    <div class="hidden" data-lobby-panel="single"><button type="button" data-lobby-back>Back</button>
      ${
        mode
          ? `<select id="round-mode">
        <option value="peaceful" data-description="Calm.">Peaceful</option>
        <option value="antagonist" data-description="Deadly.">Antagonist</option></select>
        <p id="round-mode-description"></p>`
          : ''
      }</div>
    <input type="text" id="career-name" value=""><button type="button" data-random-name="career-name">Random</button>
    <input type="text" id="round-name" value="Ada"><button type="button" data-random-name="round-name">Random</button>
    <script id="creation-data" type="application/json">${JSON.stringify({ names: NAMES })}</script>`;
  vi.resetModules();
  await import('../../space_online/webapp/static/create.js');
}

const $ = (id) => document.getElementById(id);
const randomButton = (target) => document.querySelector(`[data-random-name="${target}"]`);

describe('the lobby name fields', () => {
  it('suggests a random name for the field its button belongs to', async () => {
    await load();
    vi.spyOn(Math, 'random').mockReturnValue(0.99);
    randomButton('career-name').click();
    expect([$('career-name').value, $('round-name').value]).toEqual(['Morgan Yu', 'Ada']);
  });

  it('replaces a name that is already there', async () => {
    await load();
    vi.spyOn(Math, 'random').mockReturnValue(0);
    randomButton('round-name').click();
    expect($('round-name').value).toBe('Alex Chen');
  });
});

const hidden = (el) => el.classList.contains('hidden');
const choose = (name) => document.querySelector(`[data-lobby-choose="${name}"]`).click();
const panel = (name) => document.querySelector(`[data-lobby-panel="${name}"]`);

describe('the lobby chooser', () => {
  it('shows only the chosen panel and returns to the choices with Back', async () => {
    await load();
    choose('career');
    expect([hidden($('lobby-chooser')), hidden(panel('career')), hidden(panel('single'))]).toEqual([true, false, true]);
    panel('career').querySelector('[data-lobby-back]').click();
    expect([hidden($('lobby-chooser')), hidden(panel('career')), hidden(panel('single'))]).toEqual([false, true, true]);
    choose('single');
    expect([hidden($('lobby-chooser')), hidden(panel('career')), hidden(panel('single'))]).toEqual([true, true, false]);
  });

  it('still wires the name fields while a round is in progress', async () => {
    await load({ chooser: false, mode: false });
    vi.spyOn(Math, 'random').mockReturnValue(0);
    randomButton('round-name').click();
    expect($('round-name').value).toBe('Alex Chen');
  });
});

describe('the round mode description', () => {
  it('shows the selected mode on load and swaps it on change', async () => {
    await load();
    expect($('round-mode-description').textContent).toBe('Calm.');
    $('round-mode').value = 'antagonist';
    $('round-mode').dispatchEvent(new Event('change'));
    expect($('round-mode-description').textContent).toBe('Deadly.');
  });
});
