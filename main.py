from flask import Flask, render_template, request, redirect, url_for, flash, session, current_app, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
import os
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
import uuid
import logging
import random
import smtplib
from email.message import EmailMessage
import re
from functools import wraps
import csv
from io import StringIO
import io

# Ajout des imports pour ReportLab (PDF)
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch, cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

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


@app.context_processor
def inject_global_adherents_livres():
    """Fournit automatiquement `adherents`, `livres` (disponibles) et `today`
    à tous les templates afin que les modals et menus aient accès aux données.
    """
    try:
        adherents = Adherent.query.order_by(Adherent.nom, Adherent.prenom).all()
        livres = Livre.query.filter_by(disponible=True).order_by(Livre.titre).all()
    except Exception:
        adherents = []
        livres = []
    today = datetime.utcnow().date()
    # Récupérer les paramètres de la bibliothèque (pour exposer p.ex. le montant de l'amende)
    try:
        cfg_global = get_library_config()
        library_settings = {
            'amende_par_jour': cfg_global.amende_par_jour,
            'duree_emprunt': cfg_global.duree_emprunt,
            'max_emprunts': cfg_global.max_emprunts
        }
    except Exception:
        library_settings = {'amende_par_jour': 0.0, 'duree_emprunt': 14, 'max_emprunts': 3}
    # Si l'utilisateur courant est lié à un adhérent, recalculer et fournir ses amendes/retards
    total_amende_user = 0.0
    retards_user = 0
    try:
        if current_user.is_authenticated:
            adherent_id = getattr(current_user, 'adherent_id', None) or current_user.id
            # Mettre à jour les amendes pour les emprunts en retard
            now = datetime.utcnow()
            overdues = Emprunt.query.filter(
                Emprunt.adherent_id == adherent_id,
                Emprunt.date_retour_effective == None,
                Emprunt.date_retour_prevue < now
            ).all()
            updated = False
            cfg = get_library_config()
            for od in overdues:
                ret_prevue = _to_date(od.date_retour_prevue)
                days_late = (now.date() - ret_prevue).days if ret_prevue is not None else 0
                new_amende = cfg.amende_par_jour * days_late if days_late > 0 else 0.0
                if (od.amende or 0.0) != new_amende:
                    od.amende = new_amende
                    updated = True
            if updated:
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

            total_amende_user = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == adherent_id).scalar() or 0.0
            retards_user = len(overdues)
    except Exception:
        current_app.logger.exception('Erreur calcul amendes global')

    return dict(adherents=adherents, livres=livres, today=today, total_amende_user=total_amende_user, retards_user=retards_user, library_settings=library_settings)


