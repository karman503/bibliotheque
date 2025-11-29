/* ===== INITIALISATION CORRIGÉE ===== */
document.addEventListener('DOMContentLoaded', function () {
    console.log('🚀 Initialisation des scripts...');

    // Désactiver certaines animations sur mobile
    if (window.innerWidth <= 768) {
        document.body.classList.add('reduced-motion');
    }

    initializeAboutPage();
    initializeScrollAnimations();
    initializeButtonLoaders();

    console.log('✅ Scripts initialisés avec succès');
});

/* ===== INITIALISATION DE LA PAGE À PROPOS ===== */
function initializeAboutPage() {
    // Animation des statistiques
    animateStatistics();

    // Animation des cartes au hover
    initializeCardAnimations();

    // Animation de la section hero
    initializeHeroAnimation();
}

/* ===== ANIMATION DES STATISTIQUES ===== */
function animateStatistics() {
    const statElements = document.querySelectorAll('.stat-number');

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const statElement = entry.target;
                const targetValue = parseInt(statElement.textContent.replace('+', ''));
                let currentValue = 0;
                const duration = 2000; // 2 seconds
                const increment = targetValue / (duration / 50);

                const timer = setInterval(() => {
                    currentValue += increment;
                    if (currentValue >= targetValue) {
                        currentValue = targetValue;
                        clearInterval(timer);
                        if (statElement.textContent.includes('+')) {
                            statElement.textContent = targetValue + '+';
                        } else {
                            statElement.textContent = Math.floor(currentValue);
                        }
                    } else {
                        statElement.textContent = Math.floor(currentValue);
                    }
                }, 50);

                observer.unobserve(statElement);
            }
        });
    }, { threshold: 0.5 });

    statElements.forEach(stat => observer.observe(stat));
}

/* ===== ANIMATIONS AU SCROLL ===== */
function initializeScrollAnimations() {
    const revealElements = document.querySelectorAll('.reveal-on-scroll');

    const scrollObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('revealed');

                // Animation en cascade pour les éléments enfants
                const staggerItems = entry.target.querySelectorAll('.stagger-item');
                staggerItems.forEach((item, index) => {
                    item.style.animationDelay = (index * 0.2) + 's';
                });
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    revealElements.forEach(element => {
        scrollObserver.observe(element);
    });
}

/* ===== ANIMATION DE LA SECTION HERO ===== */
function initializeHeroAnimation() {
    const heroTitle = document.querySelector('.about-hero h1');
    if (heroTitle) {
        heroTitle.style.animation = 'fadeInUp 1s ease-out';
    }

    const heroText = document.querySelector('.about-hero .lead');
    if (heroText) {
        heroText.style.animation = 'fadeInUp 1s ease-out 0.3s both';
    }
}

/* ===== ANIMATIONS DES CARTES ===== */
function initializeCardAnimations() {
    const cards = document.querySelectorAll('.about-values .card, .about-team .card');

    cards.forEach((card, index) => {
        card.style.animationDelay = (index * 0.1) + 's';
        card.classList.add('stagger-item');
    });
}

/* ===== GESTION DES BOUTONS ===== */
function initializeButtonLoaders() {
    const buttons = document.querySelectorAll('button[type="submit"], .btn[type="submit"]');
    buttons.forEach(button => {
        button.addEventListener('click', function (e) {
            const form = this.closest('form');
            const isFormValid = form ? form.checkValidity() : true;

            if (isFormValid && !this.classList.contains('loading')) {
                const originalText = this.innerHTML;
                this.setAttribute('data-original-text', originalText);

                this.classList.add('loading');
                this.disabled = true;

                this.innerHTML = '<span class="btn-text">Chargement...</span>';

                // Si le bouton est à l'intérieur d'un formulaire, soumettre explicitement
                if (form) {
                    // Empêcher le comportement par défaut pour éviter un double envoi
                    e.preventDefault();
                    // Laisser un petit délai pour que l'UI se rafraîchisse avant la soumission
                    setTimeout(() => form.submit(), 50);
                }

                // Fallback : annuler l'état "loading" au bout de 10s si rien ne se passe
                setTimeout(() => {
                    if (this.classList.contains('loading')) {
                        this.classList.remove('loading');
                        this.disabled = false;
                        this.innerHTML = originalText;
                    }
                }, 10000);
            }
        });
    });
}

/* ===== GESTION DU REDIMENSIONNEMENT ===== */
window.addEventListener('resize', function () {
    if (window.innerWidth <= 768 && !document.body.classList.contains('reduced-motion')) {
        document.body.classList.add('reduced-motion');
    } else if (window.innerWidth > 768 && document.body.classList.contains('reduced-motion')) {
        document.body.classList.remove('reduced-motion');
    }
});

/* ===== CSS POUR REDUCED MOTION ===== */
const reducedMotionStyle = document.createElement('style');
reducedMotionStyle.textContent = `
    .reduced-motion *,
    .reduced-motion *::before,
    .reduced-motion *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
`;
document.head.appendChild(reducedMotionStyle);

/* ===== FONCTIONS GLOBALES ===== */
window.App = {
    showFlashMessage: function (message, type = 'success') {
        const flash = document.createElement('div');
        flash.className = `alert alert-${type} alert-dismissible fade show`;
        flash.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        document.body.appendChild(flash);

        setTimeout(() => flash.remove(), 5000);
    },

    stopButtonLoading: function (button) {
        if (button && button.classList.contains('loading')) {
            const originalText = button.getAttribute('data-original-text') || button.textContent;
            button.classList.remove('loading');
            button.disabled = false;
            button.innerHTML = originalText;
        }
    }
};

