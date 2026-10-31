import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const DATA = {
  departments: [['Civilian', ['Staff Assistant', 'Botanist']], ['Medical', ['Doctor']]],
  jobs: {
    'Staff Assistant': { credits: 1000, description: 'Backbone of the station.' },
    Botanist: { credits: 3000, description: 'Grows things.' },
    Doctor: { credits: 7500, description: 'Heals people.' },
  },
  names: ['Alex Chen', 'Morgan Yu'],
  selectJob: 'Select A Job',
};

const listeners = [];

beforeEach(() => {
  const listen = document.addEventListener;
  vi.spyOn(document, 'addEventListener').mockImplementation(function track(type, listener, options) {
    listeners.push([type, listener, options]);
    return listen.call(this, type, listener, options);
  });
});

afterEach(() => {
  for (const [type, listener, options] of listeners.splice(0)) document.removeEventListener(type, listener, options);
  vi.restoreAllMocks();
});

/* The character creation form as Flask renders it, after a post that kept department and job. */
async function load({ department = 'Select A Department', job = 'Select A Job' } = {}) {
  const departments = DATA.departments.map(([name]) => `<option value="${name}"${name === department ? ' selected' : ''}>${name}</option>`);
  document.body.innerHTML = `
    <input type="text" id="name" value=""><button type="button" id="random-name">Random</button>
    <select id="department"><option value="Select A Department">Select A Department</option>${departments.join('')}</select>
    <select id="job" data-selected="${job}"><option value="Select A Job">Select A Job</option></select>
    <span id="job-credits">-</span><p id="job-description">Select a department and job to see details.</p>
    <script id="creation-data" type="application/json">${JSON.stringify(DATA)}</script>`;
  vi.resetModules();
  await import('../../space_online/webapp/static/create.js');
}

const $ = (id) => document.getElementById(id);
const jobs = () => [...$('job').options].map((option) => option.value);
const shown = () => [$('job').value, $('job-credits').textContent, $('job-description').textContent];

function choose(id, value) {
  $(id).value = value;
  $(id).dispatchEvent(new Event('change'));
}

describe('character creation', () => {
  it('starts with no department and no job', async () => {
    await load();
    expect(jobs()).toEqual(['Select A Job']);
    expect(shown()).toEqual(['Select A Job', '-', 'Select a department and job to see details.']);
  });

  it('lists a department\'s jobs and describes the first', async () => {
    await load();
    choose('department', 'Civilian');
    expect(jobs()).toEqual(['Staff Assistant', 'Botanist']);
    expect(shown()).toEqual(['Staff Assistant', '1000 cr', 'Backbone of the station.']);
    choose('job', 'Botanist');
    expect(shown()).toEqual(['Botanist', '3000 cr', 'Grows things.']);
    choose('department', 'Medical');
    expect(shown()).toEqual(['Doctor', '7500 cr', 'Heals people.']);
  });

  it('keeps the job picked before a form error', async () => {
    await load({ department: 'Civilian', job: 'Botanist' });
    expect(shown()).toEqual(['Botanist', '3000 cr', 'Grows things.']);
  });

  it('falls back to the first job when the kept job is not in the department', async () => {
    await load({ department: 'Medical', job: 'Botanist' });
    expect(shown()[0]).toBe('Doctor');
  });

  it('suggests a random name', async () => {
    await load();
    vi.spyOn(Math, 'random').mockReturnValue(0.99);
    $('random-name').click();
    expect($('name').value).toBe('Morgan Yu');
  });
});
