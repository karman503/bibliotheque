// static/js/stats.js - Client-side statistics manager
(function () {
    'use strict';

    class StatsManager {
        constructor() {
            this.storageKey = 'bibliotheque_stats_v1';
            this.defaults = {
                categories: [
                    { categorie: 'Littérature', count: 0, pourcentage: 0, couleur: '#007bff' },
                    { categorie: 'Sciences', count: 0, pourcentage: 0, couleur: '#28a745' },
                    { categorie: 'Histoire', count: 0, pourcentage: 0, couleur: '#ffc107' },
                    { categorie: 'Fantasy', count: 0, pourcentage: 0, couleur: '#6f42c1' },
                    { categorie: 'Science-Fiction', count: 0, pourcentage: 0, couleur: '#dc3545' },
                    { categorie: 'Philosophie', count: 0, pourcentage: 0, couleur: '#6c757d' }
                ],
                days: [],
                top_books: [],
                livres_disponibles: 0,
                livres_empruntes: 0,
                livres_reserves: 0,
                total_livres: 0
            };

            // Populate last 7 days
            for (let i = 6; i >= 0; i--) {
                const d = new Date();
                d.setDate(d.getDate() - i);
                const label = d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
                this.defaults.days.push({
                    label: label,
                    bars: [{ width: 0, count: 0, color: '#007bff' }]
                });
            }

            this.state = this.load();
            this.init();
        }

        load() {
            try {
                const raw = localStorage.getItem(this.storageKey);
                if (raw) {
                    return JSON.parse(raw);
                }
            } catch (e) {
                console.error('Error loading stats:', e);
            }
            return JSON.parse(JSON.stringify(this.defaults));
        }

        save() {
            try {
                localStorage.setItem(this.storageKey, JSON.stringify(this.state));
            } catch (e) {
                console.error('Error saving stats:', e);
            }
        }

        init() {
            this.animateProgressBars();
            this.setupEventListeners();
        }

        animateProgressBars() {
            const bars = document.querySelectorAll('.stat-percentage');
            bars.forEach(bar => {
                const percentage = bar.dataset.percentage || '0';
                const color = bar.dataset.color || '';

                bar.style.width = '0';

                if (color && color !== 'undefined') {
                    bar.style.backgroundColor = color;
                }

                setTimeout(() => {
                    let widthValue = percentage;
                    if (percentage && !percentage.includes('%')) {
                        widthValue = percentage + '%';
                    }
                    bar.style.width = widthValue;
                    bar.style.transition = 'width 1s ease-in-out';
                }, 100);
            });
        }

        setupEventListeners() {
            // Period buttons
            const periodButtons = document.querySelectorAll('[data-period]');
            const periodInput = document.getElementById('periodInput');

            if (periodButtons.length && periodInput) {
                const current = periodInput.value || 'month';

                periodButtons.forEach(btn => {
                    if (btn.getAttribute('data-period') === current) {
                        btn.classList.remove('btn-outline-secondary');
                        btn.classList.add('btn-primary');
                    }

                    btn.addEventListener('click', () => {
                        periodInput.value = btn.getAttribute('data-period');
                        document.getElementById('periodeForm').submit();
                    });
                });
            }
        }

        recordBorrow(options = {}) {
            const { categorie = null, book = null, date = null } = options;
            const borrowDate = date ? new Date(date) : new Date();

            // Update counters
            this.state.livres_empruntes = (this.state.livres_empruntes || 0) + 1;

            // Update category
            if (categorie) {
                const cat = this.state.categories.find(c => c.categorie === categorie);
                if (cat) {
                    cat.count = (cat.count || 0) + 1;
                } else {
                    this.state.categories.push({
                        categorie: categorie,
                        count: 1,
                        pourcentage: 0,
                        couleur: '#007bff'
                    });
                }
            }

            // Update book
            if (book && book.titre) {
                let existingBook = this.state.top_books.find(b => b.titre === book.titre);
                if (existingBook) {
                    existingBook.count = (existingBook.count || 0) + 1;
                } else {
                    this.state.top_books.unshift({
                        titre: book.titre,
                        auteur: book.auteur || '',
                        count: 1
                    });
                }

                // Keep only top 10 books
                this.state.top_books = this.state.top_books
                    .sort((a, b) => b.count - a.count)
                    .slice(0, 10);
            }

            // Update day
            const label = borrowDate.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' });
            let day = this.state.days.find(d => d.label === label);

            if (!day) {
                this.state.days.push({
                    label: label,
                    bars: [{ width: 0, count: 0, color: '#007bff' }]
                });

                // Keep only last 30 days
                if (this.state.days.length > 30) {
                    this.state.days.shift();
                }

                day = this.state.days.find(d => d.label === label);
            }

            day.bars[0].count = (day.bars[0].count || 0) + 1;

            // Recalculate percentages
            const totalCat = this.state.categories.reduce((sum, c) => sum + (c.count || 0), 0);
            this.state.categories.forEach(c => {
                c.pourcentage = totalCat > 0 ? Math.round((c.count || 0) / totalCat * 100) : 0;
            });

            // Update bar widths
            this.state.days.forEach(d => {
                d.bars.forEach(b => {
                    b.width = b.count ? Math.min(100, Math.round(b.count / 10 * 100)) : 0;
                });
            });

            this.save();
        }

        reset() {
            if (confirm('Voulez-vous vraiment réinitialiser toutes les statistiques?')) {
                this.state = JSON.parse(JSON.stringify(this.defaults));
                this.save();
                location.reload();
            }
        }
    }

    // Expose to global scope
    window.StatsManager = StatsManager;

    // Auto-initialize
    document.addEventListener('DOMContentLoaded', () => {
        window.statsManager = new StatsManager();
    });
})();