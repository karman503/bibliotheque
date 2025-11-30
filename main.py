from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
import uuid
import logging
import random
import smtplib
from email.message import EmailMessage

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configuration de la base de données
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/bibliotheque'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'votre_cle_secrete'

# Mail config (configurez ici ou via variables d'environnement)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', 'gestionbibliotheque70@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', 'lgxb xbsi krgm ntes')
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', '1') in ('1', 'True', 'true')
app.config['EMAIL_FROM'] = os.environ.get('EMAIL_FROM', app.config['MAIL_USERNAME'])

# Configuration des uploads
UPLOAD_FOLDER = "static/livres/"
COUVERTURE_FOLDER = "static/images/couvertures/"
PROFILE_FOLDER = "static/uploads/profiles/"

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COUVERTURE_FOLDER'] = COUVERTURE_FOLDER
app.config['PROFILE_FOLDER'] = PROFILE_FOLDER

# Créer les dossiers s'ils n'existent pas
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(COUVERTURE_FOLDER, exist_ok=True)
os.makedirs(PROFILE_FOLDER, exist_ok=True)

# Initialisation de SQLAlchemy
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# User loader pour Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Modèles
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image = db.Column(db.String(200), nullable=True)
    # Email verification fields
    confirmed = db.Column(db.Boolean, default=False)
    confirmation_code = db.Column(db.String(16), nullable=True)
    confirmation_expires = db.Column(db.DateTime, nullable=True)
    
    # Lien avec le profil adhérent
    adherent_id = db.Column(db.Integer, db.ForeignKey('adherent.id'))
    adherent = db.relationship('Adherent', backref='user', uselist=False)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')
        
    def check_password(self, password):
        if not self.password_hash or not password:
            return False
        return check_password_hash(self.password_hash, password)

class Adherent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telephone = db.Column(db.String(20))
    classe = db.Column(db.String(50))
    statut = db.Column(db.String(20), default='Actif')
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)
    emprunts = db.relationship('Emprunt', backref='adherent', lazy=True)

class Livre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(200), nullable=False)
    auteur = db.Column(db.String(100), nullable=False)
    isbn = db.Column(db.String(13), unique=True)
    annee_publication = db.Column(db.Integer)
    categorie = db.Column(db.String(50))
    resume = db.Column(db.Text)
    contenu_pdf = db.Column(db.String(255))
    image_couverture = db.Column(db.String(255))
    disponible = db.Column(db.Boolean, default=True)
    emprunts = db.relationship('Emprunt', backref='livre', lazy=True)

class Emprunt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    adherent_id = db.Column(db.Integer, db.ForeignKey('adherent.id'), nullable=False)
    livre_id = db.Column(db.Integer, db.ForeignKey('livre.id'), nullable=False)
    date_emprunt = db.Column(db.DateTime, default=datetime.utcnow)
    date_retour_prevue = db.Column(db.DateTime, nullable=False)
    date_retour_effective = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='en_cours')
    prolongations = db.Column(db.Integer, default=0)
    amende = db.Column(db.Float, default=0.0)

class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    adherent_id = db.Column(db.Integer, db.ForeignKey('adherent.id'), nullable=False)
    livre_id = db.Column(db.Integer, db.ForeignKey('livre.id'), nullable=False)
    date_reservation = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='active')

    adherent = db.relationship('Adherent', backref='reservations')
    livre = db.relationship('Livre', backref='reservations')

# Création des tables
with app.app_context():
    try:
        db.create_all()
    except Exception:
        current_app.logger.exception('Erreur lors de la création des tables (create_all)')

    # Vérification et ajout des colonnes de vérification email si nécessaire
    try:
        inspector = inspect(db.engine)
        cols = [c['name'] for c in inspector.get_columns('user')]
        alter_needed = False
        if 'confirmed' not in cols:
            db.session.execute('ALTER TABLE user ADD COLUMN confirmed TINYINT(1) DEFAULT 0')
            alter_needed = True
        if 'confirmation_code' not in cols:
            db.session.execute("ALTER TABLE user ADD COLUMN confirmation_code VARCHAR(16)")
            alter_needed = True
        if 'confirmation_expires' not in cols:
            db.session.execute("ALTER TABLE user ADD COLUMN confirmation_expires DATETIME")
            alter_needed = True
        if alter_needed:
            db.session.commit()
    except Exception:
        current_app.logger.exception('Impossible d\'ajouter automatiquement les colonnes de confirmation')

