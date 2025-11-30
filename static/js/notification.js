// notification.js - Gestionnaire de notifications professionnel
class NotificationManager {
    constructor() {
        this.notifications = this.loadNotifications();
        this.currentUser = this.getCurrentUser();
        this.init();
    }

    init() {
        this.updateNotificationCount();
        this.renderNotifications();
        this.setupEventListeners();
        this.setupDropdownPosition();

        // Charger les notifications depuis l'API si l'utilisateur est connecté
        if (this.currentUser) {
            this.loadNotificationsFromAPI();
        }
    }

    getCurrentUser() {
        // Récupérer les infos utilisateur depuis le template Flask
        try {
            const userElement = document.querySelector('[data-user-id]');
            if (userElement) {
                return {
                    id: userElement.dataset.userId,
                    role: userElement.dataset.userRole,
                    name: userElement.dataset.userName
                };
            }
        } catch (e) {
            console.log('Utilisateur non connecté ou erreur de récupération');
        }
        return null;
    }

    loadNotifications() {
        const stored = localStorage.getItem(`notifications_${this.currentUser?.id}`);
        if (stored) {
            return JSON.parse(stored);
        }

        // Notifications par défaut selon le rôle
        if (this.currentUser?.role === 'admin') {
            return this.getDefaultAdminNotifications();
        } else {
            return this.getDefaultUserNotifications();
        }
    }

    getDefaultAdminNotifications() {
        return [
            {
                id: 1,
                type: 'system',
                title: 'Bienvenue Administrateur',
                message: 'Vous avez accès au panel d\'administration',
                time: new Date(),
                read: false,
                category: 'system'
            },
            {
                id: 2,
                type: 'info',
                title: 'Rapport quotidien',
                message: '5 nouveaux livres ajoutés aujourd\'hui',
                time: new Date(Date.now() - 2 * 60 * 60 * 1000),
                read: false,
                category: 'reports'
            }
        ];
    }

    getDefaultUserNotifications() {
        return [
            {
                id: 1,
                type: 'success',
                title: 'Bienvenue sur BibliosDjib',
                message: 'Votre compte a été créé avec succès',
                time: new Date(),
                read: false,
                category: 'welcome'
            }
        ];
    }

    saveNotifications() {
        if (this.currentUser) {
            localStorage.setItem(`notifications_${this.currentUser.id}`, JSON.stringify(this.notifications));
        }
    }

    async loadNotificationsFromAPI() {
        try {
            // Simulation d'appel API - À remplacer par votre véritable endpoint
            const response = await fetch('/api/notifications');
            if (response.ok) {
                const apiNotifications = await response.json();
                this.mergeNotifications(apiNotifications);
            }
        } catch (error) {
            console.log('Erreur chargement API notifications:', error);
        }
    }

    mergeNotifications(apiNotifications) {
        // Fusionner les notifications API avec les locales
        apiNotifications.forEach(apiNotif => {
            const exists = this.notifications.find(n => n.id === apiNotif.id);
            if (!exists) {
                this.notifications.unshift(apiNotif);
            }
        });
        this.saveNotifications();
        this.updateNotificationCount();
        this.renderNotifications();
    }

    addNotification(notification) {
        const newNotification = {
            id: Date.now(),
            type: notification.type || 'info',
            title: notification.title,
            message: notification.message,
            time: new Date(),
            read: false,
            category: notification.category || 'general',
            action: notification.action || null,
            priority: notification.priority || 'normal'
        };

        this.notifications.unshift(newNotification);
        this.saveNotifications();
        this.updateNotificationCount();
        this.renderNotifications();
        this.animateNotification();

        return newNotification.id;
    }

    // Méthodes spécifiques pour différents types de notifications
    addBookReturnReminder(bookTitle, daysLeft, bookId = null) {
        return this.addNotification({
            type: 'warning',
            title: 'Livre à rendre',
            message: `Le livre "${bookTitle}" doit être rendu dans ${daysLeft} jour(s)`,
            category: 'reminders',
            action: bookId ? { type: 'book', id: bookId } : null,
            priority: 'high'
        });
    }

