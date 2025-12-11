// OSA Coordinator Dashboard Enhancements
// - Client-side search filtering (name or ID)
// - Clickable student rows linking to detail page
// - Accessible announcements (ARIA live region) for search results count

(function(){
  const input = document.getElementById('studentSearchInput');
  const table = document.getElementById('studentsTable');
  const liveRegion = document.createElement('div');
  liveRegion.setAttribute('aria-live','polite');
  liveRegion.style.position='absolute';
  liveRegion.style.left='-9999px';
  document.body.appendChild(liveRegion);

  if(!input || !table) return;

  const normalize = (s) => (s||'').toString().toLowerCase().trim();
  const getRows = () => Array.from(table.querySelectorAll('tbody tr'));

  function applyFilter(){
    const q = normalize(input.value);
    let visible = 0;
    getRows().forEach(tr => {
      // Skip rows that are structural (could add a class to exclude if needed)
      const cells = Array.from(tr.cells).map(td => normalize(td.textContent));
      const hit = q === '' || cells.some(text => text.includes(q));
      tr.style.display = hit ? '' : 'none';
      if(hit) visible++;
    });
    liveRegion.textContent = q ? `Filtered to ${visible} matching students.` : '';
  }

  input.addEventListener('input', applyFilter);

  // Row click navigation
  getRows().forEach(tr => {
    const href = tr.getAttribute('data-href');
    if(!href) return;
    tr.addEventListener('click', () => { window.location.href = href; });
    tr.addEventListener('keydown', (e) => {
      if(e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.location.href = href;
      }
    });
    tr.setAttribute('tabindex','0'); // make row focusable for keyboard navigation
    tr.setAttribute('role','link');
    tr.setAttribute('aria-label', 'View details for ' + (tr.cells[1]?.textContent || 'student'));
  });
})();
