from main import app, db, User
from werkzeug.security import generate_password_hash

def reset_admin():
    with app.app_context():
        print("1. Suppression de tous les utilisateurs admin existants...")
        User.query.filter_by(role='admin').delete()
        db.session.commit()
        print("✓ Anciens comptes admin supprimés")

        print("\n2. Création d'un nouvel administrateur...")
        admin = User(
            username='admin',
            email='admin@bibliosdjib.dj',
            role='admin',
            password_hash=generate_password_hash('admin123')
        )
        db.session.add(admin)
        db.session.commit()
        print("✓ Nouvel admin créé")

        print("\n3. Vérification du compte créé...")
        admin = User.query.filter_by(username='admin').first()
        if admin:
            print("✓ Admin trouvé dans la base de données")
            print(f"   - Username: {admin.username}")
            print(f"   - Email: {admin.email}")
            print(f"   - Rôle: {admin.role}")
            test_password = admin.check_password('admin123')
            print(f"   - Test du mot de passe 'admin123': {'Succès' if test_password else 'Échec'}")
        else:
            print("❌ Erreur : Admin non trouvé après création")

if __name__ == '__main__':
    print("=== Recréation du compte administrateur ===\n")
    reset_admin()
    print("\n=== Terminé ===")
    print("\nVous pouvez maintenant vous connecter avec:")
    print("Username: admin")
    print("Mot de passe: admin123")