# Route pour créer un admin
@app.route('/setup/admin', methods=['GET', 'POST'])
def setup_admin():
    if User.query.filter_by(role='admin').first():
        flash('Un administrateur existe déjà', 'warning')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not username or not email or not password:
            flash('Tous les champs sont requis', 'danger')
            return render_template('setup_admin.html', title='Créer un administrateur')
        
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur existe déjà', 'danger')
            return render_template('setup_admin.html', title='Créer un administrateur')
        
        if User.query.filter_by(email=email).first():
            flash('Cet email existe déjà', 'danger')
            return render_template('setup_admin.html', title='Créer un administrateur')
        
        admin = User(
            username=username,
            email=email,
            role='admin',
            confirmed=True  # Admin n'a pas besoin de vérification email
        )
        admin.set_password(password)
        
        try:
            db.session.add(admin)
            db.session.commit()
            flash('Administrateur créé avec succès! Vous pouvez maintenant vous connecter', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la création: {str(e)}', 'danger')
    
    return render_template('setup_admin.html', title='Créer un administrateur')

@app.route("/")
def index():
    return render_template("index.html", title="Accueil")

# CATALOGUE - ACCÈS PUBLIC
@app.route("/catalogue")
def catalogue():
    categorie = request.args.get('categorie', 'Toutes')
    statut = request.args.get('statut', 'Tous')
    recherche = request.args.get('recherche', '')
    
    query = Livre.query
    
    if categorie != 'Toutes':
        query = query.filter(Livre.categorie == categorie)
    
    if statut != 'Tous':
        if statut == 'disponible':
            query = query.filter(Livre.disponible == True)
        elif statut == 'emprunté':
            query = query.filter(Livre.disponible == False)
    
    if recherche:
        query = query.filter(
            db.or_(
                Livre.titre.ilike(f'%{recherche}%'),
                Livre.auteur.ilike(f'%{recherche}%'),
                Livre.isbn.ilike(f'%{recherche}%')
            )
        )
    
    livres = query.all()
    
    livres_empruntes = []
    if current_user.is_authenticated:
        adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id
        emprunts_utilisateur = Emprunt.query.filter_by(
            adherent_id=adherent_id_for_query,
            date_retour_effective=None
        ).all()
        livres_empruntes = [emp.livre_id for emp in emprunts_utilisateur]
    
    return render_template(
        "catalogue.html", 
        title="Catalogue",
        livres=livres, 
        livres_empruntes=livres_empruntes,
        current_user=current_user,
        categorie_selected=categorie,
        statut_selected=statut,
        recherche_term=recherche
    )

# VERIFICATION EMAIL
@app.route("/verify", methods=['GET', 'POST'])
def verify_email():
    """Page de vérification du code"""
    prefill = request.args.get('username') or ''
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        code = request.form.get('code', '').strip()
        
        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()
        
        if not user:
            flash('Utilisateur non trouvé', 'danger')
            return render_template('verify.html', prefill_username=username)
        
        if (user.confirmation_code == code and 
            user.confirmation_expires and
            user.confirmation_expires > datetime.utcnow()):
            user.confirmed = True
            user.confirmation_code = None
            user.confirmation_expires = None
            db.session.commit()
            
            login_user(user)
            flash('Email vérifié avec succès!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Code invalide ou expiré', 'danger')
            return render_template('verify.html', prefill_username=username)
    
    return render_template('verify.html', prefill_username=prefill)

@app.route("/resend_code", methods=['POST'])
def resend_code():
    """Renvoyer le code de vérification"""
    identifier = request.form.get('identifier', '').strip()
    
    user = User.query.filter(
        (User.username == identifier) | (User.email == identifier)
    ).first()
    
    if user and not user.confirmed:
        code = _generate_confirmation_code()
        user.confirmation_code = code
        user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)
        db.session.commit()
        
        sent = send_verification_email(user.email, user.username, code)
        if sent:
            flash('Nouveau code envoyé!', 'success')
        else:
            flash('Erreur lors de l\'envoi du code', 'danger')
    else:
        flash('Utilisateur non trouvé ou déjà vérifié', 'warning')
    
    return redirect(url_for('verify_email', username=identifier))

def _generate_confirmation_code():
    """Génère un code de confirmation à 6 chiffres"""
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

def send_verification_email(to_email, username, code):
    """Envoie l'email de vérification"""
    try:
        msg = EmailMessage()
        msg['Subject'] = 'Vérification de votre email - Bibliothèque'
        msg['From'] = app.config['EMAIL_FROM']
        msg['To'] = to_email
        
        msg.set_content(f"""
        Bonjour {username},
        
        Votre code de vérification est : {code}
        
        Ce code expirera dans 30 minutes.
        
        Cordialement,
        L'équipe de la Bibliothèque
        """)
        
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
            if app.config['MAIL_USE_TLS']:
                server.starttls()
            server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            server.send_message(msg)
        
        return True
    except Exception as e:
        current_app.logger.error(f"Erreur envoi email: {str(e)}")
        return False

