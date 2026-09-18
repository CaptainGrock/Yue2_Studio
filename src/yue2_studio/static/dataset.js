'use strict';
// Separate CPU-only tool; deliberately independent of the generation player/queue.
(() => {
  const el = id => document.getElementById(id);
  let timer, pending = false;
  function render(value) {
    const job = value.job || {}, tracks = job.tracks || [];
    if (!el('datasetFolder').value) el('datasetFolder').value = value.default_folder;
    el('datasetTools').textContent = Object.entries(value.tools).map(([name, ok]) => `${name}: ${ok ? 'ready' : 'missing'}`).join(' · ');
    el('datasetStart').disabled = value.busy || !Object.values(value.tools).every(Boolean);
    el('datasetInstall').disabled = value.busy;
    el('datasetCancel').disabled = !value.busy;
    const finished = tracks.filter(t => ['saved','skipped','failed'].includes(t.status)).length;
    el('datasetStatus').textContent = `${job.status || 'Ready'}${tracks.length ? ` · ${finished}/${tracks.length} tracks` : ''} — ${job.message || 'Paste a playlist URL to begin.'}`;
    el('datasetProgress').max = tracks.length || 1;
    el('datasetProgress').value = finished;
    el('datasetTracks').replaceChildren(...tracks.map(track => {
      const row = document.createElement('p');
      row.textContent = `${track.status}: ${track.filename || track.title} — ${track.message}`;
      return row;
    }));
    el('datasetLog').textContent = job.log ? `Log: ${job.log}` : '';
  }
  async function refresh() {
    clearTimeout(timer);
    if (pending) return;
    pending = true;
    try { render(await api('/api/dataset-import')); }
    catch (error) { el('datasetStatus').textContent = error.message; }
    finally { pending = false; if (el('datasetDialog').open) timer = setTimeout(refresh, 1500); }
  }
  async function action(name, data = {}) {
    el('datasetStart').disabled = el('datasetInstall').disabled = true;
    try { render(await api('/api/dataset-import/' + name, data)); }
    catch (error) { el('datasetError').textContent = error.message; refresh(); return; }
    finally { if (!el('datasetDialog').open) clearTimeout(timer); }
    el('datasetError').textContent = '';
    refresh();
  }
  el('datasetNav').onclick = () => { el('datasetDialog').showModal(); refresh(); };
  el('datasetDialog').addEventListener('close', () => clearTimeout(timer));
  el('datasetStart').onclick = () => action('start', {url: el('datasetUrl').value, folder: el('datasetFolder').value, fallback_artist: el('datasetArtist').value});
  el('datasetCancel').onclick = () => action('cancel');
  el('datasetInstall').onclick = () => action('install');
})();


