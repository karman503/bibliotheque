// notification.js - Système de notifications dynamique et persistant
class NotificationManager {
    constructor(userData = null) {
        this.currentUser = userData;
        this.notifications = [];
        this.isInitialized = false;
        this.init();
    }

    async init() {
        if (!this.currentUser) {
            console.log('NotificationManager: Aucun utilisateur connecté');
            return;
        }

        console.log('NotificationManager: Initialisation pour', this.currentUser.name);

        // Charger les notifications
        await this.loadNotifications();

        // Mettre à jour l'interface
        this.updateNotificationCount();
        this.renderNotifications();

        // Configurer les événements
        this.setupEventListeners();

        // Charger les notifications API
        await this.loadNotificationsFromAPI();

        this.isInitialized = true;
        console.log('NotificationManager: Initialisation terminée');
    }

    async loadNotifications() {
        try {
            const stored = localStorage.getItem(`notifications_${this.currentUser.id}`);
            if (stored) {
                this.notifications = JSON.parse(stored).map(n => ({
                    ...n,
                    time: new Date(n.time)
                }));
                console.log('Notifications chargées:', this.notifications.length);
            } else {
                // Créer des notifications par défaut
                this.createDefaultNotifications();
            }
        } catch (error) {
            console.error('Erreur chargement notifications:', error);
            this.createDefaultNotifications();
        }
    }

    createDefaultNotifications() {
        this.notifications = [
            {
                id: Date.now(),
                type: 'success',
                title: 'Bienvenue sur BibliosDjib',
                message: 'Votre compte a été créé avec succès',
                time: new Date(),
                read: false,
                category: 'welcome'
            }
        ];

        if (this.currentUser.role === 'admin') {
            this.notifications.push({
                id: Date.now() + 1,
                type: 'system',
                title: 'Accès Administrateur',
                message: 'Vous avez accès au panel d\'administration',
                time: new Date(),
                read: false,
                category: 'system'
            });
        }

        this.saveNotifications();
    }

    saveNotifications() {
        if (!this.currentUser) return;
        localStorage.setItem(`notifications_${this.currentUser.id}`, JSON.stringify(this.notifications));
    }

    async loadNotificationsFromAPI() {
        try {
            const response = await fetch('/api/notifications');
            if (response.ok) {
                const apiNotifications = await response.json();
                this.mergeAPINotifications(apiNotifications);
            }
        } catch (error) {
            console.log('Notifications API non disponible:', error);
        }
    }

    mergeAPINotifications(apiNotifications) {
        let newNotifications = 0;

        apiNotifications.forEach(apiNotif => {
            const exists = this.notifications.find(n => n.id === apiNotif.id);
            if (!exists) {
                this.notifications.unshift({
                    ...apiNotif,
                    time: new Date(apiNotif.time)
                });
                newNotifications++;
            }
        });

        if (newNotifications > 0) {
            this.saveNotifications();
            this.updateNotificationCount();
            this.renderNotifications();
            this.animateNewNotifications(newNotifications);
        }
    }

    addNotification(notificationData) {
        const newNotification = {
            id: Date.now(),
            type: notificationData.type || 'info',
            title: notificationData.title,
            message: notificationData.message,
            time: new Date(),
            read: false,
            category: notificationData.category || 'general',
            action: notificationData.action || null,
            priority: notificationData.priority || 'normal'
        };

        this.notifications.unshift(newNotification);
        this.saveNotifications();
        this.updateNotificationCount();
        this.renderNotifications();
        this.animateNewNotification();

        return newNotification.id;
    }

    markAsRead(notificationId) {
        const notification = this.notifications.find(n => n.id == notificationId);
        if (notification && !notification.read) {
            notification.read = true;
            this.saveNotifications();
            this.updateNotificationCount();

            // Mettre à jour l'élément visuellement
            const item = document.querySelector(`.notification-item[data-id="${notificationId}"]`);
            if (item) {
                item.classList.remove('unread');
                item.querySelector('.notification-actions')?.remove();

                // Animation de lecture
                item.style.opacity = '0.7';
                item.style.transform = 'translateX(-10px)';
                setTimeout(() => {
                    item.style.opacity = '';
                    item.style.transform = '';
                }, 300);
            }

            // Envoyer à l'API
            this.markAsReadAPI(notificationId);

            return true;
        }
        return false;
    }

