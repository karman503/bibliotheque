import mysql.connector
from main import app, db, User
from werkzeug.security import generate_password_hash

def setup_database():
    # Connexion à MySQL
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password=""
    )
    cursor = connection.cursor()

    # Créer la base de données si elle n'existe pas
    cursor.execute("CREATE DATABASE IF NOT EXISTS bibliotheque")
    cursor.close()
    connection.close()

    # Créer les tables avec Flask-SQLAlchemy
    with app.app_context():
        # Créer toutes les tables
        db.create_all()

        # Vérifier si un admin existe déjà
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            # Créer un nouvel admin
            new_admin = User(
                username='admin',
                email='admin@bibliosdjib.dj',
                role='admin'
            )
            new_admin.set_password('admin123')
            db.session.add(new_admin)
            try:
                db.session.commit()
                print("✅ Compte administrateur créé avec succès!")
                print("Nom d'utilisateur: admin")
                print("Mot de passe: admin123")
            except Exception as e:
                print("❌ Erreur lors de la création de l'admin:", str(e))
                db.session.rollback()
        else:
            print("ℹ️ Un compte administrateur existe déjà")
            # Réinitialiser le mot de passe
            admin.set_password('admin123')
            try:
                db.session.commit()
                print("✅ Mot de passe admin réinitialisé à: admin123")
            except Exception as e:
                print("❌ Erreur lors de la réinitialisation du mot de passe:", str(e))
                db.session.rollback()

if __name__ == '__main__':
    print("🔄 Configuration de la base de données...")
    setup_database()
    print("✨ Configuration terminée!")