// Lyrics have their own state; download polling never rebuilds these controls.
(() => {
  const el = id => document.getElementById(id);
  let tracks = [], loadedFolder = '', working = false, stop = false;
  function node(tag, text, className) {
    const item = document.createElement(tag);
    if (text !== undefined) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  function tab(name) {
    for (const [key, prefix] of [['audio','datasetAudio'],['lyrics','datasetLyrics'],['structure','datasetStructure']]) {
      el(prefix + 'Panel').hidden = name !== key;
      el(prefix + 'Tab').setAttribute('aria-pressed', String(name === key));
    }
  }
  function controls() {
    el('datasetLyricsLoad').disabled = working;
    el('datasetLyricsSearchAll').disabled = working || !tracks.some(t => !t.exists);
    el('datasetLyricsSaveAll').disabled = working || !tracks.some(t => !t.exists && t.selected?.text && !t.selected?.instrumental);
    el('datasetLyricsStop').disabled = !working;
    tracks.forEach(t => { t.search.disabled = working || t.exists; t.save.disabled = working || !t.selected?.text || t.selected?.instrumental || t.exists; });
  }
  function card(track) {
    const box = node('section', undefined, 'trainer-panel');
    box.append(node('h4', track.filename));
    const fields = node('div', undefined, 'row wrap');
    const artistLabel = node('label', 'Artist / band'), titleLabel = node('label', 'Song title');
    track.artistInput = node('input'); track.artistInput.value = track.artist; track.artistInput.maxLength = 300;
    track.titleInput = node('input'); track.titleInput.value = track.title; track.titleInput.maxLength = 300;
    artistLabel.append(track.artistInput); titleLabel.append(track.titleInput); fields.append(artistLabel, titleLabel);
    track.feedback = node('p', track.exists ? 'Text file already exists — skipped.' : track.error || 'Ready to search.', 'hint');
    const actions = node('div', undefined, 'row wrap');
    track.search = node('button', 'Search', 'button subtle');
    track.search.onclick = () => execute([track]);
    track.select = node('select'); track.select.hidden = true; track.select.setAttribute('aria-label', 'LRCLIB matches for ' + track.filename);
    const preview = node('details'); preview.append(node('summary', 'Review retrieved lyrics'));
    track.preview = node('textarea'); track.preview.readOnly = true; track.preview.rows = 12;
    track.preview.setAttribute('aria-label', 'Retrieved lyrics for ' + track.filename);
    preview.append(track.preview);
    track.save = node('button', 'Save reviewed lyrics', 'button primary'); track.save.disabled = true;
    track.select.onchange = () => choose(track, Number(track.select.value));
    const invalidate = () => {
      track.selected = null; track.matches = []; track.select.hidden = true;
      track.preview.value = ''; track.feedback.textContent = 'Search again with the edited names.'; controls();
    };
    track.artistInput.oninput = track.titleInput.oninput = invalidate;
    track.save.onclick = async () => {
      if (working || !track.selected?.text || track.exists) return;
      working = true; controls();
      try {
        const result = await api('/api/dataset-lyrics/save', {folder:loadedFolder, filename:track.filename, text:track.selected.text});
        track.exists = true; track.feedback.textContent = 'Saved ' + result.filename;
      } catch (error) { track.feedback.textContent = error.message; }
      finally { working = false; controls(); }
    };
    actions.append(track.search, track.save);
    box.append(fields, track.feedback, actions, track.select, preview);
    return box;
  }
  function choose(track, index) {
    track.selected = track.matches[index];
    const selected = track.selected;
    track.preview.value = selected?.text || '';
    if (selected) track.feedback.textContent = (selected.instrumental ? 'Marked instrumental — no lyric file will be saved.' :
      selected.text ? 'Review the lyrics and recording before saving.' : 'This record has no usable lyrics.') +
      (selected.duration_difference === null ? '' : ' Duration difference: ' + selected.duration_difference + 's.');
    controls();
  }
  async function execute(items) {
    if (working) return;
    working = true; stop = false; controls();
    let done = 0;
    try {
      for (const track of items) {
        if (stop) break;
        if (track.exists) continue;
        track.artistInput.disabled = track.titleInput.disabled = true;
        track.selected = null; track.preview.value = ''; track.select.hidden = true;
        track.feedback.textContent = 'Searching LRCLIB…';
        try {
          const result = await api('/api/dataset-lyrics/search', {artist:track.artistInput.value, title:track.titleInput.value, duration:track.duration});
          track.matches = result.matches;
          track.select.replaceChildren(...track.matches.map((match, i) => {
            const option = node('option', [match.artist, match.title, match.album || 'Unknown album', match.duration == null ? '?' : match.duration + 's'].join(' · '));
            option.value = String(i); return option;
          }));
          track.select.hidden = !track.matches.length;
          track.select.value = '0';
          if (track.matches.length) choose(track, 0);
          else track.feedback.textContent = 'No matches. Edit artist/title and try again.';
        } catch (error) {
          track.feedback.textContent = error.message;
          if (/rate limit/i.test(error.message)) stop = true;
        } finally { track.artistInput.disabled = track.titleInput.disabled = false; }
        done++;
        el('datasetLyricsStatus').textContent = 'Searched ' + done + ' track(s). Review each result before saving.';
      }
    } finally {
      working = false; controls();
      if (stop) el('datasetLyricsStatus').textContent = 'Search stopped. Results already retrieved remain available.';
    }
  }
  el('datasetAudioTab').onclick = () => tab('audio');
  el('datasetLyricsTab').onclick = () => tab('lyrics');
  el('datasetStructureTab').onclick = () => tab('structure');
  el('datasetLyricsStop').onclick = () => { stop = true; };
  el('datasetDialog').addEventListener('close', () => { stop = true; });
  el('datasetLyricsSearchAll').onclick = () => execute(tracks.filter(t => !t.exists));
  el('datasetLyricsSaveAll').onclick = async () => {
    if (working) return;
    const items = tracks.filter(t => !t.exists && t.selected?.text && !t.selected?.instrumental)
      .map(t => ({track:t, text:t.selected.text}));
    if (!items.length) return;
    working = true; stop = false; controls();
    let saved = 0, failed = 0;
    try {
      for (const item of items) {
        if (stop) break;
        try {
          const result = await api('/api/dataset-lyrics/save', {folder:loadedFolder, filename:item.track.filename, text:item.text});
          item.track.exists = true;
          item.track.feedback.textContent = 'Saved ' + result.filename;
          saved++;
        } catch (error) { failed++; item.track.feedback.textContent = error.message; }
        el('datasetLyricsStatus').textContent = 'Saved ' + saved + '/' + items.length + ' selected matches · ' + failed + ' failed.';
      }
    } finally {
      working = false; controls();
      el('datasetLyricsStatus').textContent = (stop ? 'Stopped. ' : 'Finished. ') + saved + ' saved · ' + failed + ' failed · ' + (items.length-saved-failed) + ' remaining. Existing files were not overwritten.';
    }
  };
  el('datasetLyricsLoad').onclick = async () => {
    if (working) return;
    working = true; controls();
    try {
      const result = await api('/api/dataset-lyrics/scan', {folder:el('datasetFolder').value, fallback_artist:el('datasetArtist').value});
      loadedFolder = result.folder; tracks = result.tracks;
      el('datasetLyricsTracks').replaceChildren(...tracks.map(card));
      el('datasetLyricsStatus').textContent = 'Loaded ' + tracks.length + ' WAVs from ' + loadedFolder + '. Check names before searching.';
    } catch (error) { el('datasetLyricsStatus').textContent = error.message; }
    finally { working = false; controls(); }
  };
})();


// Text-only structural annotation, using the existing Runner connection.
(() => {
  const el = id => document.getElementById(id);
  let tracks = [], folder = '', busy = false, stopped = false;
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const eligible = t => t.exists && !t.has_structure && !t.error;
  function controls() {
    const approved = el('datasetStructureConsent').checked;
    el('datasetStructureLoad').disabled = busy;
    el('datasetStructureRunner').disabled = busy;
    el('datasetStructureAll').disabled = busy || !approved || !tracks.some(eligible);
    el('datasetStructureApplyAll').disabled = busy || !tracks.some(t => t.suggestion && t.review.checked);
    el('datasetStructureReviewAll').disabled = busy || !tracks.some(t => t.suggestion && !t.review.checked);
    el('datasetStructureStop').disabled = !busy;
    for (const t of tracks) {
      t.generate.disabled = busy || !approved || !eligible(t);
      t.apply.disabled = busy || !t.suggestion || !t.review.checked;
      t.review.disabled = busy || !t.suggestion;
    }
  }
  function modelLabel() {
    el('datasetStructureModel').textContent = state.connection?.model
      ? 'Selected Runner: ' + state.connection.provider + ' / ' + state.connection.model
      : 'Choose a model in LLM Runner first.';
  }
  async function run(items, apply) {
    if (busy) return;
    if (!apply && !el('datasetStructureConsent').checked) return;
    if (!apply && !state.connection?.model) { openRunner(); return; }
    const connection = !apply ? {...state.connection} : null;
    busy = true; stopped = false; controls(); modelLabel();
    let completed = 0, failed = 0;
    try {
      for (const t of items) {
        if (stopped) break;
        t.feedback.textContent = apply ? 'Backing up and applying…' : 'Asking LLM Runner for section labels…';
        if (!apply) { t.suggestion = null; t.review.checked = false; }
        try {
          if (apply) {
            const result = await api('/api/dataset-structure/apply', {folder,filename:t.filename,
              lyrics_name:t.suggestion.lyrics_name,sha256:t.suggestion.sha256,sections:t.suggestion.sections});
            t.has_structure = true; t.suggestion = null; t.review.checked = false;
            t.feedback.textContent = 'Saved ' + result.filename + '. Original backup: ' + result.backup;
          } else {
            const result = await api('/api/dataset-structure/propose', {folder,filename:t.filename,
              artist:t.artist,title:t.title,connection});
            t.suggestion = result;
            t.before.value = result.before; t.after.value = result.after;
            t.feedback.textContent = result.sections.length + ' section labels suggested by ' + result.model + '. Original lyric lines preserved. Review before applying.';
          }
          completed++;
        } catch (error) { failed++; t.feedback.textContent = error.message; }
        el('datasetStructureStatus').textContent = completed + ' completed · ' + failed + ' failed.';
      }
    } finally {
      busy = false; controls();
      el('datasetStructureStatus').textContent = (stopped ? 'Stopped. ' : 'Finished. ') + completed + ' completed · ' + failed + ' failed.' +
        (apply ? ' Rescan the trainer to use changed lyrics.' : ' Files are unchanged until you apply reviewed suggestions.');
    }
  }
  function card(t) {
    const box = node('section', undefined, 'trainer-panel');
    box.append(node('h4', t.filename));
    t.feedback = node('p', t.error || (t.has_structure ? 'Already tagged — skipped.' : 'Ready: ' + t.lyrics_name), 'hint');
    const actions = node('div', undefined, 'row wrap');
    t.generate = node('button', 'Suggest structure', 'button subtle');
    t.apply = node('button', 'Apply reviewed structure', 'button primary');
    t.generate.onclick = () => run([t], false);
    t.apply.onclick = () => t.suggestion && t.review.checked ? run([t], true) : undefined;
    actions.append(t.generate, t.apply);
    const details = node('details'); details.append(node('summary', 'Compare original and proposed structure'));
    t.before = node('textarea'); t.before.readOnly = true; t.before.rows = 12;
    t.before.setAttribute('aria-label', 'Original lyrics: ' + t.filename);
    t.after = node('textarea'); t.after.readOnly = true; t.after.rows = 12;
    t.after.setAttribute('aria-label', 'Proposed structure: ' + t.filename);
    details.append(node('p','Original'), t.before, node('p','Proposed'), t.after);
    const label = node('label', undefined, 'check-label');
    t.review = node('input'); t.review.type = 'checkbox'; t.review.onchange = controls;
    label.append(t.review, node('span','I reviewed this proposed structure.'));
    box.append(t.feedback, actions, details, label);
    return box;
  }
  el('datasetStructureRunner').onclick = () => openRunner();
  el('datasetStructureTab').addEventListener('click', modelLabel);
  el('runnerDialog').addEventListener('close', modelLabel);
  el('datasetStructureConsent').onchange = controls;
  el('datasetStructureStop').onclick = () => { stopped = true; };
  el('datasetDialog').addEventListener('close', () => { stopped = true; });
  el('datasetStructureAll').onclick = () => run(tracks.filter(eligible), false);
  el('datasetStructureApplyAll').onclick = () => run(tracks.filter(t => t.suggestion && t.review.checked), true);
  el('datasetStructureReviewAll').onclick = () => {
    if (busy) return;
    let marked = 0;
    for (const t of tracks) {
      if (t.suggestion && !t.review.checked) { t.review.checked = true; marked++; }
    }
    controls();
    el('datasetStructureStatus').textContent = marked + ' suggestions marked reviewed. No files changed. Use Apply all reviewed suggestions to save.';
  };
  el('datasetStructureLoad').onclick = async () => {
    if (busy) return;
    busy = true; controls(); modelLabel();
    try {
      const result = await api('/api/dataset-structure/scan', {folder:el('datasetFolder').value,fallback_artist:el('datasetArtist').value});
      folder = result.folder; tracks = result.tracks;
      el('datasetStructureTracks').replaceChildren(...tracks.map(card));
      el('datasetStructureStatus').textContent = 'Loaded ' + tracks.length + ' tracks from ' + folder + '. ' + tracks.filter(eligible).length + ' need structure.';
    } catch (error) { el('datasetStructureStatus').textContent = error.message; }
    finally { busy = false; controls(); }
  };
})();