def role_required(roles):
    """Décorateur pour vérifier le rôle de l'utilisateur"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            
            if current_user.role not in roles:
                flash('Accès non autorisé', 'danger')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def has_roles(*roles):
    """Return True if current_user.role is one of the provided roles."""
    try:
        return getattr(current_user, 'role', None) in roles
    except Exception:
        return False


def is_valid_email(email: str) -> bool:
    """Very small email validation to ensure a basic pattern (local@domain.tld)."""
    if not email or not isinstance(email, str):
        return False
    # simple regex: not perfect but prevents obvious invalids
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

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
    adherent = db.relationship('Adherent', backref=db.backref('user', uselist=False), uselist=False)
    
    # Lien avec le profil bibliothécaire
    bibliothecaire_id = db.Column(db.Integer, db.ForeignKey('bibliothecaire.id'))
    bibliothecaire = db.relationship('Bibliothecaire', backref=db.backref('user', uselist=False), uselist=False)
    
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


class Bibliothecaire(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    prenom = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telephone = db.Column(db.String(20))
    poste = db.Column(db.String(50), default='Bibliothécaire')
    departement = db.Column(db.String(50))
    date_embauche = db.Column(db.Date, default=datetime.utcnow)
    statut = db.Column(db.String(20), default='Actif')
    date_naissance = db.Column(db.Date)
    genre = db.Column(db.String(1))
    adresse = db.Column(db.Text)
    email_personnel = db.Column(db.String(120))
    telephone_personnel = db.Column(db.String(20))
    description_poste = db.Column(db.Text)
    image = db.Column(db.String(200), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


class Configuration(db.Model):
    """Singleton table pour stocker les paramètres de la bibliothèque."""
    id = db.Column(db.Integer, primary_key=True)
    max_emprunts = db.Column(db.Integer, default=3)
    duree_emprunt = db.Column(db.Integer, default=14)
    max_prolongations = db.Column(db.Integer, default=2)
    jours_prolongation = db.Column(db.Integer, default=7)
    amende_par_jour = db.Column(db.Float, default=0.5)


def get_library_config():
    cfg = Configuration.query.first()
    if not cfg:
        cfg = Configuration()
        try:
            db.session.add(cfg)
            db.session.commit()
        except Exception:
            db.session.rollback()
    return cfg


def _to_date(dt):
    """Return a date object for a datetime/date-like value or None.
    Safe helper to handle both datetime and date instances.
    """
    if dt is None:
        return None
    try:
        if isinstance(dt, datetime):
            return dt.date()
        if isinstance(dt, date):
            return dt
        # Fallback: try calling .date() (some DB objects behave like datetimes)
        return dt.date()
    except Exception:
        return None

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

# Fonctions pour générer les PDF
def generate_bibliothecaires_pdf(bibliothecaires):
    """Générer un PDF avec la liste des bibliothécaires"""
    buffer = io.BytesIO()
    
    # Créer le document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Centré
    )
    
    # Contenu du PDF
    story = []
    
    # Titre
    story.append(Paragraph("LISTE DES BIBLIOTHÉCAIRES", title_style))
    story.append(Spacer(1, 20))
    
    # Informations générales
    date_str = datetime.now().strftime("%d/%m/%Y")
    total = len(bibliothecaires)
    info_text = f"<b>Date d'export :</b> {date_str} | <b>Total :</b> {total} bibliothécaires"
    story.append(Paragraph(info_text, styles['Normal']))
    story.append(Spacer(1, 20))
    
    # Préparer les données du tableau
    data = []
    
    # En-têtes du tableau
    headers = [
        "Nom", 
        "Prénom", 
        "Email", 
        "Téléphone", 
        "Poste", 
        "Département", 
        "Statut",
        "Date embauche"
    ]
    data.append(headers)
    
    # Données des bibliothécaires
    for bib in bibliothecaires:
        row = [
            bib.nom or '',
            bib.prenom or '',
            bib.email or '',
            bib.telephone or '',
            bib.poste or '',
            bib.departement or '',
            bib.statut or '',
            bib.date_embauche.strftime('%d/%m/%Y') if bib.date_embauche else ''
        ]
        data.append(row)
    
    # Créer le tableau
    table = Table(data, repeatRows=1)
    
    # Style du tableau
    table.setStyle(TableStyle([
        # Style de l'en-tête
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        
        # Bordures
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('BOX', (0, 0), (-1, -1), 2, colors.black),
        
        # Alignement des cellules
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Alternance des couleurs des lignes
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), 
         [colors.white, colors.HexColor('#f8f9fa')]),
        
        # Hauteur des lignes
        ('MINIMUMHEIGHT', (0, 0), (-1, -1), 20),
        
        # Padding
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    # Ajuster la largeur des colonnes
    table._argW = [
        1.5*cm,  # Nom
        1.5*cm,  # Prénom
        3*cm,    # Email
        2*cm,    # Téléphone
        2*cm,    # Poste
        2*cm,    # Département
        1.5*cm,  # Statut
        2*cm     # Date embauche
    ]
    
    story.append(table)
    story.append(Spacer(1, 30))
    
    # Statistiques
    actifs = len([b for b in bibliothecaires if b.statut == 'Actif'])
    inactifs = total - actifs
    
    stats_text = f"""
    <b>STATISTIQUES :</b><br/>
    • Bibliothécaires actifs : {actifs}<br/>
    • Bibliothécaires inactifs : {inactifs}<br/>
    • Total : {total}
    """
    story.append(Paragraph(stats_text, styles['Normal']))
    
    # Pied de page
    story.append(Spacer(1, 50))
    footer_text = f"Export généré le {date_str} - Système de Gestion de Bibliothèque"
    story.append(Paragraph(footer_text, ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1
    )))
    
    # Générer le PDF
    doc.build(story)
    
    # Récupérer le PDF depuis le buffer
    pdf = buffer.getvalue()
    buffer.close()
    
    return pdf

def generate_detailed_bibliothecaire_pdf(bibliothecaire):
    """Générer un PDF détaillé pour un bibliothécaire spécifique"""
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    styles = getSampleStyleSheet()
    story = []
    
    # Titre
    story.append(Paragraph(f"FICHE DU BIBLIOTHÉCAIRE", ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=20,
        alignment=1
    )))
    
    # Informations principales
    info_data = [
        [Paragraph("<b>Nom complet :</b>", styles['Normal']), 
         f"{bibliothecaire.prenom} {bibliothecaire.nom}"],
        [Paragraph("<b>Email professionnel :</b>", styles['Normal']), 
         bibliothecaire.email],
        [Paragraph("<b>Téléphone professionnel :</b>", styles['Normal']), 
         bibliothecaire.telephone or 'Non renseigné'],
        [Paragraph("<b>Poste :</b>", styles['Normal']), 
         bibliothecaire.poste],
        [Paragraph("<b>Département :</b>", styles['Normal']), 
         bibliothecaire.departement or 'Non renseigné'],
        [Paragraph("<b>Statut :</b>", styles['Normal']), 
         bibliothecaire.statut],
        [Paragraph("<b>Date d'embauche :</b>", styles['Normal']), 
         bibliothecaire.date_embauche.strftime('%d/%m/%Y') if bibliothecaire.date_embauche else 'Non renseigné'],
    ]
    
    # Informations personnelles (si disponibles)
    if bibliothecaire.date_naissance or bibliothecaire.genre or bibliothecaire.adresse:
        story.append(Spacer(1, 20))
        story.append(Paragraph("INFORMATIONS PERSONNELLES", ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontSize=16,
            spaceAfter=10
        )))
        
        perso_data = []
        if bibliothecaire.date_naissance:
            perso_data.append([
                Paragraph("<b>Date de naissance :</b>", styles['Normal']),
                bibliothecaire.date_naissance.strftime('%d/%m/%Y')
            ])
        if bibliothecaire.genre:
            perso_data.append([
                Paragraph("<b>Genre :</b>", styles['Normal']),
                'Masculin' if bibliothecaire.genre == 'M' else 'Féminin' if bibliothecaire.genre == 'F' else 'Autre'
            ])
        if bibliothecaire.adresse:
            perso_data.append([
                Paragraph("<b>Adresse :</b>", styles['Normal']),
                Paragraph(bibliothecaire.adresse, styles['Normal'])
            ])
        if bibliothecaire.email_personnel:
            perso_data.append([
                Paragraph("<b>Email personnel :</b>", styles['Normal']),
                bibliothecaire.email_personnel
            ])
        if bibliothecaire.telephone_personnel:
            perso_data.append([
                Paragraph("<b>Téléphone personnel :</b>", styles['Normal']),
                bibliothecaire.telephone_personnel
            ])
        
        info_data.extend(perso_data)
    
    # Créer le tableau d'informations
    info_table = Table(info_data, colWidths=[3*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    
    story.append(info_table)
    
    # Description du poste
    if bibliothecaire.description_poste:
        story.append(Spacer(1, 20))
        story.append(Paragraph("DESCRIPTION DU POSTE", ParagraphStyle(
            'Subtitle',
            parent=styles['Heading2'],
            fontSize=16,
            spaceAfter=10
        )))
        story.append(Paragraph(bibliothecaire.description_poste, styles['Normal']))
    
    # Pied de page
    story.append(Spacer(1, 50))
    date_str = datetime.now().strftime("%d/%m/%Y")
    footer_text = f"Document généré le {date_str} - Système de Gestion de Bibliothèque"
    story.append(Paragraph(footer_text, ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1
    )))
    
    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    
    return pdf


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
    return _perform_emprunt(livre_id)


def _perform_emprunt(livre_id):
    """Logique partagée pour effectuer un emprunt (utilisée par plusieurs routes)."""
    livre = Livre.query.get_or_404(livre_id)
    
    if not livre.disponible:
        flash('Ce livre n\'est pas disponible pour le moment', 'error')
        return redirect(url_for('catalogue'))
    
    adherent_id_for_query = getattr(current_user, 'adherent_id', None) or current_user.id

    # Charger la configuration de la bibliothèque
    cfg = get_library_config()

    # Mettre à jour les amendes pour les emprunts en retard (actifs) et calculer total amendes
    try:
        now = datetime.utcnow()
        overdues = Emprunt.query.filter(
            Emprunt.adherent_id == adherent_id_for_query,
            Emprunt.date_retour_effective == None,
            Emprunt.date_retour_prevue < now
        ).all()
        updated = False
        for od in overdues:
            ret_prevue = _to_date(od.date_retour_prevue)
            days_late = (now.date() - ret_prevue).days if ret_prevue is not None else 0
            if days_late > 0:
                new_amende = cfg.amende_par_jour * days_late
            else:
                new_amende = 0.0
            if (od.amende or 0.0) != new_amende:
                od.amende = new_amende
                updated = True
        if updated:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        current_app.logger.exception('Erreur mise à jour amendes en amont emprunt')

    total_amende = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == adherent_id_for_query).scalar() or 0.0

    # Empêcher un nouvel emprunt si l'adhérent a des amendes impayées ou des retards actifs
    has_overdue_active = Emprunt.query.filter(
        Emprunt.adherent_id == adherent_id_for_query,
        Emprunt.date_retour_effective == None,
        Emprunt.date_retour_prevue < datetime.utcnow()
    ).count() > 0
    if total_amende > 0 or has_overdue_active:
        flash('Impossible d\'effectuer un emprunt: adhérent en retard ou amendes impayées', 'error')
        return redirect(url_for('catalogue'))

    # Vérifier le nombre d'emprunts en cours pour cet adhérent
    emprunts_en_cours = Emprunt.query.filter_by(adherent_id=adherent_id_for_query, date_retour_effective=None).count()
    if emprunts_en_cours >= (cfg.max_emprunts or 3):
        flash('Nombre maximum d\'emprunts atteint pour cet adhérent', 'error')
        return redirect(url_for('catalogue'))

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
        date_retour_prevue=datetime.utcnow() + timedelta(days=(cfg.duree_emprunt or 14)),
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


# Route de compatibilité (ancien chemin sans "_livre")
@app.route('/emprunter/<int:livre_id>', methods=['POST'])
@login_required
def emprunter_compat(livre_id):
    return _perform_emprunt(livre_id)

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

# Route d'inscription par défaut (affiche un choix si aucun admin n'existe)
@app.route("/inscription", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    # Vérifier si un administrateur existe déjà
    admin_exists = User.query.filter_by(role='admin').first() is not None

    # Si aucun admin n'existe, afficher la page de choix (permet de créer le premier admin)
    if not admin_exists:
        return render_template('register_choice.html', admin_exists=admin_exists)

    # Sinon, conserver le comportement précédent : inscription adhérent par défaut
    return register_with_type('adherent')


# Route d'inscription générique avec type
@app.route('/inscription/<string:user_type>', methods=['GET', 'POST'])
def register_with_type(user_type):
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    allowed_types = ['adherent', 'bibliothecaire', 'admin']
    if user_type not in allowed_types:
        flash('Type d\'utilisateur invalide', 'danger')
        return redirect(url_for('index'))
    
    # Vérifier si un admin existe déjà (pour éviter les doublons)
    admin_exists = User.query.filter_by(role='admin').first() is not None
    if user_type == 'admin' and admin_exists:
        flash('Un administrateur existe déjà. Contactez l\'administrateur actuel pour créer un nouveau compte admin.', 'warning')
        return redirect(url_for('login'))

    # Choisir le template en fonction du type d'utilisateur
    template = 'register_admin.html' if user_type == 'admin' else 'register_form.html'
    
    if request.method == 'POST':
        # Données du formulaire commun
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Données spécifiques
        nom = request.form.get('nom', '').strip()
        prenom = request.form.get('prenom', '').strip()
        telephone = request.form.get('telephone', '').strip()
        classe = request.form.get('classe', '').strip()
        
        # Validation
        if not username or not email or not password:
            flash('Tous les champs obligatoires doivent être remplis', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
        
        if password != confirm_password:
            flash('Les mots de passe ne correspondent pas', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
        
        # Vérifier l'existence
        if User.query.filter_by(username=username).first():
            flash('Ce nom d\'utilisateur est déjà pris', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
            
        if User.query.filter_by(email=email).first():
            flash('Cette adresse email est déjà utilisée', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
        
        # Validation email
        if not is_valid_email(email):
            flash('Adresse email invalide', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
        
        # Créer l'utilisateur
        confirmed = True if user_type == 'admin' else False
        
        user = User(
            username=username,
            email=email,
            role=user_type,
            confirmed=confirmed
        )
        
        # Configuration de la vérification email pour non-admins
        if not confirmed:
            code = _generate_confirmation_code()
            user.confirmation_code = code
            user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)
        
        user.set_password(password)
        
        # Créer un profil adhérent si nécessaire
        if user_type in ['adherent', 'bibliothecaire']:
            # Réutiliser un adhérent existant si l'email est déjà présent
            existing_adherent = Adherent.query.filter_by(email=email).first()
            if existing_adherent:
                # Ne pas créer de doublon ; attacher l'utilisateur à l'adhérent existant
                adherent = existing_adherent
                # Mettre à jour les champs vides si des valeurs sont fournies
                if nom and (not adherent.nom or adherent.nom.strip() == ''):
                    adherent.nom = nom
                if prenom and (not adherent.prenom or adherent.prenom.strip() == ''):
                    adherent.prenom = prenom
                if telephone and (not adherent.telephone or adherent.telephone.strip() == ''):
                    adherent.telephone = telephone
                if classe and (not adherent.classe or adherent.classe.strip() == ''):
                    adherent.classe = classe
            else:
                adherent = Adherent(
                    nom=nom if nom else username,
                    prenom=prenom if prenom else username,
                    email=email,
                    telephone=telephone if telephone else None,
                    classe=classe if classe else None,
                    statut='Actif'
                )
                db.session.add(adherent)
                # flush only when we created a new adherent to get its id
                try:
                    db.session.flush()
                except IntegrityError:
                    db.session.rollback()
                    # Collision improbable due to race; try to reuse existing record
                    adherent = Adherent.query.filter_by(email=email).first()
                    if not adherent:
                        flash('Erreur lors de la création du profil adhérent (conflit email).', 'danger')
                        return render_template(template, 
                             title=f'Inscription - {user_type.capitalize()}',
                             user_type=user_type,
                             admin_exists=admin_exists)
            user.adherent = adherent
        
        try:
            db.session.add(user)
            db.session.commit()
            
            # Gérer la vérification/notification
            if not confirmed:
                sent = send_verification_email(user.email, user.username, code)
                if sent:
                    flash('Inscription réussie ! Un code de vérification a été envoyé à votre email.', 'success')
                else:
                    flash('Inscription créée, mais impossible d\'envoyer le code. Contactez un administrateur.', 'warning')
                
                return redirect(url_for('verify_email', username=username))
            else:
                # Connexion automatique pour admin
                login_user(user)
                flash('Compte administrateur créé avec succès !', 'success')
                return redirect(url_for('dashboard'))
                
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'inscription: {str(e)}', 'danger')
            return render_template(template, 
                                 title=f'Inscription',
                                 user_type=user_type,
                                 admin_exists=admin_exists)
    
    # GET request
    return render_template(template, 
                         title=f'Inscription',
                         user_type=user_type,
                         admin_exists=admin_exists)

# CONNEXION
@app.route("/connexion", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('catalogue'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user:
            if user.check_password(password):
                if not user.confirmed and user.role != 'admin':
                    # Générer et envoyer un nouveau code
                    code = _generate_confirmation_code()
                    user.confirmation_code = code
                    user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)
                    
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    
                    sent = send_verification_email(user.email, user.username, code)
                    if sent:
                        flash('Un code de vérification a été envoyé à votre email. Vérifiez votre boîte et entrez le code.', 'info')
                    else:
                        flash('Impossible d\'envoyer le code de vérification. Contactez un administrateur.', 'warning')
                    
                    return redirect(url_for('verify_email', username=username))

                login_user(user)
                flash('Connexion réussie!', 'success')
                
                # Redirection selon le rôle
                if has_roles('admin', 'bibliothecaire'):
                    return redirect(url_for('dashboard'))
                else:
                    return redirect(url_for('catalogue'))
            else:
                flash('Mot de passe incorrect', 'danger')
        else:
            flash('Nom d\'utilisateur non trouvé', 'danger')

    return render_template("login.html", title="Connexion")

@app.context_processor
def inject_admin_exists():
    """Injecte la variable admin_exists dans tous les templates"""
    admin_exists = User.query.filter_by(role='admin').first() is not None
    return dict(admin_exists=admin_exists)

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
    # Admin dashboard
    if has_roles('admin'):
        total_livres = Livre.query.count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        total_adherents = Adherent.query.count()
        total_bibliothecaires = Bibliothecaire.query.count()
        emprunts_en_cours = Emprunt.query.filter_by(status='en_cours').count()
        adherents_actifs = db.session.query(Adherent).join(Emprunt).distinct().count()

        return render_template(
            "dashboard_admin.html",
            title="Dashboard",
            user=current_user,
            total_livres=total_livres,
            livres_disponibles=livres_disponibles,
            total_adherents=total_adherents,
            total_bibliothecaires=total_bibliothecaires,
            emprunts_en_cours=emprunts_en_cours,
            adherents_actifs=adherents_actifs,
            timedelta=timedelta,
            now=datetime.utcnow()
        )

    # Bibliothécaire dashboard
    if has_roles('bibliothecaire'):
        total_livres = Livre.query.count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        total_adherents = Adherent.query.count()
        retards_totaux = Emprunt.query.filter(
            Emprunt.date_retour_effective == None,
            Emprunt.date_retour_prevue < datetime.utcnow()
        ).count()
        reservations_en_attente = Reservation.query.filter_by(status='active').count()
        
        # Livres à retourner demain
        tomorrow = datetime.utcnow() + timedelta(days=1)
        tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
        livres_bientot_retour = Emprunt.query.filter(
            Emprunt.date_retour_effective == None,
            Emprunt.date_retour_prevue >= tomorrow_start,
            Emprunt.date_retour_prevue <= tomorrow_end
        ).count()

        return render_template(
            "dashboard_bibliothecaire.html",
            title="Dashboard",
            user=current_user,
            total_livres=total_livres,
            livres_disponibles=livres_disponibles,
            total_adherents=total_adherents,
            retards_totaux=retards_totaux,
            reservations_en_attente=reservations_en_attente,
            livres_bientot_retour=livres_bientot_retour,
            timedelta=timedelta,
            now=datetime.utcnow()
        )

    # Adherent / utilisateur normal
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
        "dashboard_adherent.html",
        title="Mon tableau de bord",
        user=current_user,
        total_emprunts_user=total_emprunts_user,
        emprunts_en_cours_user=emprunts_en_cours_user,
        retards_user=retards_user,
        total_amende_user=total_amende_user,
        timedelta=timedelta,
        now=datetime.utcnow()
    )

# ROUTES ADMIN
@app.route("/dashboard/adherents", methods=['GET', 'POST'])
@login_required
def adherents():
    if not has_roles('admin', 'bibliothecaire'):
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
                # Allow admin to choose role for the created user (default to 'user')
                role_selected = (request.form.get('role') or 'user').strip()
                if role_selected not in ('user', 'bibliothecaire', 'admin'):
                    role_selected = 'user'
                # Bibliothécaires ne peuvent pas créer des comptes avec un rôle autre que 'user'
                if current_user.role == 'bibliothecaire':
                    role_selected = 'user'

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

                # Validate email format before creating user
                if not is_valid_email(nouveau_adherent.email):
                    try:
                        db.session.delete(nouveau_adherent)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    flash('Adresse email invalide. Veuillez saisir une adresse email valide.', 'danger')
                    return redirect(url_for('adherents'))

                try:
                    # Admin accounts are auto-confirmed; others receive a verification code
                    confirmed_flag = True if role_selected == 'admin' else False
                    user = User(username=username, email=nouveau_adherent.email, role=role_selected, confirmed=confirmed_flag)
                    # If not admin, prepare confirmation code
                    if not confirmed_flag:
                        code = _generate_confirmation_code()
                        user.confirmation_code = code
                        user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)

                    user.set_password(password if password else uuid.uuid4().hex)
                    user.adherent = nouveau_adherent
                    db.session.add(user)
                    db.session.commit()

                    # Send verification email to non-admin users
                    if not confirmed_flag:
                        sent = send_verification_email(user.email, user.username, user.confirmation_code)
                        if sent:
                            flash('Adhérent et compte créés. Un code de vérification a été envoyé au nouvel utilisateur.', 'success')
                        else:
                            flash('Adhérent créé, mais impossible d\'envoyer le code de vérification par email.', 'warning')
                    else:
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
    if not has_roles('admin', 'bibliothecaire'):
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

                # Allow admin to choose role for the created user (default 'user')
                role_selected = (request.form.get('role') or 'user').strip()
                if role_selected not in ('user', 'bibliothecaire', 'admin'):
                    role_selected = 'user'
                # Bibliothécaires ne peuvent pas créer des comptes avec un rôle autre que 'user'
                if current_user.role == 'bibliothecaire':
                    role_selected = 'user'

                existing_user = User.query.filter((User.username == username) | (User.email == nouveau_adherent.email)).first()
                if existing_user:
                    db.session.delete(nouveau_adherent)
                    db.session.commit()
                    flash('Un utilisateur avec ce nom d\'utilisateur ou cet email existe d\'j\u00e0. Opération annul\u00e9e.', 'danger')
                    return redirect(url_for('new_adherent'))

                # Validate email format before creating user
                if not is_valid_email(nouveau_adherent.email):
                    try:
                        db.session.delete(nouveau_adherent)
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                    flash('Adresse email invalide. Veuillez saisir une adresse email valide.', 'danger')
                    return redirect(url_for('new_adherent'))

                try:
                    confirmed_flag = True if role_selected == 'admin' else False
                    user = User(username=username, email=nouveau_adherent.email, role=role_selected, confirmed=confirmed_flag)
                    if not confirmed_flag:
                        code = _generate_confirmation_code()
                        user.confirmation_code = code
                        user.confirmation_expires = datetime.utcnow() + timedelta(minutes=30)

                    user.set_password(password if password else uuid.uuid4().hex)
                    user.adherent = nouveau_adherent
                    db.session.add(user)
                    db.session.commit()

                    if not confirmed_flag:
                        sent = send_verification_email(user.email, user.username, user.confirmation_code)
                        if sent:
                            flash('Adhérent et compte créés. Un code de vérification a été envoyé au nouvel utilisateur.', 'success')
                        else:
                            flash('Adhérent créé, mais impossible d\'envoyer le code de vérification par email.', 'warning')
                    else:
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
    # Mettre à jour et calculer les amendes courantes pour l'adhérent
    try:
        cfg = get_library_config()
        now = datetime.utcnow()
        overdues = Emprunt.query.filter(
            Emprunt.adherent_id == a.id,
            Emprunt.date_retour_effective == None,
            Emprunt.date_retour_prevue < now
        ).all()
        updated = False
        for od in overdues:
            ret_prevue = _to_date(od.date_retour_prevue)
            days_late = (now.date() - ret_prevue).days if ret_prevue is not None else 0
            if days_late > 0:
                new_amende = cfg.amende_par_jour * days_late
            else:
                new_amende = 0.0
            if (od.amende or 0.0) != new_amende:
                od.amende = new_amende
                updated = True
        if updated:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        current_app.logger.exception('Erreur calcul amendes vue adherent')

    total_amende = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == a.id).scalar() or 0.0

    return render_template('adherent_view.html', title=f"Adhérent {a.nom}", adherent=a, total_amende=total_amende)

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
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # Gestion création d'un nouvel emprunt via le formulaire (bibliothécaire)
        adherent_id = request.form.get('adherent_id')
        livre_id = request.form.get('livre_id')
        date_retour_str = request.form.get('date_retour')

        if not adherent_id or not livre_id or not date_retour_str:
            flash('Tous les champs obligatoires doivent être remplis', 'danger')
            return redirect(url_for('emprunts'))

        try:
            adherent = Adherent.query.get(int(adherent_id))
            livre = Livre.query.get(int(livre_id))
            date_retour_prevue = datetime.strptime(date_retour_str, '%Y-%m-%d')

            if not adherent or not livre:
                flash('Adhérent ou livre introuvable', 'danger')
                return redirect(url_for('emprunts'))

            if not livre.disponible:
                flash('Le livre sélectionné n\'est pas disponible', 'danger')
                return redirect(url_for('emprunts'))

            # Vérifier qu'il n'y a pas déjà un emprunt actif pour ce livre
            emprunt_actif = Emprunt.query.filter_by(livre_id=livre.id, date_retour_effective=None).first()
            if emprunt_actif:
                flash('Le livre est déjà emprunté', 'danger')
                return redirect(url_for('emprunts'))

            nouvel_emprunt = Emprunt(
                adherent_id=adherent.id,
                livre_id=livre.id,
                date_retour_prevue=date_retour_prevue,
                status='en_cours'
            )

            livre.disponible = False

            db.session.add(nouvel_emprunt)
            db.session.commit()
            flash(f'Emprunt créé: "{livre.titre}" pour {adherent.nom} {adherent.prenom}', 'success')
            return redirect(url_for('emprunts'))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Erreur lors de la création de l\'emprunt')
            flash('Erreur lors de la création de l\'emprunt', 'danger')
            return redirect(url_for('emprunts'))

    emprunts_liste = Emprunt.query.all()
    adherents_liste = Adherent.query.all()
    livres_disponibles = Livre.query.filter_by(disponible=True).all()
    reservations_liste = Reservation.query.order_by(Reservation.date_reservation.desc()).all()
    cfg = get_library_config()

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
        ,library_settings={
            'duree_emprunt': cfg.duree_emprunt,
            'max_emprunts': cfg.max_emprunts,
            'max_prolongations': cfg.max_prolongations,
            'jours_prolongation': cfg.jours_prolongation,
            'amende_par_jour': cfg.amende_par_jour
        }
    )

# ============================================
# ROUTES POUR LES BIBLIOTHÉCAIRES
# ============================================

@app.route("/dashboard/bibliothecaires")
@login_required
@role_required(['admin'])
def bibliothecaires():
    """Page principale de gestion des bibliothécaires"""
    
    # Récupérer les paramètres de filtre
    recherche = request.args.get('recherche', '').strip()
    poste = request.args.get('poste', '')
    statut = request.args.get('statut', '')
    page = request.args.get('page', 1, type=int)
    
    # Construire la requête
    query = Bibliothecaire.query
    
    # Filtre de recherche
    if recherche:
        recherche_pattern = f"%{recherche}%"
        query = query.filter(
            db.or_(
                Bibliothecaire.nom.ilike(recherche_pattern),
                Bibliothecaire.prenom.ilike(recherche_pattern),
                Bibliothecaire.email.ilike(recherche_pattern),
                Bibliothecaire.telephone.ilike(recherche_pattern)
            )
        )
    
    # Filtre par poste
    if poste:
        query = query.filter(Bibliothecaire.poste == poste)
    
    # Filtre par statut
    if statut:
        query = query.filter(Bibliothecaire.statut == statut)
    
    # Pagination
    per_page = 10
    pagination = query.order_by(Bibliothecaire.nom.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return render_template(
        "bibliothecaires.html",
        title="Bibliothécaires",
        bibliothecaires=pagination.items,
        pagination=pagination,
        recherche=recherche,
        poste=poste,
        statut=statut
    )


@app.route("/dashboard/bibliothecaires/new")
@login_required
@role_required(['admin'])
def new_bibliothecaire():
    """Page pour créer un nouveau bibliothécaire"""
    return render_template(
        "new_bibliothecaire.html",
        title="Nouveau bibliothécaire"
    )


@app.route("/dashboard/bibliothecaires/create", methods=['POST'])
@login_required
@role_required(['admin'])
def create_bibliothecaire():
    """Créer un nouveau bibliothécaire"""
    try:
        # Récupérer les données du formulaire
        nom = request.form.get('nom', '').strip()
        prenom = request.form.get('prenom', '').strip()
        email = request.form.get('email', '').strip()
        telephone = request.form.get('telephone', '').strip()
        poste = request.form.get('poste', 'Bibliothécaire').strip()
        departement = request.form.get('departement', '').strip()
        date_embauche_str = request.form.get('date_embauche', '').strip()
        statut = request.form.get('statut', 'Actif').strip()
        date_naissance_str = request.form.get('date_naissance', '').strip()
        genre = request.form.get('genre', '').strip()
        adresse = request.form.get('adresse', '').strip()
        email_personnel = request.form.get('email_personnel', '').strip()
        telephone_personnel = request.form.get('telephone_personnel', '').strip()
        description_poste = request.form.get('description_poste', '').strip()
        
        # Validation des champs obligatoires
        if not nom or not prenom or not email or not poste:
            flash('Les champs Nom, Prénom, Email et Poste sont obligatoires', 'danger')
            return redirect(url_for('new_bibliothecaire'))
        
        # Vérifier l'unicité de l'email
        if Bibliothecaire.query.filter_by(email=email).first():
            flash('Un bibliothécaire avec cet email existe déjà', 'danger')
            return redirect(url_for('new_bibliothecaire'))
        
        # Convertir les dates
        date_embauche = None
        if date_embauche_str:
            try:
                date_embauche = datetime.strptime(date_embauche_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Format de date d\'embauche invalide', 'danger')
                return redirect(url_for('new_bibliothecaire'))
        
        date_naissance = None
        if date_naissance_str:
            try:
                date_naissance = datetime.strptime(date_naissance_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Format de date de naissance invalide', 'danger')
                return redirect(url_for('new_bibliothecaire'))
        
        # Créer le bibliothécaire
        nouveau_bibliothecaire = Bibliothecaire(
            nom=nom,
            prenom=prenom,
            email=email,
            telephone=telephone,
            poste=poste,
            departement=departement,
            date_embauche=date_embauche,
            statut=statut,
            date_naissance=date_naissance,
            genre=genre,
            adresse=adresse,
            email_personnel=email_personnel,
            telephone_personnel=telephone_personnel,
            description_poste=description_poste
        )
        
        # Gérer l'upload de l'image
        photo = request.files.get('photo')
        if photo and photo.filename:
            filename = secure_filename(photo.filename)
            if filename:
                unique_filename = f"{uuid.uuid4().hex}_{filename}"
                photo_path = os.path.join(app.config['PROFILE_FOLDER'], unique_filename)
                photo.save(photo_path)
                nouveau_bibliothecaire.image = unique_filename
        
        db.session.add(nouveau_bibliothecaire)
        db.session.flush()  # Pour obtenir l'ID
        
        # Créer un compte utilisateur si demandé
        if request.form.get('creer_compte') == 'on':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '').strip()
            confirm_password = request.form.get('confirm_password', '').strip()
            role = request.form.get('role', 'bibliothecaire').strip()
            
            # Validation du compte utilisateur
            if not username or not password:
                flash('Pour créer un compte, le nom d\'utilisateur et le mot de passe sont obligatoires', 'danger')
                db.session.rollback()
                return redirect(url_for('new_bibliothecaire'))
            
            if password != confirm_password:
                flash('Les mots de passe ne correspondent pas', 'danger')
                db.session.rollback()
                return redirect(url_for('new_bibliothecaire'))
            
            # Vérifier si l'utilisateur existe déjà
            if User.query.filter_by(username=username).first():
                flash('Ce nom d\'utilisateur est déjà pris', 'danger')
                db.session.rollback()
                return redirect(url_for('new_bibliothecaire'))
            
            if User.query.filter_by(email=email).first():
                flash('Un compte avec cet email existe déjà', 'danger')
                db.session.rollback()
                return redirect(url_for('new_bibliothecaire'))
            
            # Créer l'utilisateur
            user = User(
                username=username,
                email=email,
                role=role,
                confirmed=True  # Les bibliothécaires sont confirmés automatiquement
            )
            user.set_password(password)
            user.bibliothecaire = nouveau_bibliothecaire
            db.session.add(user)
            
            # Envoyer un email de bienvenue
            try:
                msg = EmailMessage()
                msg['Subject'] = 'Bienvenue dans l\'équipe de la bibliothèque'
                msg['From'] = app.config['EMAIL_FROM']
                msg['To'] = email
                
                msg.set_content(f"""
                Bonjour {prenom} {nom},
                
                Votre compte bibliothécaire a été créé avec succès.
                
                Informations de connexion :
                - Nom d\'utilisateur : {username}
                - Mot de passe : [celui que vous avez défini]
                - Rôle : {role}
                
                Vous pouvez vous connecter à l\'adresse : {request.host_url}connexion
                
                Cordialement,
                L\'équipe de la Bibliothèque
                """)
                
                with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
                    if app.config['MAIL_USE_TLS']:
                        server.starttls()
                    server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
                    server.send_message(msg)
            except Exception as e:
                current_app.logger.error(f"Erreur lors de l'envoi de l'email de bienvenue : {str(e)}")
                # Ne pas bloquer la création si l'email échoue
        
        db.session.commit()
        flash('Bibliothécaire créé avec succès', 'success')
        
        # Rediriger vers la page de détails ou la liste
        return redirect(url_for('view_bibliothecaire', id=nouveau_bibliothecaire.id))
        
    except IntegrityError:
        db.session.rollback()
        flash('Erreur : l\'email est déjà utilisé', 'danger')
        return redirect(url_for('new_bibliothecaire'))
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Erreur lors de la création du bibliothécaire')
        flash(f'Erreur lors de la création : {str(e)}', 'danger')
        return redirect(url_for('new_bibliothecaire'))


@app.route("/dashboard/bibliothecaires/<int:id>")
@login_required
@role_required(['admin'])
def view_bibliothecaire(id):
    """Voir les détails d'un bibliothécaire"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    # Récupérer les statistiques du bibliothécaire (si gestion des emprunts)
    emprunts_geres = Emprunt.query.filter(
        Emprunt.status == 'en_cours'
    ).count() if hasattr(bibliothecaire, 'emprunts_geres') else 0
    
    return render_template(
        "view_bibliothecaire.html",
        title=f"Bibliothécaire {bibliothecaire.prenom} {bibliothecaire.nom}",
        bibliothecaire=bibliothecaire,
        emprunts_geres=emprunts_geres,
        now=datetime.now()
    )


