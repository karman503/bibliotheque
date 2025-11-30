// stats.js - client-side stats manager
(function () {
    class StatsManager {
        constructor() {
            this.storageKey = 'bibliotheque_stats_v1';
            this.defaults = {
                categories: [
                    { categorie: 'Littérature', count: 0, pourcentage: 0, couleur: 'var(--primary)' },
                    { categorie: 'Sciences', count: 0, pourcentage: 0, couleur: 'var(--success)' },
                    { categorie: 'Histoire', count: 0, pourcentage: 0, couleur: 'var(--warning)' },
                    { categorie: 'Fantasy', count: 0, pourcentage: 0, couleur: 'var(--purple)' },
                    { categorie: 'Science-Fiction', count: 0, pourcentage: 0, couleur: 'var(--danger)' },
                    { categorie: 'Philosophie', count: 0, pourcentage: 0, couleur: 'var(--gray)' }
                ],
                days: [
                    // default last 7 days
                ],
                top_books: [],
                livres_disponibles: 0,
                livres_empruntes: 0,
                livres_reserves: 0,
                total_livres: 0
            };

            // populate last 7 days labels
            for (let i = 6; i >= 0; i--) {
                const d = new Date();
                d.setDate(d.getDate() - i);
                const label = d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
                this.defaults.days.push({ label: label, bars: [{ width: 0, count: 0, color: 'var(--primary)' }] });
            }

            this.state = this.load();
            this.initDOM();
        }

        load() {
            // Prefer server stats if provided, else localStorage, else defaults
            try {
                const srv = window.SERVER_STATS || null;
                if (srv) {
                    // normalize server object: fill missing keys with defaults
                    const merged = Object.assign({}, this.defaults, {});
                    if (Array.isArray(srv.categories)) merged.categories = srv.categories.map((c, idx) => Object.assign({}, this.defaults.categories[idx] || {}, c));
                    if (Array.isArray(srv.days)) merged.days = srv.days;
                    if (Array.isArray(srv.top_books)) merged.top_books = srv.top_books;
                    merged.livres_disponibles = srv.livres_disponibles ?? this.defaults.livres_disponibles;
                    merged.livres_empruntes = srv.livres_empruntes ?? this.defaults.livres_empruntes;
                    merged.livres_reserves = srv.livres_reserves ?? this.defaults.livres_reserves;
                    merged.total_livres = srv.total_livres ?? this.defaults.total_livres;
                    // persist as base
                    localStorage.setItem(this.storageKey, JSON.stringify(merged));
                    return merged;
                }

                const raw = localStorage.getItem(this.storageKey);
                if (raw) return JSON.parse(raw);
            } catch (e) {
                console.error('Error loading stats', e);
            }
            // fallback
            localStorage.setItem(this.storageKey, JSON.stringify(this.defaults));
            return JSON.parse(JSON.stringify(this.defaults));
        }

        save() {
            localStorage.setItem(this.storageKey, JSON.stringify(this.state));
        }

        initDOM() {
            // Update categories
            const container = document.querySelector('.card-body h3:contains("Répartition par catégorie")') || null;
            // We'll target by known structure: find the first card body with that heading text
            const nodes = document.querySelectorAll('.card-body');
            let catCard = null;
            nodes.forEach(nb => {
                const h = nb.querySelector('h3.h5');
                if (h && h.textContent.trim().startsWith('Répartition')) catCard = nb;
            });
            if (catCard) {
                // build inner HTML from state.categories
                const listHtml = this.state.categories.map(stat => {
                    const pct = stat.pourcentage ?? (this.state.total_livres > 0 ? Math.round(stat.count / this.state.total_livres * 100) : 0);
                    return `
<div class="mb-3">
  <div class="d-flex justify-content-between align-items-center mb-1">
    <div class="d-flex align-items-center gap-2">
      <div class="rounded-circle" style="width:16px;height:16px;background-color: ${stat.couleur};"></div>
      <span class="small text-secondary mb-0">${stat.categorie}</span>
    </div>
    <div class="text-end">
      <span class="fw-medium" data-stat-count="${stat.categorie}">${stat.count}</span>
      <span class="small text-muted ms-2">(${pct}%)</span>
    </div>
  </div>
  <div class="progress" style="height:8px;">
    <div class="progress-bar" role="progressbar" style="width:${pct}%; background-color:${stat.couleur};"></div>
  </div>
</div>`;
                }).join('\n');
                // replace existing inner content (keep the h3)
                const heading = catCard.querySelector('h3.h5');
                // remove all siblings after heading
                let sib = heading.nextElementSibling;
                while (sib) { const rem = sib; sib = sib.nextElementSibling; rem.remove(); }
                // insert generated HTML
                heading.insertAdjacentHTML('afterend', listHtml);
            }

            // Update days
            let dayCard = null;
            nodes.forEach(nb => {
                const h = nb.querySelector('h5.fw-semibold');
                if (h && h.textContent.trim().startsWith('Emprunts par')) dayCard = nb;
            });
            if (dayCard) {
                const heading = dayCard.querySelector('h5.fw-semibold');
                // remove old lines after heading
                let sib = heading.nextElementSibling;
                while (sib) { const rem = sib; sib = sib.nextElementSibling; rem.remove(); }
                // insert dynamic days
                const daysHtml = this.state.days.map(d => {
                    const barsHtml = d.bars.map((bar, i) => `
<div class="progress ${i > 0 ? 'mt-1' : ''}">
  <div class="progress-bar" role="progressbar" style="width:${bar.width}%; background-color:${bar.color};">${bar.count}</div>
</div>`).join('\n');
                    return `<div class="mb-2 d-flex justify-content-between align-items-center">
  <span>${d.label}</span>
  <div class="flex-grow-1 mx-2">${barsHtml}</div>
</div>`;
                }).join('\n');
                heading.insertAdjacentHTML('afterend', daysHtml);
            }

            // Update top books card
            let booksCard = null;
            nodes.forEach(nb => {
                const h = nb.querySelector('h3.h5');
                if (h && h.textContent.trim().startsWith('Livres les plus')) booksCard = nb;
            });
            if (booksCard) {
                const heading = booksCard.querySelector('h3.h5');
                // remove old content after heading
                let sib = heading.nextElementSibling;
                while (sib) { const rem = sib; sib = sib.nextElementSibling; rem.remove(); }
                const books = this.state.top_books.length ? this.state.top_books : [];
                let booksHtml = '';
                if (books.length === 0) {
                    booksHtml = `<div class="d-flex justify-content-between align-items-center p-3 rounded-3 mb-2 hover-overlay">
  <div class="d-flex align-items-center gap-3">
    <div class="bg-primary bg-opacity-10 text-primary rounded-circle d-flex align-items-center justify-content-center" style="width:32px;height:32px;"><span class="fw-bold small">#1</span></div>
    <div><p class="mb-0 fw-medium text-dark">Aucun livre</p><p class="mb-0 small text-secondary">--</p></div>
  </div>
  <div class="text-end"><p class="mb-0 fw-bold text-dark">0</p><p class="mb-0 small text-muted">emprunts</p></div>
</div>`;
                } else {
                    booksHtml = books.slice(0, 5).map((book, i) => `
<div class="d-flex justify-content-between align-items-center p-3 rounded-3 mb-2 hover-overlay">
  <div class="d-flex align-items-center gap-3">
    <div class="bg-primary bg-opacity-10 text-primary rounded-circle d-flex align-items-center justify-content-center" style="width:32px;height:32px;"><span class="fw-bold small">#${i + 1}</span></div>
    <div><p class="mb-0 fw-medium text-dark">${book.titre}</p><p class="mb-0 small text-secondary">${book.auteur || book.author || ''}</p></div>
  </div>
  <div class="text-end"><p class="mb-0 fw-bold text-dark">${book.count || book.emprunts || 0}</p><p class="mb-0 small text-muted">emprunts</p></div>
</div>`).join('\n');
                }
                heading.insertAdjacentHTML('afterend', booksHtml);
            }

            // Update collection state numbers if present in page
            const disponEl = document.querySelector('.card-body .fw-bold'); // coarse selection; we keep the dynamic values already printed by Jinja
            // We won't override those printed values unless they are missing
        }

        // Public API: record a borrow action
        recordBorrow({ categorie = null, book = null, date = null } = {}) {
            // increment total, category and book
            date = date ? new Date(date) : new Date();
            // update total counters
            this.state.livres_empruntes = (this.state.livres_empruntes || 0) + 1;
            this.state.total_livres = this.state.total_livres || (this.state.livres_empruntes + (this.state.livres_disponibles || 0) + (this.state.livres_reserves || 0));
            if (categorie) {
                const cat = this.state.categories.find(c => c.categorie === categorie);
                if (cat) cat.count = (cat.count || 0) + 1;
                else this.state.categories.push({ categorie: categorie, count: 1, pourcentage: 0, couleur: 'var(--primary)' });
            }
            if (book) {
                let b = this.state.top_books.find(x => x.id === book.id || x.titre === book.titre);
                if (b) b.count = (b.count || b.emprunts || 0) + 1;
                else this.state.top_books.unshift({ titre: book.titre || book.name, auteur: book.auteur || book.author || '', count: 1, id: book.id });
            }
            // update day slot (match today's label)
            const label = date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
            let day = this.state.days.find(d => d.label === label);
            if (!day) {
                // push new day at end and drop oldest to keep length reasonable
                this.state.days.push({ label: label, bars: [{ width: 0, count: 0, color: 'var(--primary)' }] });
                if (this.state.days.length > 30) this.state.days.shift();
                day = this.state.days.find(d => d.label === label);
            }
            day.bars[0].count = (day.bars[0].count || 0) + 1;

            // Recompute percentages
            const totalCat = this.state.categories.reduce((s, c) => s + (c.count || 0), 0) || 0;
            this.state.categories.forEach(c => { c.pourcentage = totalCat > 0 ? Math.round((c.count || 0) / totalCat * 100) : 0; });

            // map counts to widths for day bars and categories
            this.state.days.forEach(d => { d.bars.forEach(b => { b.width = b.count ? Math.min(100, Math.round(b.count / 1 * 100)) : 0; }); });
            this.state.categories.forEach(c => { /* keep pourcentage as is */ });

            this.save();
            this.initDOM();
        }

        // Expose helper to reset stats
        reset() {
            this.state = JSON.parse(JSON.stringify(this.defaults));
            this.save();
            this.initDOM();
        }
    }

    // create and expose
    const manager = new StatsManager();
    window.statsManager = manager;
})();