    addReservationConfirmed(bookTitle, reservationId = null) {
        return this.addNotification({
            type: 'success',
            title: 'Réservation confirmée',
            message: `Votre réservation pour "${bookTitle}" a été confirmée`,
            category: 'reservations',
            action: reservationId ? { type: 'reservation', id: reservationId } : null
        });
    }

    addNewBookAvailable(bookTitle, bookId = null) {
        return this.addNotification({
            type: 'info',
            title: 'Nouveau livre disponible',
            message: `Le livre "${bookTitle}" est maintenant disponible`,
            category: 'new_books',
            action: bookId ? { type: 'book', id: bookId } : null
        });
    }

    // Notifications spécifiques aux administrateurs
    addAdminAlert(message, priority = 'normal') {
        if (this.currentUser?.role === 'admin') {
            return this.addNotification({
                type: 'danger',
                title: 'Alerte Administration',
                message: message,
                category: 'admin_alerts',
                priority: priority
            });
        }
    }

    addSystemReport(message) {
        if (this.currentUser?.role === 'admin') {
            return this.addNotification({
                type: 'system',
                title: 'Rapport Système',
                message: message,
                category: 'system_reports'
            });
        }
    }

    markAsRead(notificationId) {
        const notification = this.notifications.find(n => n.id === notificationId);
        if (notification && !notification.read) {
            notification.read = true;
            this.saveNotifications();
            this.updateNotificationCount();
            this.renderNotifications();

            // Mettre à jour via API si nécessaire
            this.markAsReadAPI(notificationId);
        }
    }

