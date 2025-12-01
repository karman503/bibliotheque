// init-notifications.js
document.addEventListener('DOMContentLoaded', function () {
    // Attendre que Bootstrap soit complètement chargé
    setTimeout(() => {
        // Vérifier si l'utilisateur est connecté
        const isLoggedIn = document.body.classList.contains('has-sidebar') ||
            document.querySelector('.navbar-nav .dropdown-menu');

        if (isLoggedIn) {
            console.log('Initialisation du système de notifications...');

            // Récupérer les infos utilisateur
            const userRole = getCurrentUserRole();
            const userName = getCurrentUserName();

            if (userName) {
                // ID temporaire basé sur le nom
                const userId = hashCode(userName);

                const userData = {
                    id: userId,
                    role: userRole,
                    name: userName
                };

                // Initialiser le gestionnaire
                if (typeof NotificationManager !== 'undefined') {
                    window.notificationManager = new NotificationManager(userData);

                    // Ajouter un écouteur pour le bouton de démo
                    const demoBtn = document.getElementById('demoNotificationBtn');
                    if (demoBtn) {
                        demoBtn.addEventListener('click', function () {
                            if (window.notificationManager) {
                                window.notificationManager.addNotification({
                                    type: 'info',
                                    title: 'Notification de démonstration',
                                    message: 'Ceci est une notification de test du système',
                                    category: 'demo'
                                });
                            }
                        });
                    }
                }
            }
        }
    }, 1000);

    // Fonctions utilitaires
    function getCurrentUserRole() {
        const roleElements = [
            document.querySelector('.sidebar small.text-white-50'),
            document.querySelector('.dropdown-menu .text-muted')
        ];

        for (const element of roleElements) {
            if (element) {
                const text = element.textContent.toLowerCase();
                if (text.includes('admin')) return 'admin';
                if (text.includes('bibliothécaire') || text.includes('bibliothecaire')) return 'bibliothecaire';
            }
        }
        return 'user';
    }

    function getCurrentUserName() {
        const nameElements = [
            document.querySelector('.sidebar h6.fw-bold'),
            document.querySelector('.navbar .dropdown-toggle span')
        ];

        for (const element of nameElements) {
            if (element) {
                return element.textContent.trim();
            }
        }
        return 'Utilisateur';
    }

    function hashCode(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return Math.abs(hash);
    }
});