@app.route("/dashboard/bibliothecaires/<int:id>/edit", methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def edit_bibliothecaire(id):
    """Modifier un bibliothécaire"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Mettre à jour les informations
            bibliothecaire.nom = request.form.get('nom', bibliothecaire.nom).strip()
            bibliothecaire.prenom = request.form.get('prenom', bibliothecaire.prenom).strip()
            bibliothecaire.email = request.form.get('email', bibliothecaire.email).strip()
            bibliothecaire.telephone = request.form.get('telephone', bibliothecaire.telephone).strip()
            bibliothecaire.poste = request.form.get('poste', bibliothecaire.poste).strip()
            bibliothecaire.departement = request.form.get('departement', bibliothecaire.departement).strip()
            bibliothecaire.statut = request.form.get('statut', bibliothecaire.statut).strip()
            
            # Gérer les dates
            date_embauche_str = request.form.get('date_embauche', '').strip()
            if date_embauche_str:
                try:
                    bibliothecaire.date_embauche = datetime.strptime(date_embauche_str, '%Y-%m-%d').date()
                except ValueError:
                    flash('Format de date d\'embauche invalide', 'danger')
            
            date_naissance_str = request.form.get('date_naissance', '').strip()
            if date_naissance_str:
                try:
                    bibliothecaire.date_naissance = datetime.strptime(date_naissance_str, '%Y-%m-%d').date()
                except ValueError:
                    flash('Format de date de naissance invalide', 'danger')
            
            # Autres champs
            bibliothecaire.genre = request.form.get('genre', bibliothecaire.genre).strip()
            bibliothecaire.adresse = request.form.get('adresse', bibliothecaire.adresse).strip()
            bibliothecaire.email_personnel = request.form.get('email_personnel', bibliothecaire.email_personnel).strip()
            bibliothecaire.telephone_personnel = request.form.get('telephone_personnel', bibliothecaire.telephone_personnel).strip()
            bibliothecaire.description_poste = request.form.get('description_poste', bibliothecaire.description_poste).strip()
            
            # Gérer l'upload de la photo
            photo = request.files.get('photo')
            if photo and photo.filename:
                filename = secure_filename(photo.filename)
                if filename:
                    # Supprimer l'ancienne photo si elle existe
                    if bibliothecaire.image:
                        old_photo_path = os.path.join(app.config['PROFILE_FOLDER'], bibliothecaire.image)
                        if os.path.exists(old_photo_path):
                            os.remove(old_photo_path)
                    
                    unique_filename = f"{uuid.uuid4().hex}_{filename}"
                    photo_path = os.path.join(app.config['PROFILE_FOLDER'], unique_filename)
                    photo.save(photo_path)
                    bibliothecaire.image = unique_filename
            
            db.session.commit()
            flash('Bibliothécaire mis à jour avec succès', 'success')
            return redirect(url_for('view_bibliothecaire', id=bibliothecaire.id))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.exception('Erreur lors de la mise à jour du bibliothécaire')
            flash(f'Erreur lors de la mise à jour : {str(e)}', 'danger')
    
    return render_template(
        "edit_bibliothecaire.html",
        title=f"Modifier {bibliothecaire.prenom} {bibliothecaire.nom}",
        bibliothecaire=bibliothecaire
    )


@app.route("/dashboard/bibliothecaires/<int:id>/delete", methods=['POST'])
@login_required
@role_required(['admin'])
def delete_bibliothecaire(id):
    """Supprimer un bibliothécaire"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    try:
        # Supprimer la photo si elle existe
        if bibliothecaire.image:
            photo_path = os.path.join(app.config['PROFILE_FOLDER'], bibliothecaire.image)
            if os.path.exists(photo_path):
                os.remove(photo_path)
        
        # Supprimer le compte utilisateur associé s'il existe
        user = User.query.filter_by(bibliothecaire_id=id).first()
        if user:
            db.session.delete(user)
        
        # Supprimer le bibliothécaire
        db.session.delete(bibliothecaire)
        db.session.commit()
        
        flash('Bibliothécaire supprimé avec succès', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Erreur lors de la suppression du bibliothécaire')
        flash(f'Erreur lors de la suppression : {str(e)}', 'danger')
    
    return redirect(url_for('bibliothecaires'))


@app.route("/dashboard/bibliothecaires/export/<format>")
@login_required
@role_required(['admin'])
def export_bibliothecaires(format):
    """Exporter la liste des bibliothécaires"""
    
    # Récupérer les mêmes filtres que pour l'affichage
    recherche = request.args.get('recherche', '').strip()
    poste = request.args.get('poste', '')
    statut = request.args.get('statut', '')
    
    # Construire la requête avec les mêmes filtres
    query = Bibliothecaire.query
    
    if recherche:
        recherche_pattern = f"%{recherche}%"
        query = query.filter(
            db.or_(
                Bibliothecaire.nom.ilike(recherche_pattern),
                Bibliothecaire.prenom.ilike(recherche_pattern),
                Bibliothecaire.email.ilike(recherche_pattern),
                Bibliothecaire.telephone.ilike(recherche_pattern)
            )
        )
    
    if poste:
        query = query.filter(Bibliothecaire.poste == poste)
    
    if statut:
        query = query.filter(Bibliothecaire.statut == statut)
    
    bibliothecaires = query.order_by(Bibliothecaire.nom.asc()).all()
    
    if format == 'csv':
        # Générer un CSV simple
        si = StringIO()
        writer = csv.writer(si)
        
        # En-têtes
        writer.writerow(['Nom', 'Prénom', 'Email', 'Téléphone', 'Poste', 
                        'Département', 'Statut', 'Date d\'embauche'])
        
        # Données
        for bib in bibliothecaires:
            writer.writerow([
                bib.nom,
                bib.prenom,
                bib.email,
                bib.telephone or '',
                bib.poste or '',
                bib.departement or '',
                bib.statut or '',
                bib.date_embauche.strftime('%d/%m/%Y') if bib.date_embauche else ''
            ])
        
        output = si.getvalue()
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-disposition": 
                    f"attachment; filename=bibliothecaires_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
        )
    
    elif format == 'pdf':
        try:
            pdf = generate_bibliothecaires_pdf(bibliothecaires)
            
            filename = f"bibliothecaires_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            
            return Response(
                pdf,
                mimetype="application/pdf",
                headers={
                    "Content-disposition": f"attachment; filename={filename}",
                    "Content-Type": "application/pdf"
                }
            )
        except Exception as e:
            current_app.logger.error(f"Erreur lors de la génération du PDF : {str(e)}")
            flash(f'Erreur lors de la génération du PDF : {str(e)}', 'danger')
            return redirect(url_for('bibliothecaires'))
    
    flash('Format d\'export non supporté', 'danger')
    return redirect(url_for('bibliothecaires'))


@app.route("/dashboard/bibliothecaires/<int:id>/toggle_status", methods=['POST'])
@login_required
@role_required(['admin'])
def toggle_bibliothecaire_status(id):
    """Activer/désactiver un bibliothécaire"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    try:
        if bibliothecaire.statut == 'Actif':
            bibliothecaire.statut = 'Inactif'
            message = 'Bibliothécaire désactivé'
        else:
            bibliothecaire.statut = 'Actif'
            message = 'Bibliothécaire activé'
        
        db.session.commit()
        flash(f'{message} avec succès', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors du changement de statut : {str(e)}', 'danger')
    
    return redirect(url_for('view_bibliothecaire', id=id))


@app.route("/dashboard/bibliothecaires/<int:id>/create_account", methods=['POST'])
@login_required
@role_required(['admin'])
def create_bibliothecaire_account(id):
    """Créer un compte utilisateur pour un bibliothécaire existant"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    # Vérifier si un compte existe déjà
    user = User.query.filter_by(bibliothecaire_id=id).first()
    if user:
        flash('Ce bibliothécaire a déjà un compte utilisateur', 'warning')
        return redirect(url_for('view_bibliothecaire', id=id))
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    role = request.form.get('role', 'bibliothecaire').strip()
    
    # Validation
    if not username or not password:
        flash('Le nom d\'utilisateur et le mot de passe sont obligatoires', 'danger')
        return redirect(url_for('view_bibliothecaire', id=id))
    
    if password != confirm_password:
        flash('Les mots de passe ne correspondent pas', 'danger')
        return redirect(url_for('view_bibliothecaire', id=id))
    
    if User.query.filter_by(username=username).first():
        flash('Ce nom d\'utilisateur est déjà pris', 'danger')
        return redirect(url_for('view_bibliothecaire', id=id))
    
    try:
        # Créer l'utilisateur
        user = User(
            username=username,
            email=bibliothecaire.email,
            role=role,
            confirmed=True
        )
        user.set_password(password)
        user.bibliothecaire = bibliothecaire
        
        db.session.add(user)
        db.session.commit()
        
        flash('Compte utilisateur créé avec succès', 'success')
        
        # Envoyer un email avec les informations de connexion
        try:
            msg = EmailMessage()
            msg['Subject'] = 'Votre compte bibliothécaire a été créé'
            msg['From'] = app.config['EMAIL_FROM']
            msg['To'] = bibliothecaire.email
            
            msg.set_content(f"""
            Bonjour {bibliothecaire.prenom} {bibliothecaire.nom},
            
            Un compte utilisateur a été créé pour vous sur le système de la bibliothèque.
            
            Informations de connexion :
            - Nom d\'utilisateur : {username}
            - Mot de passe : [celui qui a été défini]
            
            Vous pouvez vous connecter à l\'adresse : {request.host_url}connexion
            
            Cordialement,
            L\'équipe de la Bibliothèque
            """)
            
            with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT']) as server:
                if app.config['MAIL_USE_TLS']:
                    server.starttls()
                server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
                server.send_message(msg)
        except Exception as e:
            current_app.logger.error(f"Erreur lors de l'envoi de l'email : {str(e)}")
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la création du compte : {str(e)}', 'danger')
    
    return redirect(url_for('view_bibliothecaire', id=id))

@app.route("/dashboard/bibliothecaires/<int:id>/export_pdf")
@login_required
@role_required(['admin'])
def export_bibliothecaire_pdf(id):
    """Exporter la fiche d'un bibliothécaire en PDF"""
    bibliothecaire = Bibliothecaire.query.get_or_404(id)
    
    try:
        pdf = generate_detailed_bibliothecaire_pdf(bibliothecaire)
        
        filename = f"bibliothecaire_{bibliothecaire.nom}_{bibliothecaire.prenom}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return Response(
            pdf,
            mimetype="application/pdf",
            headers={
                "Content-disposition": f"attachment; filename={filename}",
                "Content-Type": "application/pdf"
            }
        )
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la génération du PDF : {str(e)}")
        flash(f'Erreur lors de la génération du PDF : {str(e)}', 'danger')
        return redirect(url_for('view_bibliothecaire', id=id))

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
    if not has_roles('admin', 'bibliothecaire'):
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
    if not has_roles('admin', 'bibliothecaire') and r.adherent_id != owner_adherent_id:
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
    
    if has_roles('admin', 'bibliothecaire'):
        return redirect(url_for('reservations_list'))
    return redirect(url_for('mes_reservations'))

