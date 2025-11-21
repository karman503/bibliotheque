from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
import uuid
import logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Configuration de la base de données
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://root:@localhost/bibliotheque'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'votre_cle_secrete'

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
    image_couverture = db.Column(db.String(255))  # Nouveau champ pour l'image
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

# Route pour créer un admin (à retirer en production)
@app.route('/setup/admin', methods=['GET', 'POST'])
def setup_admin():
    if User.query.filter_by(role='admin').first():
        flash('Un administrateur existe déjà', 'warning')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        admin = User(
            username=request.form['username'],
            email=request.form['email'],
            role='admin'
        )
        admin.set_password(request.form['password'])
        db.session.add(admin)
        db.session.commit()
        flash('Administrateur créé avec succès', 'success')
        return redirect(url_for('login'))
    
    return render_template('setup_admin.html', title='Créer un administrateur')

# Création des tables
with app.app_context():
    db.create_all()

@app.route("/")
def index():
    return render_template("index.html", title="Accueil")

# CATALOGUE - ACCÈS PUBLIC (connecté ou non)
@app.route("/catalogue")
def catalogue():
    # Récupérer les paramètres de filtrage
    categorie = request.args.get('categorie', 'Toutes')
    statut = request.args.get('statut', 'Tous')
    recherche = request.args.get('recherche', '')
    
    # Construire la requête de base
    query = Livre.query
    
    # Appliquer les filtres
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
    
    # Récupérer les emprunts en cours si l'utilisateur est connecté
    livres_empruntes = []
    if current_user.is_authenticated:
        # Utiliser adherent_id si disponible, sinon tenter current_user.id (legacy)
        adherent_id_for_query = None
        if getattr(current_user, 'adherent_id', None):
            adherent_id_for_query = current_user.adherent_id
        else:
            adherent_id_for_query = current_user.id
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

# EMPRUNTER LIVRE - UNIQUEMENT POUR CONNECTÉS
@app.route('/emprunter_livre/<int:livre_id>', methods=['POST'])
@login_required
def emprunter_livre(livre_id):
    livre = Livre.query.get_or_404(livre_id)
    
    # Vérifier si le livre est disponible
    if not livre.disponible:
        flash('Ce livre n\'est pas disponible pour le moment', 'error')
        return redirect(url_for('catalogue'))
    
    # Résoudre l'adhérent lié à l'utilisateur (si non présent, on tombe back sur current_user.id)
    adherent_id_for_query = current_user.adherent_id if getattr(current_user, 'adherent_id', None) else current_user.id

    # Vérifier si l'utilisateur a déjà emprunté ce livre
    emprunt_existant = Emprunt.query.filter_by(
        adherent_id=adherent_id_for_query,
        livre_id=livre_id,
        date_retour_effective=None
    ).first()
    
    if emprunt_existant:
        flash('Vous avez déjà emprunté ce livre', 'error')
        return redirect(url_for('catalogue'))
    
    # Créer un nouvel emprunt
    nouvel_emprunt = Emprunt(
        adherent_id=adherent_id_for_query,
        livre_id=livre_id,
        date_retour_prevue=datetime.utcnow() + timedelta(days=14),
        status='en_cours'
    )
    
    # Marquer le livre comme non disponible
    livre.disponible = False
    
    try:
        db.session.add(nouvel_emprunt)
        db.session.commit()
        flash(f'Livre "{livre.titre}" emprunté avec succès! Date de retour: {nouvel_emprunt.date_retour_prevue.strftime("%d/%m/%Y")}', 'success')
    except Exception as e:
        db.session.rollback()
        flash('Erreur lors de l\'emprunt', 'error')
    
    return redirect(url_for('catalogue'))

# MES EMPRUNTS - UNIQUEMENT POUR CONNECTÉS
@app.route("/mes_emprunts")
@login_required
def mes_emprunts():
    adherent_id_for_query = current_user.adherent_id if getattr(current_user, 'adherent_id', None) else current_user.id
    emprunts_utilisateur = Emprunt.query.filter_by(
        adherent_id=adherent_id_for_query
    ).order_by(Emprunt.date_emprunt.desc()).all()
    
    return render_template(
        "mes_emprunts.html",
        title="Mes Emprunts",
        emprunts=emprunts_utilisateur,
        now=datetime.utcnow()
    )

@app.route("/propos")
def propos():
    return render_template("propos.html", title="À propos")

@app.route("/contact")
def contact():
    return render_template("contact.html", title="Contact")