# EMPRUNTER LIVRE
@app.route('/emprunter_livre/<int:livre_id>', methods=['POST'])
@login_required
def emprunter_livre(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    
    if not livre.disponible:
        flash('Ce livre n\'est pas disponible pour le moment', 'error')
        return redirect(url_for('catalogue'))
    
    adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id

    emprunt_existant = Emprunt.query.filter_by(
        adherent_id=adherent_id_for_query,
        livre_id=livre_id,
        date_retour_effective=None
    ).first()
    
    if emprunt_existant:
        flash('Vous avez déjà emprunté ce livre', 'error')
        return redirect(url_for('catalogue'))
    
    nouvel_emprunt = Emprunt(
        adherent_id=adherent_id_for_query,
        livre_id=livre_id,
        date_retour_prevue=datetime.utcnow() + timedelta(days=14),
        status='en_cours'
    )
    
    livre.disponible = False
    
    try:
        db.session.add(nouvel_emprunt)
        db.session.commit()
        flash(f'Livre "{livre.titre}" emprunté avec succès! Date de retour: {nouvel_emprunt.date_retour_prevue.strftime("%d/%m/%Y")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Erreur lors de l\'emprunt', 'error')
    
    return redirect(url_for('catalogue'))

# MES EMPRUNTS
@app.route("/mes_emprunts")
@login_required
def mes_emprunts():
    adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id
    emprunts_utilisateur = Emprunt.query.filter_by(
        adherent_id=adherent_id_for_query
    ).order_by(Emprunt.date_emprunt.desc()).all()
    
    livres_disponibles = Livre.query.filter_by(disponible=True).all()

    return render_template(
        "mes_emprunts.html",
        title="Mes Emprunts",
        emprunts=emprunts_utilisateur,
        now=datetime.utcnow(),
        livres=livres_disponibles
    )

@app.route("/propos")
def propos():
    return render_template("propos.html", title="À propos")

@app.route("/contact", methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        nom_complet = request.form.get('nom_complet', '').strip()
        email = request.form.get('email', '').strip()
        sujet = request.form.get('sujet', '').strip()
        message = request.form.get('message', '').strip()
        
        # Validation des champs
        if not nom_complet or not email or not sujet or not message:
            flash('Tous les champs obligatoires doivent être remplis', 'danger')
            return render_template("contact.html", title="Contact")
        
        # Vérification que l'email n'est pas celui de l'administrateur
        admin_emails = [user.email for user in User.query.filter_by(role='admin').all()]
        if email in admin_emails:
            flash('Veuillez utiliser une adresse email personnelle pour nous contacter', 'danger')
            return render_template("contact.html", title="Contact")
        
        # Envoi de l'email
        try:
            msg = EmailMessage()
            msg['Subject'] = f'Message de contact - {sujet}'
            msg['From'] = app.config['EMAIL_FROM']
            msg['To'] = app.config['EMAIL_FROM']  # Envoi à la bibliothèque
            msg['Reply-To'] = email  # Pour pouvoir répondre directement à l'expéditeur
            
            msg.set_content(f"""
            Nouveau message de contact reçu :
            
            Nom complet : {nom_complet}
            Email : {email}
            Sujet : {sujet}
            
            Message :
            {message}
            
            ---
            Ce message a été envoyé via le formulaire de contact du site web.
            """)
            
            with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
                if app.config['MAIL_USE_TLS']:
                    server.starttls()
                server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
                server.send_message(msg)
            
            flash('Votre message a été envoyé avec succès ! Nous vous répondrons dans les plus brefs délais.', 'success')
            return redirect(url_for('contact'))
            
        except Exception as e:
            current_app.logger.error(f"Erreur envoi email contact: {str(e)}")
            flash('Une erreur est survenue lors de l\'envoi de votre message. Veuillez réessayer.', 'danger')
    
    return render_template("contact.html", title="Contact")

# INSCRIPTION
@app.route("/inscription", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur est déjà pris', 'danger')
            return render_template('register.html', title='Inscription')
            
        if User.query.filter_by(email=email).first():
            flash('Cette adresse email est déjà utilisée', 'danger')
            return render_template('register.html', title='Inscription')
            
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html', title='Inscription')
        
        # CORRECTION: Cette partie était mal indentée
        user = User(username=username, email=email, role='user', confirmed=False)
        user.set_password(password)
        
        code = _generate_confirmation_code()
        user.confirmation_code = code
        user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)

        db.session.add(user)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Erreur lors de l\'inscription')
            flash('Erreur lors de l\'inscription : ' + str(e), 'danger')
            return render_template('register.html', title='Inscription')

        sent = send_verification_email(user.email, user.username, code)
        if sent:
            flash('Inscription réussie ! Un code de vérification a été envoyé à votre adresse email.', 'success')
        else:
            flash('Inscription créée, mais impossible d\'envoyer le code par email. Contactez un administrateur.', 'warning')

        return redirect(url_for('verify_email'))
        
    return render_template('register.html', title='Inscription')

# CONNEXION
@app.route("/connexion", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('catalogue'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        logging.info(f"Tentative de connexion - Username reçu")
        
        user = User.query.filter_by(username=username).first()
        
        if user:
            if user.check_password(password):
                if not user.confirmed and user.role != 'admin':
                    # Générer et envoyer un code de vérification au moment de la tentative de connexion
                    code = _generate_confirmation_code()
                    user.confirmation_code = code
                    user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                    sent = send_verification_email(user.email, user.username, code)
                    if sent:
                        flash('Un code de vérification a été envoyé à votre adresse email. Vérifiez votre boîte et entrez le code.', 'info')
                    else:
                        flash('Impossible d\'envoyer le code de vérification par email. Contactez un administrateur.', 'warning')

                    # Rediriger vers la page de vérification en préremplissant le champ username
                    return redirect(url_for('verify_email', username=username))

                login_user(user)
                flash('Connexion réussie!', 'success')
                return redirect(url_for('catalogue'))
            else:
                logging.info("Mot de passe incorrect")
                flash('Mot de passe incorrect', 'danger')
        else:
            flash('Nom d\'utilisateur non trouvé', 'danger')

    return render_template("login.html", title="Connexion")

@app.route("/deconnexion")
@login_required
def logout():
    logout_user()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('index'))

# DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    if getattr(current_user, 'role', None) == 'admin':
        total_livres = Livre.query.count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        total_adherents = Adherent.query.count()
        emprunts_en_cours = Emprunt.query.filter_by(status='en_cours').count()

        return render_template(
            "dashboard.html",
            title="Dashboard",
            user=current_user,
            is_admin=True,
            total_livres=total_livres,
            livres_disponibles=livres_disponibles,
            total_adherents=total_adherents,
            emprunts_en_cours=emprunts_en_cours
        )
    
    adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id
    
    total_emprunts_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query).count()
    emprunts_en_cours_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query, status='en_cours').count()
    retards_user = Emprunt.query.filter(
        Emprunt.adherent_id == adherent_id_for_query,
        Emprunt.date_retour_effective == None,
        Emprunt.date_retour_prevue < datetime.utcnow()
    ).count()
    total_amende_user = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == adherent_id_for_query).scalar() or 0.0
    
    return render_template(
        "dashboard.html",
        title="Dashboard",
        user=current_user,
        is_admin=False,
        total_emprunts_user=total_emprunts_user,
        emprunts_en_cours_user=emprunts_en_cours_user,
        retards_user=retards_user,
        total_amende_user=total_amende_user
    )