@app.route('/dashboard/reservations/fulfill/<int:res_id>', methods=['POST'])
@login_required
def fulfill_reservation(res_id):
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    r = Reservation.query.get_or_404(res_id)
    if r.status != 'active':
        flash('Réservation non active', 'warning')
        return redirect(url_for('reservations_list'))

    if not r.livre.disponible:
        flash('Livre non disponible pour prêt', 'danger')
        return redirect(url_for('reservations_list'))

    cfg = get_library_config()
    # Vérifier amendes/retards pour l'adhérent de la réservation
    try:
        now = datetime.utcnow()
        overdues = Emprunt.query.filter(
            Emprunt.adherent_id == r.adherent_id,
            Emprunt.date_retour_effective == None,
            Emprunt.date_retour_prevue < now
        ).all()
        updated = False
        for od in overdues:
            ret_prevue = _to_date(od.date_retour_prevue)
            days_late = (now.date() - ret_prevue).days if ret_prevue is not None else 0
            new_amende = cfg.amende_par_jour * days_late if days_late > 0 else 0.0
            if (od.amende or 0.0) != new_amende:
                od.amende = new_amende
                updated = True
        if updated:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        total_amende_for_adherent = db.session.query(db.func.coalesce(db.func.sum(Emprunt.amende), 0.0)).filter(Emprunt.adherent_id == r.adherent_id).scalar() or 0.0
        if total_amende_for_adherent > 0 or len(overdues) > 0:
            flash('Impossible de transformer la réservation en emprunt: adhérent en retard ou amendes impayées', 'danger')
            return redirect(url_for('reservations_list'))
    except Exception:
        current_app.logger.exception('Erreur vérification amendes fulfil reservation')

    empr = Emprunt(adherent_id=r.adherent_id, livre_id=r.livre_id, date_retour_prevue=datetime.utcnow() + timedelta(days=(cfg.duree_emprunt or 14)), status='en_cours')
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
    if not has_roles('admin', 'bibliothecaire'):
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
    if not has_roles('admin', 'bibliothecaire'):
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
    emprunt = Emprunt.query.get_or_404(emprunt_id)
    # Autoriser le bibliothécaire/admin ou l'adhérent propriétaire à marquer le retour
    allowed = has_roles('admin', 'bibliothecaire') or (
        current_user.is_authenticated and getattr(current_user, 'adherent', None) and current_user.adherent.id == emprunt.adherent_id
    )
    if not allowed:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
    emprunt.status = 'retourne'
    emprunt.date_retour_effective = datetime.utcnow()
    # Calculer l'amende si retour en retard
    try:
        cfg = get_library_config()
        if emprunt.date_retour_prevue and emprunt.date_retour_effective:
            ret_eff = _to_date(emprunt.date_retour_effective)
            ret_prevue = _to_date(emprunt.date_retour_prevue)
            if ret_eff is not None and ret_prevue is not None:
                days_late = (ret_eff - ret_prevue).days
            else:
                days_late = 0
            if days_late > 0:
                emprunt.amende = cfg.amende_par_jour * days_late
            else:
                emprunt.amende = 0.0
    except Exception:
        current_app.logger.exception('Erreur calcul amende')
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
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))
        
    emprunt = Emprunt.query.get_or_404(emprunt_id)
    try:
        cfg = get_library_config()
        if emprunt.date_retour_effective:
            flash('Impossible de prolonger un emprunt déjà retourné.', 'warning')
            return redirect(url_for('emprunts'))
        if emprunt.prolongations >= (cfg.max_prolongations or 2):
            flash('Nombre maximum de prolongations atteint.', 'warning')
            return redirect(url_for('emprunts'))
        emprunt.prolongations = emprunt.prolongations + 1
        emprunt.date_retour_prevue = emprunt.date_retour_prevue + timedelta(days=(cfg.jours_prolongation or 7))
        db.session.commit()
        flash(f'Prolongation effectuée (+{cfg.jours_prolongation or 7} jours)', 'success')
    except Exception:
        db.session.rollback()
        flash('Erreur lors de la prolongation', 'danger')
    return redirect(url_for('emprunts'))