@app.route("/inscription", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Vérifications
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur est déjà pris', 'danger')
            return render_template('register.html', title='Inscription')
            
        if User.query.filter_by(email=email).first():
            flash('Cette adresse email est déjà utilisée', 'danger')
            return render_template('register.html', title='Inscription')
            
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template('register.html', title='Inscription')
            
        # Création du nouvel utilisateur
        user = User(username=username, email=email, role='user')
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Inscription réussie ! Vous pouvez maintenant vous connecter', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html', title='Inscription')



@app.route("/connexion", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('catalogue'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        logging.info(f"Tentative de connexion - Username reçu")
        
        user = User.query.filter_by(username=username).first()
        logging.info(f"Utilisateur trouvé: {user is not None}")
        
        if user:
            if user.check_password(password):
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


# DASHBOARD - GARDER EXISTANT
@app.route("/dashboard")
@login_required
def dashboard():
    total_livres = Livre.query.count()
    livres_disponibles = Livre.query.filter_by(disponible=True).count()
    total_adherents = Adherent.query.count()
    emprunts_en_cours = Emprunt.query.filter_by(status='en_cours').count()

    return render_template(
        "dashboard.html",
        title="Dashboard",
        user=current_user,
        total_livres=total_livres,
        livres_disponibles=livres_disponibles,
        total_adherents=total_adherents,
        emprunts_en_cours=emprunts_en_cours
    )

# Routes admin (gardez vos routes existantes avec modifications)
@app.route("/dashboard/adherents", methods=['GET', 'POST'])
@login_required
def adherents():
    if request.method == 'POST':
        nouveau_adherent = Adherent(
            nom=request.form['nom'],
            prenom=request.form['prenom'],
            email=request.form['email'],
            telephone=request.form['telephone'],
            classe=request.form.get('classe')
        )
        db.session.add(nouveau_adherent)
        db.session.commit()
        return redirect(url_for('adherents'))
    
    adherents_liste = Adherent.query.all()
    return render_template("adherents.html", title="Adhérents", adherents=adherents_liste)

@app.route("/dashboard/emprunts", methods=['GET', 'POST'])
@login_required
def emprunts():
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
    reservations_liste = []

    return render_template(
        "emprunts.html",
        title="Emprunts",
        emprunts=emprunts_liste,
        adherents=adherents_liste,
        livres=livres_disponibles,
        reservations=reservations_liste,
        now=datetime.utcnow(),
        today=datetime.utcnow().date()
    )

# LIVRES - ADMIN (AJOUTER LE CHAMP IMAGE)
@app.route("/dashboard/livres", methods=['GET', 'POST'])
@login_required
def livres():
    if current_user.role != "admin":
        flash("Accès non autorisé", "danger")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        titre = request.form['titre']
        auteur = request.form['auteur']
        isbn = request.form['isbn']
        annee = request.form['annee_publication']
        categorie = request.form['categorie']
        resume = request.form['resume']

        # GESTION DU FICHIER PDF
        fichier_pdf = request.files.get("contenu_pdf")
        fichier_pdf_nom = None

        if fichier_pdf and fichier_pdf.filename:
            if fichier_pdf.filename.lower().endswith('.pdf'):
                fichier_pdf_nom = secure_filename(fichier_pdf.filename)
                fichier_pdf.save(os.path.join(app.config['UPLOAD_FOLDER'], fichier_pdf_nom))
            else:
                flash("Le fichier doit être au format PDF", "error")
                return redirect(url_for("livres"))

        # GESTION DE L'IMAGE DE COUVERTURE
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

        # Créer le nouveau livre
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
    emprunt = Emprunt.query.get_or_404(emprunt_id)
    emprunt.status = 'retourne'
    emprunt.date_retour_effective = datetime.utcnow()
    emprunt.livre.disponible = True
    db.session.commit()
    return redirect(url_for('emprunts'))


@app.route("/dashboard/statistiques")
@login_required
def statistiques():
    # Si l'utilisateur est admin, on affiche les statistiques globales
    if getattr(current_user, 'role', None) == 'admin':
        total_adherents = Adherent.query.count()
        total_livres = Livre.query.count()
        emprunts_en_cours = Emprunt.query.filter_by(status='en_cours').count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        
        # Calcul du taux de disponibilité
        taux_disponibilite = round((livres_disponibles / total_livres * 100) if total_livres > 0 else 100)
        
        # Statistiques des emprunts par catégorie avec pourcentages pré-calculés
        emprunts_par_categorie = db.session.query(
            Livre.categorie, 
            db.func.count(Emprunt.id).label('count')
        ).join(Emprunt).group_by(Livre.categorie).all()
        
        stats_categories = []
        for categorie, count in emprunts_par_categorie:
            pourcentage = round((count / emprunts_en_cours * 100) if emprunts_en_cours > 0 else 0)
            stats_categories.append({
                'categorie': categorie,
                'count': count,
                'pourcentage': pourcentage
            })
        
        # Adhérents les plus actifs avec pourcentages pré-calculés
        adherents_actifs = db.session.query(
            Adherent,
            db.func.count(Emprunt.id).label('total_emprunts')
        ).join(Emprunt).group_by(Adherent).order_by(db.text('total_emprunts DESC')).limit(5).all()
        
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
                             stats_adherents=stats_adherents)

    # Sinon, afficher uniquement les statistiques personnelles de l'utilisateur
    adherent_id_for_query = current_user.adherent_id if getattr(current_user, 'adherent_id', None) else current_user.id

    total_emprunts_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query).count()
    emprunts_en_cours_user = Emprunt.query.filter_by(adherent_id=adherent_id_for_query, status='en_cours').count()
    retards_user = Emprunt.query.filter(
        Emprunt.adherent_id == adherent_id_for_query,
        Emprunt.date_retour_effective == None,
        Emprunt.date_retour_prevue < datetime.utcnow()
    ).count()
    total_amende_user = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == adherent_id_for_query).scalar() or 0.0

    # Répartition des emprunts par catégorie pour cet utilisateur
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
def parametres():
    return render_template("parametres.html", title="Paramètres")