# ROUTES ADMIN
@app.route("/dashboard/adherents", methods=['GET', 'POST'])
@login_required
def adherents():
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            form_data = {k: (v.strip() if isinstance(v, str) else v) for k, v in request.form.items()}
        except Exception:
            form_data = dict(request.form)
        current_app.logger.info(f"Ajout adhérent - données reçues: {form_data}")

        nom = (request.form.get('nom') or '').strip()
        prenom = (request.form.get('prenom') or '').strip()
        email = (request.form.get('email') or '').strip()
        telephone = (request.form.get('telephone') or '').strip()
        classe = (request.form.get('classe') or '').strip() or None
        statut = (request.form.get('statut') or 'Actif').strip()

        if not nom or not prenom or not email:
            flash('Veuillez remplir au moins le nom, le prénom et l\'email', 'danger')
            return redirect(url_for('adherents'))

        nouveau_adherent = Adherent(
            nom=nom,
            prenom=prenom,
            email=email,
            telephone=telephone,
            classe=classe,
            statut=statut
        )
        db.session.add(nouveau_adherent)
        try:
            db.session.commit()

            if request.form.get('create_user'):
                username = (request.form.get('username') or '').strip()
                password = request.form.get('password') or ''
                confirm_password = request.form.get('confirm_password') or ''

                if not username:
                    username = (nouveau_adherent.email.split('@')[0] if nouveau_adherent.email else f'user{nouveau_adherent.id}').strip()

                if password and password != confirm_password:
                    db.session.delete(nouveau_adherent)
                    db.session.commit()
                    flash('Les mots de passe ne correspondent pas. Opération annulée.', 'danger')
                    return redirect(url_for('adherents'))

                existing_user = User.query.filter((User.username == username) | (User.email == nouveau_adherent.email)).first()
                if existing_user:
                    db.session.delete(nouveau_adherent)
                    db.session.commit()
                    flash('Un utilisateur avec ce nom d\'utilisateur ou cet email existe déjà. Opération annulée.', 'danger')
                    return redirect(url_for('adherents'))

                try:
                    user = User(username=username, email=nouveau_adherent.email, role='user', confirmed=True)
                    user.set_password(password if password else uuid.uuid4().hex)
                    user.adherent = nouveau_adherent
                    db.session.add(user)
                    db.session.commit()
                    flash('Adhérent et compte utilisateur créés avec succès', 'success')
                except IntegrityError:
                    db.session.rollback()
                    try:
                        db.session.delete(nouveau_adherent)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    flash('Erreur : impossible de créer le compte utilisateur (doublon).', 'danger')
                    return redirect(url_for('adherents'))
                except Exception:
                    db.session.rollback()
                    current_app.logger.exception('Erreur lors de la création du compte utilisateur')
                    flash('Erreur lors de la création du compte utilisateur.', 'danger')
                    return redirect(url_for('adherents'))

            flash('Adhérent ajouté avec succès', 'success')
            return redirect(url_for('edit_adherent', adherent_id=nouveau_adherent.id))
        except IntegrityError as ie:
            db.session.rollback()
            current_app.logger.exception('IntegrityError lors de l\'ajout d\'un adhérent')
            flash('Erreur : l\'email est déjà utilisé ou données invalides.', 'danger')
            return redirect(url_for('adherents'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Erreur inattendue lors de l\'ajout d\'un adhérent')
            flash('Une erreur est survenue lors de l\'ajout de l\'adhérent.', 'danger')
            return redirect(url_for('adherents'))

    # Filtres GET
    recherche = request.args.get('recherche', '').strip()
    classe = request.args.get('classe', 'Toutes')
    statut = request.args.get('statut', 'Tous')
    emprunteurs_only = request.args.get('emprunteurs', '0') == '1'

    query = Adherent.query

    if recherche:
        pattern = f"%{recherche}%"
        query = query.filter(
            db.or_(
                Adherent.nom.ilike(pattern),
                Adherent.prenom.ilike(pattern),
                Adherent.email.ilike(pattern),
                Adherent.telephone.ilike(pattern)
            )
        )

    if classe and classe not in ('Toutes', 'Toutes les classes'):
        query = query.filter(Adherent.classe == classe)

    if statut and statut != 'Tous':
        try:
            query = query.filter(Adherent.statut == statut)
        except Exception:
            current_app.logger.exception('Erreur lors du filtrage par statut')

    if emprunteurs_only:
        query = query.join(Emprunt).group_by(Adherent.id)

    adherents_liste = query.order_by(Adherent.nom.asc()).all()
    return render_template("adherents.html", title="Adhérents", adherents=adherents_liste,
                           recherche_term=recherche, classe_selected=classe, statut_selected=statut,
                           emprunteurs_selected= ('1' if emprunteurs_only else '0'))

@app.route('/dashboard/adherents/new', methods=['GET', 'POST'])
@login_required
def new_adherent():
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('adherents'))

    if request.method == 'POST':
        try:
            form_data = {k: (v.strip() if isinstance(v, str) else v) for k, v in request.form.items()}
        except Exception:
            form_data = dict(request.form)
        current_app.logger.info(f"Ajout adhérent (page) - données reçues: {form_data}")

        nom = (request.form.get('nom') or '').strip()
        prenom = (request.form.get('prenom') or '').strip()
        email = (request.form.get('email') or '').strip()
        telephone = (request.form.get('telephone') or '').strip()
        classe = (request.form.get('classe') or '').strip() or None
        statut = (request.form.get('statut') or 'Actif').strip()

        if not nom or not prenom or not email:
            flash('Veuillez remplir au moins le nom, le prénom et l\'email', 'danger')
            return redirect(url_for('new_adherent'))

        nouveau_adherent = Adherent(
            nom=nom,
            prenom=prenom,
            email=email,
            telephone=telephone,
            classe=classe,
            statut=statut
        )
        db.session.add(nouveau_adherent)
        try:
            db.session.commit()

            if request.form.get('create_user'):
                username = (request.form.get('username') or '').strip()
                password = request.form.get('password') or ''
                confirm_password = request.form.get('confirm_password') or ''

                if not username:
                    username = (nouveau_adherent.email.split('@')[0] if nouveau_adherent.email else f'user{nouveau_adherent.id}').strip()

                if password and password != confirm_password:
                    db.session.delete(nouveau_adherent)
                    db.session.commit()
                    flash('Les mots de passe ne correspondent pas. Opération annulée.', 'danger')
                    return redirect(url_for('new_adherent'))

                existing_user = User.query.filter((User.username == username) | (User.email == nouveau_adherent.email)).first()
                if existing_user:
                    db.session.delete(nouveau_adherent)
                    db.session.commit()
                    flash('Un utilisateur avec ce nom d\'utilisateur ou cet email existe déjà. Opération annulée.', 'danger')
                    return redirect(url_for('new_adherent'))

                try:
                    user = User(username=username, email=nouveau_adherent.email, role='user', confirmed=True)
                    user.set_password(password if password else uuid.uuid4().hex)
                    user.adherent = nouveau_adherent
                    db.session.add(user)
                    db.session.commit()
                    flash('Adhérent et compte utilisateur créés avec succès', 'success')
                except IntegrityError:
                    db.session.rollback()
                    try:
                        db.session.delete(nouveau_adherent)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    flash('Erreur : impossible de créer le compte utilisateur (doublon).', 'danger')
                    return redirect(url_for('new_adherent'))
                except Exception:
                    db.session.rollback()
                    current_app.logger.exception('Erreur lors de la création du compte utilisateur')
                    flash('Erreur lors de la création du compte utilisateur.', 'danger')
                    return redirect(url_for('new_adherent'))

            flash('Adhérent ajouté avec succès', 'success')
            return redirect(url_for('adherents'))
        except IntegrityError:
            db.session.rollback()
            current_app.logger.exception('IntegrityError lors de l\'ajout d\'un adhérent')
            flash('Erreur : l\'email est déjà utilisé ou données invalides.', 'danger')
            return redirect(url_for('new_adherent'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Erreur inattendue lors de l\'ajout de l\'adhérent')
            flash('Une erreur est survenue lors de l\'ajout de l\'adhérent.', 'danger')
            return redirect(url_for('new_adherent'))

    return render_template('adherent_new.html', title='Nouvel adhérent')

@app.route('/dashboard/adherents/<int:adherent_id>')
@login_required
def view_adherent(adherent_id):
    a = Adherent.query.get_or_404(adherent_id)
    return render_template('adherent_view.html', title=f"Adhérent {a.nom}", adherent=a)

@app.route('/dashboard/adherents/<int:adherent_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_adherent(adherent_id):
    a = Adherent.query.get_or_404(adherent_id)
    if request.method == 'POST':
        a.nom = request.form.get('nom', a.nom)
        a.prenom = request.form.get('prenom', a.prenom)
        a.email = request.form.get('email', a.email)
        a.telephone = request.form.get('telephone', a.telephone)
        a.classe = request.form.get('classe', a.classe)
        a.statut = request.form.get('statut', a.statut if hasattr(a, 'statut') else 'Actif')
        try:
            db.session.commit()
            flash('Adhérent mis à jour', 'success')
        except Exception:
            db.session.rollback()
            flash('Erreur lors de la mise à jour', 'danger')
        return redirect(url_for('adherents'))
    return render_template('adherent_edit.html', title=f"Modifier {a.nom}", adherent=a)

@app.route('/dashboard/adherents/<int:adherent_id>/emprunts')
@login_required
def adherent_emprunts(adherent_id):
    a = Adherent.query.get_or_404(adherent_id)
    emprunts_liste = Emprunt.query.filter_by(adherent_id=adherent_id).order_by(Emprunt.date_emprunt.desc()).all()
    livres_disponibles = Livre.query.filter_by(disponible=True).all()
    return render_template('adherent_emprunts.html', title=f"Emprunts {a.nom}", adherent=a, emprunts=emprunts_liste, livres=livres_disponibles)

@app.route("/dashboard/emprunts", methods=['GET', 'POST'])
@login_required
def emprunts():
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        try:
            adherent_id = int(request.form['adherent_id'])
            livre_id = int(request.form['livre_id'])
            date_retour_str = request.form['date_retour']
            date_retour_prevue = datetime.strptime(date_retour_str, '%Y-%m-%d')
        except (ValueError, KeyError):
            return "Données invalides", 400

        livre = Livre.query.get(livre_id)
        if not livre or not livre.disponible:
            return "Livre non disponible", 400

        nouvel_emprunt = Emprunt(
            adherent_id=adherent_id,
            livre_id=livre_id,
            date_retour_prevue=date_retour_prevue
        )

        livre.disponible = False
        db.session.add(nouvel_emprunt)
        db.session.commit()

        return redirect(url_for('emprunts'))

    emprunts_liste = Emprunt.query.all()
    adherents_liste = Adherent.query.all()
    livres_disponibles = Livre.query.filter_by(disponible=True).all()
    reservations_liste = Reservation.query.order_by(Reservation.date_reservation.desc()).all()

    return render_template(
        "emprunts.html",
        title="Emprunts",
        emprunts=emprunts_liste,
        adherents=adherents_liste,
        livres=livres_disponibles,
        reservations=reservations_liste,
        now=datetime.utcnow(),
        today=datetime.utcnow().date(),
        timedelta=timedelta
    )

# ROUTES RESERVATIONS
@app.route('/reservation/create', methods=['POST'])
@login_required
def create_reservation():
    try:
        livre_id = int(request.form.get('livre_id'))
    except (ValueError, TypeError):
        flash('Données invalides pour la réservation (livre).', 'danger')
        return redirect(request.referrer or url_for('catalogue'))

    adherent_id = request.form.get('adherent_id')
    if not adherent_id:
        adherent_id = getattr(current_user, 'adherent_id', None) or (getattr(current_user, 'adherent', None) and current_user.adherent.id)

    try:
        adherent_id = int(adherent_id)
    except (ValueError, TypeError):
        flash('Aucun adhérent associé à votre compte. Contactez un administrateur.', 'warning')
        return redirect(request.referrer or url_for('mes_emprunts'))

    livre = Livre.query.get(livre_id)
    adherent = Adherent.query.get(adherent_id)
    if not livre or not adherent:
        flash('Livre ou adhérent introuvable', 'danger')
        return redirect(request.referrer or url_for('catalogue'))

    existing = Reservation.query.filter_by(adherent_id=adherent_id, livre_id=livre_id, status='active').first()
    if existing:
        flash('Vous avez déjà une réservation active pour ce livre.', 'warning')
        return redirect(request.referrer or url_for('catalogue'))

    res = Reservation(adherent_id=adherent_id, livre_id=livre_id)
    db.session.add(res)
    try:
        db.session.commit()
        flash('Réservation créée avec succès', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors de la création de la réservation', 'danger')

    return redirect(request.referrer or url_for('catalogue'))

@app.route('/dashboard/reservations')
@login_required
def reservations_list():
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    res = Reservation.query.order_by(Reservation.date_reservation.desc()).all()
    return render_template('reservations.html', title='Réservations', reservations=res)

@app.route('/mes_reservations')
@login_required
def mes_reservations():
    adherent_id = getattr(current_user, 'adherent_id', None) or (getattr(current_user, 'adherent', None) and current_user.adherent.id)
    if not adherent_id:
        flash('Aucun profil adhérent lié à votre compte. Impossible d\'afficher les réservations.', 'warning')
        return redirect(url_for('mes_emprunts'))

    reservations = Reservation.query.filter_by(adherent_id=adherent_id).order_by(Reservation.date_reservation.desc()).all()
    return render_template('mes_reservations.html', title='Mes Réservations', reservations=reservations)

@app.route('/reservation/cancel/<int:res_id>', methods=['POST'])
@login_required
def user_cancel_reservation(res_id):
    r = Reservation.query.get_or_404(res_id)
    owner_adherent_id = getattr(current_user, 'adherent_id', None) or (getattr(current_user, 'adherent', None) and current_user.adherent.id)
    if getattr(current_user, 'role', None) != 'admin' and r.adherent_id != owner_adherent_id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('mes_reservations'))

    if r.status != 'active':
        flash('La réservation n\'est pas active.', 'warning')
        return redirect(url_for('mes_reservations'))

    r.status = 'cancelled'
    try:
        db.session.commit()
        flash('Réservation annulée', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors de l\'annulation de la réservation', 'danger')
    
    if getattr(current_user, 'role', None) == 'admin':
        return redirect(url_for('reservations_list'))
    return redirect(url_for('mes_reservations'))

@app.route('/dashboard/reservations/fulfill/<int:res_id>', methods=['POST'])
@login_required
def fulfill_reservation(res_id):
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    r = Reservation.query.get_or_404(res_id)
    if r.status != 'active':
        flash('Réservation non active', 'warning')
        return redirect(url_for('reservations_list'))

    if not r.livre.disponible:
        flash('Livre non disponible pour prêt', 'danger')
        return redirect(url_for('reservations_list'))

    empr = Emprunt(adherent_id=r.adherent_id, livre_id=r.livre_id, date_retour_prevue=datetime.utcnow() + timedelta(days=14), status='en_cours')
    r.status = 'fulfilled'
    r.livre.disponible = False
    db.session.add(empr)
    try:
        db.session.commit()
        flash('Réservation transformée en emprunt', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors du traitement', 'danger')
    return redirect(url_for('reservations_list'))

@app.route('/dashboard/reservations/cancel/<int:res_id>', methods=['POST'])
@login_required
def cancel_reservation(res_id):
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    r = Reservation.query.get_or_404(res_id)
    if r.status != 'active':
        flash('Réservation non active', 'warning')
        return redirect(url_for('reservations_list'))
    r.status = 'cancelled'
    try:
        db.session.commit()
        flash('Réservation annulée', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors de l\'annulation', 'danger')
    return redirect(url_for('reservations_list'))

# LIVRES - ADMIN
@app.route("/dashboard/livres", methods=['GET', 'POST'])
@login_required
def livres():
    if getattr(current_user, 'role', None) != 'admin':
        flash("Accès non autorisé", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        titre = request.form['titre']
        auteur = request.form['auteur']
        isbn = request.form['isbn']
        annee = request.form['annee_publication']
        categorie = request.form['categorie']
        resume = request.form['resume']

        fichier_pdf = request.files.get("contenu_pdf")
        fichier_pdf_nom = None

        if fichier_pdf and fichier_pdf.filename:
            if fichier_pdf.filename.lower().endswith('.pdf'):
                fichier_pdf_nom = secure_filename(fichier_pdf.filename)
                fichier_pdf.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_pdf_nom))
            else:
                flash("Le fichier doit être au format PDF", "error")
                return redirect(url_for("livres"))

        fichier_image = request.files.get("image_couverture")
        fichier_image_nom = None

        if fichier_image and fichier_image.filename:
            allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            if '.' in fichier_image.filename and \
               fichier_image.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                fichier_image_nom = secure_filename(fichier_image.filename)
                fichier_image.save(os.path.join(app.config['COUVERTURE_FOLDER'], fichier_image_nom))
            else:
                flash("Le fichier image doit être au format PNG, JPG, JPEG, GIF ou WEBP", "error")
                return redirect(url_for("livres"))

        nouveau_livre = Livre(
            titre=titre,
            auteur=auteur,
            isbn=isbn,
            annee_publication=annee,
            categorie=categorie,
            resume=resume,
            contenu_pdf=fichier_pdf_nom,
            image_couverture=fichier_image_nom
        )

        try:
            db.session.add(nouveau_livre)
            db.session.commit()
            flash("Livre ajouté avec succès", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'ajout du livre: {str(e)}", "error")

        return redirect(url_for("livres"))

    livres_liste = Livre.query.all()
    return render_template("livres.html", title="Livres", livres=livres_liste)

@app.route("/dashboard/emprunts/retour/<int:emprunt_id>")
@login_required
def retourner_livre(emprunt_id):
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
        
    emprunt = Emprunt.query.get_or_404(emprunt_id)
    emprunt.status = 'retourne'
    emprunt.date_retour_effective = datetime.utcnow()
    emprunt.livre.disponible = True
    db.session.commit()
    
    ref = request.referrer
    try:
        if ref:
            return redirect(ref)
    except Exception:
        pass
    return redirect(url_for('adherents'))

@app.route('/dashboard/emprunts/prolong/<int:emprunt_id>', methods=['POST'])
@login_required
def prolonger_emprunt(emprunt_id):
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
        
    emprunt = Emprunt.query.get_or_404(emprunt_id)
    try:
        if emprunt.date_retour_effective:
            flash('Impossible de prolonger un emprunt déjà retourné.', 'warning')
            return redirect(url_for('emprunts'))
        if emprunt.prolongations >= 2:
            flash('Nombre maximum de prolongations atteint.', 'warning')
            return redirect(url_for('emprunts'))
        emprunt.prolongations = emprunt.prolongations + 1
        emprunt.date_retour_prevue = emprunt.date_retour_prevue + timedelta(days=7)
        db.session.commit()
        flash('Prolongation effectuée (+7 jours)', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors de la prolongation', 'danger')
    return redirect(url_for('emprunts'))

@app.route('/dashboard/emprunts/<int:emprunt_id>')
@login_required
def view_emprunt(emprunt_id):
    if getattr(current_user, 'role', None) != 'admin':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
        
    e = Emprunt.query.get_or_404(emprunt_id)
    return render_template('emprunt_detail.html', title=f"Emprunt {e.id}", emprunt=e)

# STATISTIQUES
@app.route("/dashboard/statistiques")
@login_required
def statistiques():
    if getattr(current_user, 'role', None) == 'admin':
        period = request.args.get('period', 'month')
        now_dt = datetime.utcnow()
        if period == 'week':
            start = now_dt - timedelta(days=7)
        elif period == 'month':
            start = now_dt - timedelta(days=30)
        elif period == 'quarter':
            start = now_dt - timedelta(days=90)
        elif period == 'year':
            start = now_dt - timedelta(days=365)
        else:
            start = now_dt - timedelta(days=30)

        total_adherents = Adherent.query.count()
        total_livres = Livre.query.count()
        emprunts_en_cours = Emprunt.query.filter(Emprunt.date_emprunt >= start).filter_by(status='en_cours').count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        
        taux_disponibilite = round((livres_disponibles / total_livres * 100) if total_livres > 0 else 100)
        
        emprunts_par_categorie = db.session.query(
            Livre.categorie, 
            db.func.count(Emprunt.id).label('count')
        ).join(Emprunt).filter(Emprunt.date_emprunt >= start).group_by(Livre.categorie).all()
        
        stats_categories = []
        for categorie, count in emprunts_par_categorie:
            pourcentage = round((count / emprunts_en_cours * 100) if emprunts_en_cours > 0 else 0)
            stats_categories.append({
                'categorie': categorie,
                'count': count,
                'pourcentage': pourcentage
            })
        
        adherents_actifs = db.session.query(
            Adherent,
            db.func.count(Emprunt.id).label('total_emprunts')
        ).join(Emprunt).filter(Emprunt.date_emprunt >= start).group_by(Adherent).order_by(db.text('total_emprunts DESC')).limit(5).all()
        
        stats_adherents = []
        max_emprunts = max([total for _, total in adherents_actifs]) if adherents_actifs else 1
        for adherent, total in adherents_actifs:
            pourcentage = round((total / max_emprunts * 100))
            stats_adherents.append({
                'adherent': adherent,
                'total': total,
                'pourcentage': pourcentage
            })
        
        return render_template("statistiques.html", 
                     title="Statistiques",
                     is_admin=True,
                     total_adherents=total_adherents,
                     total_livres=total_livres,
                     emprunts_en_cours=emprunts_en_cours,
                     livres_disponibles=livres_disponibles,
                     taux_disponibilite=taux_disponibilite,
                     stats_categories=stats_categories,
                     stats_adherents=stats_adherents,
                     period=period)

    adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id

    total_emprunts_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query).count()
    emprunts_en_cours_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query, status='en_cours').count()
    retards_user = Emprunt.query.filter(
        Emprunt.adherent_id == adherent_id_for_query,
        Emprunt.date_retour_effective == None,
        Emprunt.date_retour_prevue < datetime.utcnow()
    ).count()
    total_amende_user = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == adherent_id_for_query).scalar() or 0.0

    emprunts_par_categorie_user = db.session.query(
        Livre.categorie,
        db.func.count(Emprunt.id).label('count')
    ).join(Emprunt).filter(Emprunt.adherent_id == adherent_id_for_query).group_by(Livre.categorie).all()

    stats_categories = []
    for categorie, count in emprunts_par_categorie_user:
        pourcentage = round((count / total_emprunts_user * 100) if total_emprunts_user > 0 else 0)
        stats_categories.append({
            'categorie': categorie,
            'count': count,
            'pourcentage': pourcentage
        })

    recent_emprunts = Emprunt.query.filter_by(adherent_id=adherent_id_for_query).order_by(Emprunt.date_emprunt.desc()).limit(6).all()

    return render_template("statistiques.html",
                         title="Mes statistiques",
                         is_admin=False,
                         total_emprunts_user=total_emprunts_user,
                         emprunts_en_cours_user=emprunts_en_cours_user,
                         retards_user=retards_user,
                         total_amende_user=total_amende_user,
                         stats_categories=stats_categories,
                         recent_emprunts=recent_emprunts)

@app.route("/dashboard/parametres")
@login_required
def parametres():
    return render_template("parametres.html", title="Paramètres")

# PROFIL UTILISATEUR
@app.route("/profil")
@login_required
def profil():
    return render_template("profil.html", title="Mon Profil", user=current_user)

@app.route("/profil/update", methods=["POST"])
@login_required
def update_profil():
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    current_password = request.form.get("current_password") or request.form.get("current_password", "")

    if not username or not email:
        flash("Veuillez remplir tous les champs.", "danger")
        return redirect(url_for("profil"))

    if current_password:
        if not current_user.check_password(current_password):
            flash("Mot de passe actuel incorrect.", "danger")
            return redirect(url_for("profil"))

    existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
    if existing_user:
        flash("Ce nom d'utilisateur est déjà pris.", "danger")
        return redirect(url_for("profil"))

    existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing_email:
        flash("Cette adresse email est déjà utilisée.", "danger")
        return redirect(url_for("profil"))

    try:
        current_user.username = username
        current_user.email = email
        telephone_form = (request.form.get('telephone') or '').strip()
        if getattr(current_user, 'adherent', None) and telephone_form:
            try:
                current_user.adherent.telephone = telephone_form
            except Exception:
                current_app.logger.exception('Impossible de mettre à jour le téléphone de l\'adhérent')
        db.session.commit()
        flash("Informations mises à jour", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erreur lors de la mise à jour du profil")
        flash("Erreur lors de la mise à jour.", "danger")
    return redirect(url_for("profil"))

@app.route("/profil/upload", methods=["POST"])
@login_required
def upload_image():
    file = request.files.get('image') or request.files.get('profile_picture')
    if not file or file.filename == "":
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for("profil"))

    allowed_ext = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    if '.' not in filename:
        flash("Fichier invalide.", "danger")
        return redirect(url_for("profil"))
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in allowed_ext:
        flash("Format non autorisé. Utilisez PNG/JPG/JPEG/GIF/WEBP.", "danger")
        return redirect(url_for("profil"))

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    profile_folder = app.config.get('PROFILE_FOLDER', PROFILE_FOLDER)
    os.makedirs(profile_folder, exist_ok=True)
    file_path = os.path.join(profile_folder, unique_name)

    try:
        file.save(file_path)

        old = current_user.image
        if old and old != unique_name:
            try:
                old_path = os.path.join(profile_folder, old)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                current_app.logger.exception("Impossible de supprimer l'ancienne image de profil")

        current_user.image = unique_name
        db.session.commit()
        flash("Photo de profil mise à jour", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erreur lors de l'upload de la photo de profil")
        flash("Erreur lors de l'upload de l'image.", "danger")

    return redirect(url_for("profil"))

@app.route('/profil/delete', methods=['POST'])
@login_required
def delete_account():
    password = request.form.get('password') or ''
    if not password or not current_user.check_password(password):
        flash('Mot de passe incorrect ou manquant. Suppression annulée.', 'danger')
        return redirect(url_for('profil'))

    try:
        adherent = getattr(current_user, 'adherent', None)
        if adherent:
            try:
                db.session.query(Emprunt).filter(Emprunt.adherent_id == adherent.id).delete(synchronize_session=False)
            except Exception:
                current_app.logger.exception('Erreur suppression emprunts utilisateur')
            try:
                db.session.query(Reservation).filter(Reservation.adherent_id == adherent.id).delete(synchronize_session=False)
            except Exception:
                current_app.logger.exception('Erreur suppression reservations utilisateur')

        user = User.query.get(current_user.id)
        logout_user()
        db.session.delete(user)

        if adherent:
            db.session.delete(adherent)

        db.session.commit()
        flash('Compte supprimé avec succès.', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Erreur lors de la suppression du compte')
        flash('Erreur lors de la suppression du compte.', 'danger')
        return redirect(url_for('profil'))

    return redirect(url_for('index'))

if __name__ == "__main__":
    app.run(debug=True)