@app.route('/dashboard/emprunts/<int:emprunt_id>')
@login_required
def view_emprunt(emprunt_id):
    e = Emprunt.query.get_or_404(emprunt_id)
    # Autoriser bibliothécaire/admin ou l'adhérent propriétaire à voir le détail
    allowed = has_roles('admin', 'bibliothecaire') or (
        current_user.is_authenticated and getattr(current_user, 'adherent', None) and current_user.adherent.id == e.adherent_id
    )
    if not allowed:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    is_staff = has_roles('admin', 'bibliothecaire')
    return render_template('emprunt_detail.html', title=f"Emprunt {e.id}", emprunt=e, is_staff=is_staff)

# STATISTIQUES
@app.route("/dashboard/statistiques")
@login_required
def statistiques():
    if has_roles('admin', 'bibliothecaire'):
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
        total_bibliothecaires = Bibliothecaire.query.count()
        emprunts_en_cours = Emprunt.query.filter(Emprunt.date_emprunt >= start).filter_by(status='en_cours').count()
        livres_disponibles = Livre.query.filter_by(disponible=True).count()
        
        # Récupérer TOUTES les catégories distinctes de livres
        toutes_categories = db.session.query(Livre.categorie).distinct().all()
        toutes_categories = [c[0] for c in toutes_categories if c[0]]  # Nettoyer les valeurs None
        
        # Récupérer les emprunts par catégorie pour la période
        emprunts_par_categorie = db.session.query(
            Livre.categorie, 
            db.func.count(Emprunt.id).label('count')
        ).join(Emprunt).filter(Emprunt.date_emprunt >= start).group_by(Livre.categorie).all()
        
        # Créer un dictionnaire pour les emprunts par catégorie
        emprunts_dict = {categorie: count for categorie, count in emprunts_par_categorie}
        
        # Calculer le nombre total de livres par catégorie
        livres_par_categorie = db.session.query(
            Livre.categorie,
            db.func.count(Livre.id).label('total_livres')
        ).group_by(Livre.categorie).all()
        
        livres_dict = {categorie: count for categorie, count in livres_par_categorie}
        
        # Préparer les statistiques pour TOUTES les catégories
        stats_categories = []
        for categorie in toutes_categories:
            emprunts_cat = emprunts_dict.get(categorie, 0)
            total_livres_cat = livres_dict.get(categorie, 0)
            
            # Pourcentage d'emprunts dans cette catégorie
            pourcentage_emprunts = round((emprunts_cat / max(emprunts_en_cours, 1)) * 100) if emprunts_en_cours > 0 else 0
            
            # Pourcentage de disponibilité par catégorie
            livres_cat = Livre.query.filter_by(categorie=categorie).all()
            livres_cat_ids = [l.id for l in livres_cat]
            livres_dispo_cat = Livre.query.filter(
                Livre.id.in_(livres_cat_ids),
                Livre.disponible == True
            ).count() if livres_cat_ids else 0
            
            pourcentage_dispo = round((livres_dispo_cat / max(total_livres_cat, 1)) * 100) if total_livres_cat > 0 else 100
            
            stats_categories.append({
                'categorie': categorie,
                'count_livres': total_livres_cat,
                'count_emprunts': emprunts_cat,
                'pourcentage_emprunts': pourcentage_emprunts,
                'livres_disponibles': livres_dispo_cat,
                'pourcentage_dispo': pourcentage_dispo
            })
        
        # Trier par nombre d'emprunts décroissant
        stats_categories.sort(key=lambda x: x['count_emprunts'], reverse=True)
        
        # Statistiques d'état de la collection
        livres_empruntes = Livre.query.filter_by(disponible=False).count()
        # Calculer les livres réservés (à adapter selon votre modèle)
        livres_reserves = 0  # À remplacer par votre logique de réservation
        
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
        
        # Livres les plus empruntés
        top_books = db.session.query(
            Livre,
            db.func.count(Emprunt.id).label('count')
        ).join(Emprunt).filter(Emprunt.date_emprunt >= start).group_by(Livre).order_by(db.text('count DESC')).limit(5).all()
        
        top_books_data = []
        for livre, count in top_books:
            top_books_data.append({
                'titre': livre.titre,
                'auteur': livre.auteur,
                'count': count
            })
        
        # Statistiques par jour
        stats_days = []
        if period == 'week':
            for i in range(7):
                day = start + timedelta(days=i)
                count = Emprunt.query.filter(
                    db.func.date(Emprunt.date_emprunt) == day.date()
                ).count()
                stats_days.append({
                    'label': day.strftime('%a %d'),
                    'bars': [{'width': min(count * 5, 100), 'color': 'var(--primary)', 'count': count}]
                })
        
        # Calcul du taux de disponibilité global (en pourcentage)
        if total_livres and total_livres > 0:
            taux_disponibilite = round((livres_disponibles / total_livres) * 100, 1)
        else:
            taux_disponibilite = 100

        return render_template("statistiques.html", 
                     title="Statistiques",
                     is_admin=True,
                     total_adherents=total_adherents,
                     total_livres=total_livres,
                     total_bibliothecaires=total_bibliothecaires,
                     emprunts_en_cours=emprunts_en_cours,
                     livres_disponibles=livres_disponibles,
                     livres_empruntes=livres_empruntes,
                     livres_reserves=livres_reserves,
                     taux_disponibilite=taux_disponibilite,
                     stats_categories=stats_categories,
                     stats_adherents=stats_adherents,
                     top_books=top_books_data,
                     stats_days=stats_days if stats_days else None,
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


@app.route('/dashboard/export_data')
@login_required
def export_data():
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    import csv, zipfile

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
        # Adherents
        s = StringIO()
        writer = csv.writer(s)
        writer.writerow(['id', 'nom', 'prenom', 'email', 'telephone', 'classe', 'statut', 'date_inscription'])
        for a in Adherent.query.all():
            writer.writerow([a.id, a.nom, a.prenom, a.email, a.telephone, a.classe, a.statut, a.date_inscription])
        zf.writestr('adherents.csv', s.getvalue())

        # Livres
        s = StringIO()
        writer = csv.writer(s)
        writer.writerow(['id', 'titre', 'auteur', 'isbn', 'annee_publication', 'categorie', 'disponible'])
        for l in Livre.query.all():
            writer.writerow([l.id, l.titre, l.auteur, l.isbn, l.annee_publication, l.categorie, l.disponible])
        zf.writestr('livres.csv', s.getvalue())

        # Emprunts
        s = StringIO()
        writer = csv.writer(s)
        writer.writerow(['id', 'adherent_id', 'livre_id', 'date_emprunt', 'date_retour_prevue', 'date_retour_effective', 'status', 'prolongations', 'amende'])
        for e in Emprunt.query.all():
            writer.writerow([e.id, e.adherent_id, e.livre_id, e.date_emprunt, e.date_retour_prevue, e.date_retour_effective, e.status, e.prolongations, e.amende])
        zf.writestr('emprunts.csv', s.getvalue())

        # Reservations
        s = StringIO()
        writer = csv.writer(s)
        writer.writerow(['id', 'adherent_id', 'livre_id', 'date_reservation', 'status'])
        for r in Reservation.query.all():
            writer.writerow([r.id, r.adherent_id, r.livre_id, r.date_reservation, r.status])
        zf.writestr('reservations.csv', s.getvalue())

    mem_zip.seek(0)
    return Response(mem_zip.getvalue(), mimetype='application/zip', headers={
        'Content-Disposition': 'attachment; filename=bibliotheque_export.zip'
    })


@app.route('/dashboard/download_backup')
@login_required
def download_backup():
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('dashboard'))

    # Simple JSON backup of key tables
    import json
    data = {
        'adherents': [
            { 'id': a.id, 'nom': a.nom, 'prenom': a.prenom, 'email': a.email } for a in Adherent.query.all()
        ],
        'livres': [ { 'id': l.id, 'titre': l.titre, 'auteur': l.auteur } for l in Livre.query.all() ],
        'emprunts': [ { 'id': e.id, 'adherent_id': e.adherent_id, 'livre_id': e.livre_id } for e in Emprunt.query.all() ]
    }
    payload = json.dumps(data, default=str, ensure_ascii=False)
    return Response(payload, mimetype='application/json', headers={'Content-Disposition': 'attachment; filename=bibliotheque_backup.json'})

