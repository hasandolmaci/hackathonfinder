// Phones: collapse the sidebar filters behind a "Filters (n)" button so results come first.
const sidebar = document.querySelector('.sidebar');
if (sidebar) {
  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'filters-toggle';
  button.className = 'filters-toggle';
  button.setAttribute('aria-expanded', 'false');
  sidebar.id ||= 'filter-sidebar';
  button.setAttribute('aria-controls', sidebar.id);
  const brand = sidebar.querySelector('.brand');
  (brand ? brand.nextSibling : sidebar.firstChild) ? sidebar.insertBefore(button, brand ? brand.nextSibling : sidebar.firstChild) : sidebar.append(button);

  // Active = anything that differs from the default view (next 7 days, hackathons only).
  const activeCount = () => {
    const p = new URLSearchParams(location.search);
    const list = key => (p.get(key) || '').split(',').filter(Boolean);
    let n = list('region').length + list('country').length + list('categories').length + list('types').length;
    if (p.get('format')) n += 1;
    if (Number(p.get('min_score') || 0) > 0) n += 1;
    const kinds = list('kinds');
    if (kinds.length && !(kinds.length === 1 && kinds[0] === 'hackathon')) n += 1;
    return n;
  };
  const label = () => {
    const n = activeCount(), open = sidebar.classList.contains('filters-open');
    button.textContent = `${open ? 'Hide filters' : 'Filters'}${n ? ` (${n})` : ''}`;
  };
  button.addEventListener('click', () => {
    const open = sidebar.classList.toggle('filters-open');
    button.setAttribute('aria-expanded', String(open));
    label();
  });
  // list.js rewrites the URL after each filter change; refresh the count right after.
  ['change', 'click', 'input'].forEach(type => sidebar.addEventListener(type, () => setTimeout(label, 0)));
  document.addEventListener('click', () => setTimeout(label, 0));
  window.addEventListener('popstate', label);
  label();
}
