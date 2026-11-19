const $ = (id) => document.getElementById(id);
const text = (tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};
let libraryLoaded = false;
let querying = false;

async function showView(name) {
  const library = name === 'library';
  $('ask-view').hidden = library;
  $('library-view').hidden = !library;
  $('breadcrumb').textContent = library ? 'Document library' : 'Ask Atlas';
  for (const [id, active] of [['ask-nav', !library], ['library-nav', library]]) {
    $(id).classList.toggle('active', active);
    if (active) $(id).setAttribute('aria-current', 'page');
    else $(id).removeAttribute('aria-current');
  }
  if (!library || libraryLoaded) return;
  $('document-list').replaceChildren(text('p', 'Loading the reference library…'));
  try {
    const response = await fetch('/library');
    if (!response.ok) throw new Error('Could not load the library. Select Document library to retry.');
    const { documents } = await response.json();
    $('document-list').replaceChildren();
    documents.forEach((doc, i) => {
      const detail = document.createElement('details');
      detail.className = 'document';
      const summary = text('summary', doc.title);
      summary.append(text('small', doc.source));
      detail.append(summary, text('pre', doc.content));
      $('document-list').append(detail);
    });
    libraryLoaded = true;
  } catch (error) {
    $('document-list').replaceChildren(text('p', error.message));
  }
}

$('ask-nav').addEventListener('click', () => showView('ask'));
$('library-nav').addEventListener('click', () => showView('library'));
$('browse-library').addEventListener('click', () => { showView('library'); window.scrollTo({ top: 0, behavior: 'smooth' }); });

async function ask() {
  if (querying) return;
  const question = $('question').value.trim();
  if (!question) { $('query-status').textContent = 'Enter a question to search the documents.'; $('question').focus(); return; }
  querying = true;
  $('submit-question').disabled = true;
  $('question-form').setAttribute('aria-busy', 'true');
  $('query-status').textContent = 'Searching the maintenance references…';
  $('answer-section').hidden = true;
  try {
    const response = await fetch('/query', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, top_k: 4 }), signal: AbortSignal.timeout(30000),
    });
    if (!response.ok) throw new Error(response.status === 401 ? 'This deployment requires an API token. The public demo is temporarily unavailable.' : 'The service could not answer. Please try again.');
    const result = await response.json();
    $('answered-question').textContent = question;
    $('answer-text').textContent = result.answer;
    $('answer-kind').textContent = result.sources.length ? 'Source found' : 'No supporting source';
    $('sources').replaceChildren();
    for (const source of result.sources) {
      const detail = document.createElement('details');
      detail.className = 'source';
      detail.append(text('summary', `  ${source.title} · view supporting passage`));
      detail.append(text('pre', source.content || 'Passage content is not available.'));
      detail.append(text('small', `${source.source} · ${source.id}`));
      $('sources').append(detail);
    }
    const m = result.metadata;
    $('answer-meta').textContent = `Local TF-IDF · Extractive answer · ${Math.max(1, Math.round(m.latency_ms))} ms server processing · ${result.sources.length} source${result.sources.length === 1 ? '' : 's'}`;
    $('answer-section').hidden = false;
    $('query-status').textContent = result.sources.length ? 'Answer ready. Review the supporting passage below.' : 'The documents do not support an answer to this question.';
  } catch (error) {
    $('query-status').textContent = error.name === 'TimeoutError' ? 'The service took too long. Please try again.' : error.message;
  } finally {
    querying = false;
    $('submit-question').disabled = false;
    $('question-form').removeAttribute('aria-busy');
  }
}
$('question-form').addEventListener('submit', (event) => { event.preventDefault(); ask(); });
document.querySelectorAll('[data-question]').forEach((button) => {
  button.addEventListener('click', () => { $('question').value = button.dataset.question; ask(); });
});
fetch('/health').then((response) => {
  if (!response.ok) throw new Error();
  return response.json();
}).then((health) => {
  if (!health.ok || health.backend !== 'local') throw new Error();
  $('service-status').textContent = 'Local engine ready';
}).catch(() => {
  $('service-status').textContent = 'Service unavailable';
  $('service-status').classList.add('error');
});