@app.route("/dashboard/parametres", methods=["GET", "POST"])
@login_required
def parametres():
    # Gestion POST pour sauvegarder la configuration
    cfg = get_library_config()
    if request.method == 'POST':
        try:
            max_emprunts = int(request.form.get('max_emprunts') or cfg.max_emprunts)
            duree_emprunt = int(request.form.get('duree_emprunt') or cfg.duree_emprunt)
            max_prolongations = int(request.form.get('max_prolongations') or cfg.max_prolongations)
            jours_prolongation = int(request.form.get('jours_prolongation') or cfg.jours_prolongation)
            amende_par_jour = float(request.form.get('amende_par_jour') or cfg.amende_par_jour)

            cfg.max_emprunts = max_emprunts
            cfg.duree_emprunt = duree_emprunt
            cfg.max_prolongations = max_prolongations
            cfg.jours_prolongation = jours_prolongation
            cfg.amende_par_jour = amende_par_jour
            db.session.commit()
            flash('Paramètres sauvegardés', 'success')
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Erreur sauvegarde paramètres')
            flash('Erreur lors de la sauvegarde des paramètres', 'danger')
        return redirect(url_for('parametres'))

    library_settings = {
        'max_emprunts': cfg.max_emprunts,
        'duree_emprunt': cfg.duree_emprunt,
        'max_prolongations': cfg.max_prolongations,
        'jours_prolongation': cfg.jours_prolongation,
        'amende_par_jour': cfg.amende_par_jour
    }

    # Notification preferences placeholders (in future, persist per-user)
    notification_settings = {
        'email': True,
        'sms': False,
        'livres_retard': True,
        'nouveaux_livres': True,
        'reservations': True,
        'system': False,
        'reports': False,
        'alerts': False
    }

    # Lists for admin/bibliothecaire to manage
    users_non_admin = User.query.filter(User.role != 'admin').order_by(User.username.asc()).all()
    bibliothecaires_list = Bibliothecaire.query.order_by(Bibliothecaire.nom.asc()).all()
    adherents = Adherent.query.order_by(Adherent.nom.asc()).all()

    return render_template("parametres.html", title="Paramètres",
                           library_settings=library_settings,
                           notification_settings=notification_settings,
                           users_non_admin=users_non_admin,
                           bibliothecaires=bibliothecaires_list,
                           adherents=adherents)


