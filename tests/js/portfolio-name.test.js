import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function load(fetch) {
  document.body.innerHTML = '<a class="btn" id="portfolio-button" href="/sso/login" '
    + 'data-portfolio-url="http://portfolio.test">Log In with Portfolio Account</a>';
  vi.stubGlobal('fetch', fetch);
  vi.resetModules();
  await import('../../space_online/webapp/static/portfolio-name.js');
  await new Promise((resolve) => setTimeout(resolve, 0));
  return document.getElementById('portfolio-button').textContent;
}

const answer = (ok, body) => vi.fn(async () => ({ ok, json: async () => body }));

describe('the portfolio login button', () => {
  it('names the portfolio account this browser is logged in to', async () => {
    const fetch = answer(true, { username: 'ronovo' });
    expect(await load(fetch)).toBe('Log In as ronovo');
    expect(fetch).toHaveBeenCalledWith('http://portfolio.test/sso/me',
      { credentials: 'include', signal: expect.any(AbortSignal) });
  });

  it.each([
    ['nobody is logged in', answer(true, {})],
    ['the portfolio answers with an error', answer(false, { username: 'ronovo' })],
    ['the portfolio cannot be reached', vi.fn(async () => { throw new TypeError('offline'); })],
  ])('keeps its text when %s', async (_, fetch) => {
    expect(await load(fetch)).toBe('Log In with Portfolio Account');
  });
});