/* ===== CORRECTION DES ICÔNES DES SERVICES ===== */
function initializeServiceIcons() {
    // Attendre que le DOM soit complètement chargé
    setTimeout(() => {
        const serviceIcons = document.querySelectorAll('.bg-primary.bg-opacity-10, .bg-success.bg-opacity-10, .bg-purple.bg-opacity-10');
        
        serviceIcons.forEach(icon => {
            // Forcer les styles CSS
            icon.style.backgroundColor = getComputedStyle(icon).backgroundColor;
            icon.style.width = '80px';
            icon.style.height = '80px';
            icon.style.borderRadius = '50%';
            icon.style.display = 'flex';
            icon.style.alignItems = 'center';
            icon.style.justifyContent = 'center';
            icon.style.margin = '0 auto 1.5rem auto';
            icon.style.opacity = '1';
        });
        
        console.log('✅ Icônes des services initialisées:', serviceIcons.length);
    }, 100);
}

// Modifiez la fonction DOMContentLoaded existante :
document.addEventListener('DOMContentLoaded', function () {
    console.log('🚀 Initialisation des scripts...');

    // Désactiver certaines animations sur mobile
    if (window.innerWidth <= 768) {
        document.body.classList.add('reduced-motion');
    }

    initializeAboutPage();
    initializeScrollAnimations();
    initializeButtonLoaders();
    initializeServiceIcons(); // ← AJOUTEZ CETTE LIGNE

    console.log('✅ Scripts initialisés avec succès');
});
/* ===== CORRECTION DES ICÔNES DU DASHBOARD ===== */
function initializeDashboardIcons() {
    // Attendre que le DOM soit complètement chargé
    setTimeout(() => {
        const dashboardIcons = document.querySelectorAll('.bg-primary.bg-opacity-10, .bg-success.bg-opacity-10, .bg-warning.bg-opacity-10, .bg-danger.bg-opacity-10');
        
        dashboardIcons.forEach(icon => {
            // Forcer les styles CSS pour les icônes du dashboard
            icon.style.opacity = '1';
            icon.style.width = '60px';
            icon.style.height = '60px';
            icon.style.borderRadius = '50%';
            icon.style.display = 'flex';
            icon.style.alignItems = 'center';
            icon.style.justifyContent = 'center';
            
            // Appliquer la couleur de fond selon la classe
            if (icon.classList.contains('bg-primary')) {
                icon.style.backgroundColor = 'rgba(99, 102, 241, 0.15)';
            } else if (icon.classList.contains('bg-success')) {
                icon.style.backgroundColor = 'rgba(16, 185, 129, 0.15)';
            } else if (icon.classList.contains('bg-warning')) {
                icon.style.backgroundColor = 'rgba(245, 158, 11, 0.15)';
            } else if (icon.classList.contains('bg-danger')) {
                icon.style.backgroundColor = 'rgba(239, 68, 68, 0.15)';
            }
        });
        
        console.log('✅ Icônes du dashboard initialisées:', dashboardIcons.length);
    }, 100);
}

// Ajoutez cette ligne dans votre DOMContentLoaded existant :
document.addEventListener('DOMContentLoaded', function () {
    console.log('🚀 Initialisation des scripts...');

    // Désactiver certaines animations sur mobile
    if (window.innerWidth <= 768) {
        document.body.classList.add('reduced-motion');
    }

    initializeAboutPage();
    initializeScrollAnimations();
    initializeButtonLoaders();
    initializeServiceIcons();
    initializeDashboardIcons(); // ← AJOUTEZ CETTE LIGNE

    console.log('✅ Scripts initialisés avec succès');
});
/* ===== CORRECTION ALIGNEMENT STATISTIQUES ===== */
function fixStatsAlignment() {
    setTimeout(() => {
        // Sélectionner toutes les cartes de statistiques
        const statCards = document.querySelectorAll('.card.border.shadow-sm');
        
        statCards.forEach(card => {
            // Forcer l'alignement au centre
            card.style.display = 'flex';
            card.style.flexDirection = 'column';
            card.style.alignItems = 'center';
            card.style.justifyContent = 'center';
            card.style.textAlign = 'center';
            
            // Forcer l'alignement du body de la carte
            const cardBody = card.querySelector('.card-body');
            if (cardBody) {
                cardBody.style.display = 'flex';
                cardBody.style.flexDirection = 'column';
                cardBody.style.alignItems = 'center';
                cardBody.style.justifyContent = 'center';
                cardBody.style.textAlign = 'center';
                cardBody.style.width = '100%';
            }
            
            // Forcer l'alignement des éléments flex à l'intérieur
            const flexItems = card.querySelectorAll('.d-flex');
            flexItems.forEach(item => {
                item.style.justifyContent = 'center';
                item.style.width = '100%';
            });
        });
        
        console.log('✅ Alignement des statistiques corrigé');
    }, 150);
}

// Ajoutez dans votre DOMContentLoaded :
document.addEventListener('DOMContentLoaded', function () {
    // ... vos autres initialisations ...
    fixStatsAlignment(); // ← AJOUTEZ CETTE LIGNE
});