@app.route('/dashboard/parametres/delete_all_non_admins', methods=['POST'])
@login_required
def delete_all_non_admins():
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('parametres'))

    try:
        # Do not delete the current user to avoid immediate logout issues
        User.query.filter(User.role != 'admin', User.id != current_user.id).delete(synchronize_session=False)
        db.session.commit()
        flash('Tous les comptes non-admin ont été supprimés (sauf votre compte).', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Erreur lors de la suppression de tous les comptes non-admin')
        flash('Erreur lors de la suppression des comptes.', 'danger')
    return redirect(url_for('parametres'))


@app.route('/dashboard/parametres/delete_user', methods=['POST'])
@login_required
def delete_user():
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('parametres'))

    user_id = request.form.get('user_id')
    try:
        uid = int(user_id)
    except Exception:
        flash('Utilisateur invalide', 'danger')
        return redirect(url_for('parametres'))

    user = User.query.get(uid)
    if not user:
        flash('Utilisateur introuvable', 'danger')
        return redirect(url_for('parametres'))

    # Prevent non-admins from deleting admin accounts
    if user.role == 'admin' and not (getattr(current_user, 'role', None) == 'admin'):
        flash('Vous n\'êtes pas autorisé à supprimer un administrateur', 'danger')
        return redirect(url_for('parametres'))

    try:
        # If user has an adherent profile, delete related emprunts/reservations
        adherent = getattr(user, 'adherent', None)
        if adherent:
            try:
                db.session.query(Emprunt).filter(Emprunt.adherent_id == adherent.id).delete(synchronize_session=False)
            except Exception:
                current_app.logger.exception('Erreur suppression emprunts utilisateur lors suppression user')
            try:
                db.session.query(Reservation).filter(Reservation.adherent_id == adherent.id).delete(synchronize_session=False)
            except Exception:
                current_app.logger.exception('Erreur suppression reservations utilisateur lors suppression user')

        db.session.delete(user)
        if adherent:
            db.session.delete(adherent)
        db.session.commit()
        flash('Utilisateur supprimé avec succès', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Erreur lors de la suppression d\'un utilisateur')
        flash('Erreur lors de la suppression de l\'utilisateur', 'danger')

    return redirect(url_for('parametres'))