# ======================
# 🔵 PROFIL UTILISATEUR
# ======================

# Dossier pour les images de profil
PROFILE_FOLDER = "static/uploads/profiles/"
os.makedirs(PROFILE_FOLDER, exist_ok=True)
app.config['PROFILE_FOLDER'] = PROFILE_FOLDER

# Ajout du champ image dans le modèle User si tu ne l’as pas encore
# 👉 (à exécuter ensuite avec flask db migrate && flask db upgrade)
if not hasattr(User, 'image'):
    with app.app_context():
        from sqlalchemy import Column, String
        if not 'image' in [c.name for c in User.__table__.columns]:
            db.session.execute('ALTER TABLE user ADD COLUMN image VARCHAR(255)')
            db.session.commit()


@app.route("/profil")
@login_required
def profil():
    """Page de profil : voir et modifier ses informations"""
    # IMPORTANT: renvoyer exactement 'Mon Profil' pour respecter la logique du template
    return render_template("profil.html", title="Mon Profil", user=current_user)


@app.route("/profil/update", methods=["POST"])
@login_required
def update_profil():
    """Mise à jour du nom et de l’e-mail (vérifie mot de passe courant et unicité)."""
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    current_password = request.form.get("current_password") or request.form.get("current_password", "")

    if not username or not email:
        flash("Veuillez remplir tous les champs.", "danger")
        return redirect(url_for("profil"))

    # Vérifier le mot de passe si fourni (si ton front exige ce champ)
    if current_password:
        if not current_user.check_password(current_password):
            flash("Mot de passe actuel incorrect.", "danger")
            return redirect(url_for("profil"))

    # Vérifier unicité username/email (sauf si c'est le même utilisateur)
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
        db.session.commit()
        flash("Informations mises à jour ✅", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erreur lors de la mise à jour du profil")
        flash("Erreur lors de la mise à jour.", "danger")
    return redirect(url_for("profil"))


@app.route("/profil/upload", methods=["POST"])
@login_required
def upload_image():
    """Téléversement de la photo de profil (sécurisé, nom unique)."""
    # Accepter les deux noms de champ possibles (image ou profile_picture)
    file = request.files.get('image') or request.files.get('profile_picture')
    if not file or file.filename == "":
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for("profil"))

    # Vérifier extension
    allowed_ext = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    if '.' not in filename:
        flash("Fichier invalide.", "danger")
        return redirect(url_for("profil"))
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in allowed_ext:
        flash("Format non autorisé. Utilisez PNG/JPG/JPEG/GIF/WEBP.", "danger")
        return redirect(url_for("profil"))

    # Générer nom unique pour éviter collisions
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    profile_folder = app.config.get('PROFILE_FOLDER', PROFILE_FOLDER)
    os.makedirs(profile_folder, exist_ok=True)
    file_path = os.path.join(profile_folder, unique_name)

    try:
        file.save(file_path)

        # Supprimer ancienne image si existante (propre)
        old = current_user.image
        if old and old != unique_name:
            try:
                old_path = os.path.join(profile_folder, old)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception:
                current_app.logger.exception("Impossible de supprimer l'ancienne image de profil")

        # Met à jour le profil
        current_user.image = unique_name
        db.session.commit()
        flash("Photo de profil mise à jour ✅", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erreur lors de l'upload de la photo de profil")
        flash("Erreur lors de l'upload de l'image.", "danger")

    return redirect(url_for("profil"))

if __name__ == "__main__":
    app.run(debug=True)