    async markAsReadAPI(notificationId) {
        try {
            await fetch(`/api/notifications/${notificationId}/read`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (error) {
            console.log('Erreur API marquage comme lu:', error);
        }
    }

    markAllAsRead() {
        let hasUnread = false;

        this.notifications.forEach(notification => {
            if (!notification.read) {
                notification.read = true;
                hasUnread = true;
            }
        });

        if (hasUnread) {
            this.saveNotifications();
            this.updateNotificationCount();
            this.renderNotifications();

            // Envoyer à l'API
            this.markAllAsReadAPI();

            return true;
        }
        return false;
    }

    async markAllAsReadAPI() {
        try {
            await fetch('/api/notifications/read-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (error) {
            console.log('Erreur API marquage tous comme lu:', error);
        }
    }

    deleteNotification(notificationId) {
        const index = this.notifications.findIndex(n => n.id == notificationId);
        if (index !== -1) {
            // Animation de suppression
            const item = document.querySelector(`.notification-item[data-id="${notificationId}"]`);
            if (item) {
                item.style.transition = 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)';
                item.style.opacity = '0';
                item.style.transform = 'translateX(100px) scale(0.8)';

                setTimeout(() => {
                    this.notifications.splice(index, 1);
                    this.saveNotifications();
                    this.updateNotificationCount();
                    this.renderNotifications();
                }, 400);
            } else {
                this.notifications.splice(index, 1);
                this.saveNotifications();
                this.updateNotificationCount();
                this.renderNotifications();
            }

            return true;
        }
        return false;
    }

    updateNotificationCount() {
        const unreadCount = this.notifications.filter(n => !n.read).length;
        const countElement = document.getElementById('notificationCount');

        if (countElement) {
            if (unreadCount > 0) {
                countElement.textContent = unreadCount > 99 ? '99+' : unreadCount;
                countElement.style.display = 'flex';

                // Animation
                if (!countElement.classList.contains('notification-pulse')) {
                    countElement.classList.add('notification-pulse');
                    setTimeout(() => {
                        countElement.classList.remove('notification-pulse');
                    }, 600);
                }
            } else {
                countElement.style.display = 'none';
            }
        }
    }

    renderNotifications() {
        const listElement = document.getElementById('notificationList');
        if (!listElement) {
            console.log('Element notificationList non trouvé');
            return;
        }

        if (this.notifications.length === 0) {
            listElement.innerHTML = `
                <div class="notification-empty">
                    <i class="ri-inbox-line fs-1 text-muted mb-2"></i>
                    <p class="text-muted text-center mb-0">Aucune notification</p>
                </div>
            `;
            return;
        }

        const notificationsToShow = this.notifications.slice(0, 8);

        listElement.innerHTML = notificationsToShow.map(notification => `
            <div class="notification-item ${notification.read ? '' : 'unread'}" data-id="${notification.id}">
                <div class="notification-content">
                    <div class="notification-icon ${notification.type}">
                        <i class="ri-${this.getNotificationIcon(notification.type)}"></i>
                    </div>
                    <div class="notification-text">
                        <div class="notification-title">${this.escapeHtml(notification.title)}</div>
                        <div class="notification-message">${this.escapeHtml(notification.message)}</div>
                        <div class="notification-time">${this.formatTime(notification.time)}</div>
                        ${!notification.read ? `
                            <div class="notification-actions">
                                <button class="btn btn-sm btn-outline-success notification-action read" 
                                        onclick="window.notificationManager.markAsRead(${notification.id})"
                                        data-bs-toggle="tooltip" title="Marquer comme lu">
                                    <i class="ri-check-line me-1"></i>Lu
                                </button>
                                <button class="btn btn-sm btn-outline-danger notification-action delete" 
                                        onclick="window.notificationManager.deleteNotification(${notification.id})"
                                        data-bs-toggle="tooltip" title="Supprimer">
                                    <i class="ri-delete-bin-line me-1"></i>Supprimer
                                </button>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');

        // Initialiser les tooltips Bootstrap
        if (typeof $ !== 'undefined') {
            $('[data-bs-toggle="tooltip"]').tooltip();
        }
    }

    getNotificationIcon(type) {
        const icons = {
            info: 'information-line',
            warning: 'alert-line',
            success: 'checkbox-circle-line',
            danger: 'error-warning-line',
            system: 'settings-line'
        };
        return icons[type] || 'notification-line';
    }

    formatTime(date) {
        if (!(date instanceof Date)) date = new Date(date);
        const now = new Date();
        const diff = now - date;
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (minutes < 1) return 'À l\'instant';
        if (minutes < 60) return `Il y a ${minutes} min`;
        if (hours < 24) return `Il y a ${hours} h`;
        if (days < 7) return `Il y a ${days} j`;
        return date.toLocaleDateString('fr-FR', {
            day: 'numeric',
            month: 'short'
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    animateNewNotification() {
        // Animation de la cloche
        const bell = document.querySelector('#notificationDropdown i');
        if (bell) {
            bell.style.transition = 'all 0.3s ease';
            bell.style.color = 'var(--primary)';
            bell.style.transform = 'scale(1.2) rotate(15deg)';

            setTimeout(() => {
                bell.style.color = '';
                bell.style.transform = '';
            }, 300);
        }

        // Animation du badge
        const badge = document.getElementById('notificationCount');
        if (badge) {
            badge.classList.add('notification-pulse');
        }
    }

    animateNewNotifications(count) {
        if (count > 0) {
            // Animation plus prononcée pour plusieurs notifications
            const bell = document.querySelector('#notificationDropdown i');
            if (bell) {
                for (let i = 0; i < 3; i++) {
                    setTimeout(() => {
                        bell.style.color = 'var(--primary)';
                        bell.style.transform = 'scale(1.3)';
                        setTimeout(() => {
                            bell.style.color = '';
                            bell.style.transform = '';
                        }, 150);
                    }, i * 200);
                }
            }
        }
    }

    setupEventListeners() {
        // Bouton "Marquer tout comme lu"
        const markAllBtn = document.getElementById('markAllAsRead');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();

                if (this.markAllAsRead()) {
                    // Feedback visuel
                    markAllBtn.innerHTML = '<i class="ri-check-double-line me-1"></i> Tout marqué !';
                    markAllBtn.classList.add('text-success');

                    setTimeout(() => {
                        markAllBtn.innerHTML = 'Tout marquer comme lu';
                        markAllBtn.classList.remove('text-success');
                    }, 2000);
                }
            });
        }

        // Clic sur les notifications (pour les marquer comme lues)
        document.addEventListener('click', (e) => {
            const notificationItem = e.target.closest('.notification-item');
            if (notificationItem && !e.target.closest('.notification-action')) {
                const notificationId = parseInt(notificationItem.dataset.id);
                this.markAsRead(notificationId);
            }
        });

        // Rafraîchissement automatique
        setInterval(() => {
            this.loadNotificationsFromAPI();
        }, 60000); // Toutes les minutes
    }

    // Méthodes utilitaires pour les démos
    addDemoNotifications() {
        if (!this.currentUser) return;

        // Notification de nouveau livre
        setTimeout(() => {
            this.addNotification({
                type: 'info',
                title: 'Nouveautés livresques',
                message: 'Découvrez notre nouvelle collection de romans français',
                category: 'news'
            });
        }, 2000);

        // Notification de rappel (pour non-admin)
        if (this.currentUser.role === 'user') {
            setTimeout(() => {
                this.addNotification({
                    type: 'warning',
                    title: 'Rappel important',
                    message: 'Votre livre "Le Petit Prince" doit être rendu demain',
                    category: 'reminder',
                    priority: 'high'
                });
            }, 4000);
        }

        // Notification système (pour admin)
        if (this.currentUser.role === 'admin') {
            setTimeout(() => {
                this.addNotification({
                    type: 'system',
                    title: 'Maintenance prévue',
                    message: 'Maintenance système prévue samedi de 2h à 4h',
                    category: 'system'
                });
            }, 6000);
        }
    }

    // Méthode pour tester le système
    testNotificationSystem() {
        console.log('=== Test du système de notifications ===');
        console.log('Utilisateur:', this.currentUser);
        console.log('Notifications chargées:', this.notifications.length);
        console.log('Non lues:', this.notifications.filter(n => !n.read).length);

        // Ajouter une notification de test
        const testId = this.addNotification({
            type: 'success',
            title: 'Test de notification',
            message: 'Ceci est une notification de test du système',
            category: 'test'
        });

        console.log('Notification de test ajoutée avec ID:', testId);

        // Marquer comme lu après 2 secondes
        setTimeout(() => {
            this.markAsRead(testId);
            console.log('Notification marquée comme lue');
        }, 2000);

        // Supprimer après 4 secondes
        setTimeout(() => {
            this.deleteNotification(testId);
            console.log('Notification supprimée');
        }, 4000);
    }
}

// Exposer globalement pour le débogage
window.NotificationManager = NotificationManager;

// Initialisation automatique si l'utilisateur est connecté
document.addEventListener('DOMContentLoaded', function () {
    // Vérifier si l'utilisateur est connecté via les données du template
    const isAuthenticated = document.body.classList.contains('has-sidebar');

    if (isAuthenticated) {
        // Récupérer les données utilisateur du DOM
        const userRoleElement = document.querySelector('.sidebar small.text-white-50');
        let userRole = 'user';
        if (userRoleElement) {
            if (userRoleElement.textContent.includes('Administrateur')) userRole = 'admin';
            else if (userRoleElement.textContent.includes('Bibliothécaire')) userRole = 'bibliothecaire';
        }

        const usernameElement = document.querySelector('.sidebar h6.fw-bold');
        const username = usernameElement ? usernameElement.textContent.trim() : 'Utilisateur';

        const userData = {
            id: Math.floor(Math.random() * 1000000), // ID temporaire
            role: userRole,
            name: username
        };

        // Initialiser le gestionnaire après un délai
        setTimeout(() => {
            window.notificationManager = new NotificationManager(userData);

            // Ajouter quelques notifications de démonstration
            if (window.notificationManager) {
                setTimeout(() => {
                    window.notificationManager.addDemoNotifications();
                }, 1500);
            }
        }, 1000);
    }
});

// Fonctions utilitaires globales
window.markNotificationAsRead = function (notificationId) {
    if (window.notificationManager) {
        return window.notificationManager.markAsRead(notificationId);
    }
    return false;
};

window.deleteNotification = function (notificationId) {
    if (window.notificationManager) {
        return window.notificationManager.deleteNotification(notificationId);
    }
    return false;
};

window.markAllNotificationsAsRead = function () {
    if (window.notificationManager) {
        return window.notificationManager.markAllAsRead();
    }
    return false;
};