@app.route('/dashboard/parametres/delete_adherent', methods=['POST'])
@login_required
def delete_adherent():
    if not has_roles('admin', 'bibliothecaire'):
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('parametres'))

    adherent_id = request.form.get('adherent_id')
    try:
        aid = int(adherent_id)
    except Exception:
        flash('Adhérent invalide', 'danger')
        return redirect(url_for('parametres'))

    a = Adherent.query.get(aid)
    if not a:
        flash('Adhérent introuvable', 'danger')
        return redirect(url_for('parametres'))

    try:
        db.session.query(Emprunt).filter(Emprunt.adherent_id == a.id).delete(synchronize_session=False)
        db.session.query(Reservation).filter(Reservation.adherent_id == a.id).delete(synchronize_session=False)
        # delete linked user if any
        if getattr(a, 'user', None):
            try:
                db.session.delete(a.user)
            except Exception:
                current_app.logger.exception('Erreur lors de suppression du user lié à l\'adhérent')

        db.session.delete(a)
        db.session.commit()
        flash('Adhérent supprimé avec succès', 'success')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Erreur suppression adhérent')
        flash('Erreur lors de la suppression de l\'adhérent', 'danger')

    return redirect(url_for('parametres'))


@app.route("/profil/update", methods=["POST"])
@login_required
def update_profil():
    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip()
    current_password = request.form.get("current_password") or request.form.get("current_password", "")

    if not username or not email:
        flash("Veuillez remplir tous les champs.", "danger")
        return redirect(url_for("parametres") + '#profil')

    if current_password:
        if not current_user.check_password(current_password):
            flash("Mot de passe actuel incorrect.", "danger")
            return redirect(url_for("parametres") + '#profil')

    # Handle password change: if new_password provided, require current_password and confirmation
    new_password = request.form.get('new_password') or ''
    confirm_new = request.form.get('confirm_new_password') or ''
    if new_password:
        # require current_password
        if not current_password:
            flash('Pour changer le mot de passe, veuillez fournir votre mot de passe actuel.', 'danger')
            return redirect(url_for('parametres') + '#profil')
        if new_password != confirm_new:
            flash('Le nouveau mot de passe et sa confirmation ne correspondent pas.', 'danger')
            return redirect(url_for('parametres') + '#profil')
        if len(new_password) < 6:
            flash('Le mot de passe doit contenir au moins 6 caractères.', 'danger')
            return redirect(url_for('parametres') + '#profil')

    existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
    if existing_user:
        flash("Ce nom d'utilisateur est déjà pris.", "danger")
        return redirect(url_for("parametres") + '#profil')

    existing_email = User.query.filter(User.email == email, User.id != current_user.id).first()
    if existing_email:
        flash("Cette adresse email est déjà utilisée.", "danger")
        return redirect(url_for("parametres") + '#profil')

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
        # apply password update after commit of profile info
        if new_password:
            try:
                current_user.set_password(new_password)
                db.session.commit()
                flash('Mot de passe mis à jour', 'success')
            except Exception:
                db.session.rollback()
                current_app.logger.exception('Erreur lors de la mise à jour du mot de passe')
                flash('Erreur lors de la mise à jour du mot de passe.', 'danger')
        flash("Informations mises à jour", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Erreur lors de la mise à jour du profil")
        flash("Erreur lors de la mise à jour.", "danger")
    return redirect(url_for("parametres") + '#profil')

@app.route("/profil/upload", methods=["POST"])
@login_required
def upload_image():
    file = request.files.get('image') or request.files.get('profile_picture')
    if not file or file.filename == "":
        flash("Aucun fichier sélectionné.", "warning")
        return redirect(url_for("parametres") + '#profil')

    allowed_ext = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    filename = secure_filename(file.filename)
    if '.' not in filename:
        flash("Fichier invalide.", "danger")
        return redirect(url_for("parametres") + '#profil')
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in allowed_ext:
        flash("Format non autorisé. Utilisez PNG/JPG/JPEG/GIF/WEBP.", "danger")
        return redirect(url_for("parametres") + '#profil')

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

    return redirect(url_for("parametres") + '#profil')

@app.route('/profil/delete', methods=['POST'])
@login_required
def delete_account():
    password = request.form.get('password') or ''
    if not password or not current_user.check_password(password):
        flash('Mot de passe incorrect ou manquant. Suppression annulée.', 'danger')
        return redirect(url_for('parametres') + '#profil')

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
        return redirect(url_for('parametres') + '#profil')

    return redirect(url_for('index'))

@app.context_processor
def inject_variables():
    """Injecte des variables utiles dans tous les templates"""
    admin_exists = User.query.filter_by(role='admin').first() is not None
    return dict(
        admin_exists=admin_exists,
        current_year=datetime.now().year
    )

@app.context_processor
def utility_processor():
    def format_date(date, format='%d/%m/%Y'):
        if date:
            return date.strftime(format)
        return ''

    def days_until(dt):
        """Return number of days from today until `dt` (positive if in future, negative if past).
        Accepts both `datetime` and `date` values.
        """
        d = _to_date(dt)
        if d is None:
            return 0
        return (d - datetime.utcnow().date()).days

    return dict(
        timedelta=timedelta,
        now=datetime.utcnow(),
        format_date=format_date,
        datetime=datetime,
        today=datetime.utcnow().date(),
        days_until=days_until
    )


if __name__ == "__main__":
    app.run(debug=True)