    async markAsReadAPI(notificationId) {
        try {
            await fetch(`/api/notifications/${notificationId}/read`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (error) {
            console.log('Erreur marquage comme lu API:', error);
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

            // Mettre à jour via API
            this.markAllAsReadAPI();
        }
    }

    async markAllAsReadAPI() {
        try {
            await fetch('/api/notifications/read-all', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
        } catch (error) {
            console.log('Erreur marquage tous comme lu API:', error);
        }
    }

    deleteNotification(notificationId) {
        this.notifications = this.notifications.filter(n => n.id !== notificationId);
        this.saveNotifications();
        this.updateNotificationCount();
        this.renderNotifications();
    }

    updateNotificationCount() {
        const unreadCount = this.notifications.filter(n => !n.read).length;
        const countElement = document.getElementById('notificationCount');

        if (countElement) {
            countElement.textContent = unreadCount > 99 ? '99+' : unreadCount;

            // CORRECTION IMPORTANTE : Toujours mettre à jour l'affichage
            if (unreadCount > 0) {
                countElement.style.display = 'flex';
            } else {
                countElement.style.display = 'none';
            }
        }
    }

    renderNotifications() {
        const listElement = document.getElementById('notificationList');
        if (!listElement) return;

        if (this.notifications.length === 0) {
            listElement.innerHTML = `
                <div class="notification-empty">
                    <i class="ri-inbox-line"></i>
                    <p class="text-muted text-center mb-0">Aucune notification</p>
                </div>
            `;
            return;
        }

        listElement.innerHTML = this.notifications.slice(0, 10).map(notification => `
            <div class="notification-item ${notification.read ? '' : 'unread'}" data-id="${notification.id}">
                <div class="notification-content">
                    <div class="notification-icon ${notification.type}">
                        <i class="ri-${this.getNotificationIcon(notification.type)}"></i>
                    </div>
                    <div class="notification-text">
                        <div class="notification-title">${notification.title}</div>
                        <div class="notification-message">${notification.message}</div>
                        <div class="notification-time">${this.formatTime(notification.time)}</div>
                        ${!notification.read ? `
                            <div class="notification-actions">
                                <button class="notification-action read" onclick="notificationManager.markAsRead(${notification.id})">
                                    Marquer comme lu
                                </button>
                                <button class="notification-action delete" onclick="notificationManager.deleteNotification(${notification.id})">
                                    Supprimer
                                </button>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');
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
        const now = new Date();
        const diff = now - new Date(date);
        const minutes = Math.floor(diff / 60000);
        const hours = Math.floor(diff / 3600000);
        const days = Math.floor(diff / 86400000);

        if (minutes < 1) return 'À l\'instant';
        if (minutes < 60) return `Il y a ${minutes} min`;
        if (hours < 24) return `Il y a ${hours} h`;
        if (days < 7) return `Il y a ${days} j`;
        return new Date(date).toLocaleDateString('fr-FR');
    }

    animateNotification() {
        const countElement = document.getElementById('notificationCount');
        if (countElement) {
            countElement.classList.add('notification-pulse');
            setTimeout(() => {
                countElement.classList.remove('notification-pulse');
            }, 600);
        }
    }

    setupEventListeners() {
        // Marquer toutes comme lues - CORRECTION IMPORTANTE
        const markAllBtn = document.getElementById('markAllAsRead');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.markAllAsRead();
            });
        }

        // Clic sur une notification
        document.addEventListener('click', (e) => {
            const notificationItem = e.target.closest('.notification-item');
            if (notificationItem && !e.target.closest('.notification-action')) {
                const notificationId = parseInt(notificationItem.dataset.id);
                this.handleNotificationClick(notificationId);
            }
        });

        // Fermer le dropdown quand on clique ailleurs
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.notification-dropdown') && !e.target.closest('#notificationDropdown')) {
                this.closeDropdown();
            }
        });

        // Actualiser les notifications périodiquement (toutes les 2 minutes)
        setInterval(() => {
            this.loadNotificationsFromAPI();
        }, 120000);
    }

    setupDropdownPosition() {
        // Correction du positionnement du dropdown
        const dropdownElement = document.querySelector('.notification-dropdown');
        const triggerElement = document.getElementById('notificationDropdown');

        if (dropdownElement && triggerElement) {
            // Forcer le repositionnement
            $(dropdownElement).on('shown.bs.dropdown', function () {
                const $this = $(this);
                setTimeout(function () {
                    $this.css('z-index', '99999');
                }, 10);
            });

            // S'assurer que le dropdown reste au-dessus
            dropdownElement.style.zIndex = '99999';
            dropdownElement.style.position = 'absolute';
        }
    }

    handleNotificationClick(notificationId) {
        const notification = this.notifications.find(n => n.id === notificationId);
        if (notification) {
            // Marquer comme lu seulement si ce n'est pas déjà lu
            if (!notification.read) {
                this.markAsRead(notificationId);
            }

            // Rediriger selon l'action
            if (notification.action) {
                switch (notification.action.type) {
                    case 'book':
                        window.location.href = `/livre/${notification.action.id}`;
                        break;
                    case 'reservation':
                        window.location.href = '/mes-reservations';
                        break;
                    case 'admin':
                        window.location.href = '/admin';
                        break;
                }
            }
        }
    }

    closeDropdown() {
        const dropdown = document.querySelector('.notification-dropdown');
        if (dropdown) {
            $(dropdown).removeClass('show');
        }
    }

    // Méthode pour vider les notifications (démo)
    clearAll() {
        this.notifications = [];
        this.saveNotifications();
        this.updateNotificationCount();
        this.renderNotifications();
    }
}

// Initialiser le gestionnaire de notifications
let notificationManager;

document.addEventListener('DOMContentLoaded', function () {
    notificationManager = new NotificationManager();

    // Exposer globalement pour le débogage
    window.notificationManager = notificationManager;

    // Simuler quelques notifications de démonstration
    setTimeout(() => {
        if (notificationManager.currentUser) {
            if (notificationManager.currentUser.role === 'admin') {
                notificationManager.addSystemReport('Système fonctionnel - Tous les services opérationnels');
            } else {
                notificationManager.addNewBookAvailable('Le Petit Prince');
            }
        }
    }, 3000);
});