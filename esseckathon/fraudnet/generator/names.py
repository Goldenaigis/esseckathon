"""Pools de noms fictifs. Aucune reference a une personne ou entite reelle."""

FIRST_NAMES = [
    "Lucas", "Emma", "Gabriel", "Jade", "Raphael", "Louise", "Arthur", "Alice",
    "Louis", "Chloe", "Jules", "Lina", "Adam", "Mila", "Maël", "Rose",
    "Paul", "Anna", "Hugo", "Inès", "Nathan", "Léa", "Theo", "Manon",
    "Antoine", "Camille", "Pierre", "Sophie", "Julien", "Marie", "Nicolas",
    "Claire", "Thomas", "Isabelle", "Olivier", "Nathalie", "Philippe",
    "Catherine", "Michel", "Francoise", "Alain", "Monique", "Bernard",
    "Jacqueline", "Daniel", "Danielle", "Christian", "Martine", "Gerard",
    "Chantal", "Andre", "Sylvie", "Rene", "Brigitte", "Marcel", "Annie",
    "Yvon", "Colette", "Fatima", "Karim", "Amine", "Sarah", "Youssef",
    "Leila", "Mehdi", "Nadia", "Ibrahim", "Awa", "Mamadou", "Fanta",
    "Joao", "Maria", "Elena", "Andrei", "Ioana", "Piotr", "Kasia",
]

LAST_NAMES = [
    "Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit",
    "Durand", "Leroy", "Moreau", "Simon", "Laurent", "Lefebvre", "Michel",
    "Garcia", "David", "Bertrand", "Roux", "Vincent", "Fournier", "Morel",
    "Girard", "Andre", "Lefevre", "Mercier", "Dupont", "Lambert", "Bonnet",
    "Francois", "Martinez", "Legrand", "Garnier", "Faure", "Rousseau",
    "Blanc", "Guerin", "Muller", "Henry", "Roussel", "Nicolas", "Perrin",
    "Morin", "Mathieu", "Clement", "Gauthier", "Dumont", "Lopez", "Fontaine",
    "Chevalier", "Robin", "Masson", "Sanchez", "Gerard", "Nguyen", "Boyer",
    "Denis", "Lemaire", "Duval", "Joly", "Gautier", "Roger", "Roche",
    "Benali", "Haddad", "Cherif", "Diallo", "Traore", "Ndiaye", "Sow",
    "Silva", "Costa", "Popescu", "Ionescu", "Kowalski", "Nowak",
]

CITIES = [
    ("Paris", 0.14), ("Marseille", 0.05), ("Lyon", 0.05), ("Toulouse", 0.04),
    ("Nice", 0.03), ("Nantes", 0.03), ("Montpellier", 0.03), ("Strasbourg", 0.03),
    ("Bordeaux", 0.03), ("Lille", 0.03), ("Rennes", 0.02), ("Reims", 0.02),
    ("Saint-Etienne", 0.02), ("Toulon", 0.02), ("Le Havre", 0.02),
    ("Grenoble", 0.02), ("Dijon", 0.02), ("Angers", 0.02), ("Nimes", 0.02),
    ("Villeurbanne", 0.01), ("Clermont-Ferrand", 0.02), ("Le Mans", 0.01),
    ("Aix-en-Provence", 0.02), ("Brest", 0.01), ("Tours", 0.02),
    ("Amiens", 0.01), ("Limoges", 0.01), ("Annecy", 0.01), ("Perpignan", 0.01),
    ("Besancon", 0.01), ("Metz", 0.01), ("Orleans", 0.01), ("Rouen", 0.01),
    ("Mulhouse", 0.01), ("Caen", 0.01), ("Nancy", 0.01), ("Argenteuil", 0.01),
    ("Montreuil", 0.01), ("Roubaix", 0.01), ("Dunkerque", 0.01),
]

DOMESTIC_BANKS = [
    ("Banque du Centre", "BDCEFRPP"),
    ("Credit Atlantique", "CRATFRPP"),
    ("Banque Populaire du Nord", "BPNOFRPP"),
    ("Societe Meridionale de Banque", "SMEBFRPP"),
    ("Caisse Mutuelle de l'Ouest", "CMOUFRPP"),
    ("Neobanque Kairos", "KAIRFRP2"),
    ("Banque Horizon", "BHORFRPP"),
    ("Epargne et Credit Rhodanien", "ECRHFRPP"),
]

# (nom, pays, profil) ; profil "emi" = etablissement de paiement, destination
# classique des mules. profil "retail" = banque de detail ordinaire.
FOREIGN_BANKS = [
    ("Baltic Pay Institution", "LT", "emi"),
    ("Valletta Digital Bank", "MT", "emi"),
    ("Nicosia Finance House", "CY", "emi"),
    ("Riga Transfer Bank", "LV", "emi"),
    ("Sofia Commercial Credit", "BG", "emi"),
    ("Tallinn Fintech Bank", "EE", "emi"),
    ("Banco do Minho", "PT", "retail"),
    ("Banque Atlas du Maghreb", "MA", "retail"),
    ("Banque de l'Ouest Africain", "SN", "retail"),
    ("Banca Transcarpatica", "RO", "retail"),
    ("Rheinland Sparbank", "DE", "retail"),
    ("Banco del Levante", "ES", "retail"),
    ("Amsterdam Handelsbank", "NL", "retail"),
    ("Warsaw Credit Union", "PL", "retail"),
    ("London Merchant Bank", "GB", "retail"),
    ("Gulf Transfer Bank", "AE", "emi"),
]

# Corridors de remise de fonds legitimes. Volontairement en partie distincts
# des pays "emi" pour que le modele n'apprenne pas "etranger = fraude".
REMITTANCE_COUNTRIES = ["MA", "SN", "PT", "RO", "PL", "ES", "DE"]

CSP = {
    "cadre": {"income": (3400, 9500), "age": (28, 62), "w": 0.17},
    "profession_intermediaire": {"income": (2200, 3600), "age": (25, 62), "w": 0.14},
    "employe": {"income": (1500, 2400), "age": (20, 62), "w": 0.22},
    "ouvrier": {"income": (1450, 2300), "age": (20, 62), "w": 0.13},
    "artisan_commercant": {"income": (1600, 6500), "age": (26, 65), "w": 0.07},
    "agriculteur": {"income": (1000, 3200), "age": (28, 66), "w": 0.02},
    "retraite": {"income": (950, 2900), "age": (63, 93), "w": 0.17},
    "etudiant": {"income": (320, 1000), "age": (18, 27), "w": 0.05},
    "sans_emploi": {"income": (620, 1350), "age": (20, 60), "w": 0.03},
}

COMPANY_SECTORS = [
    ("commerce_alimentaire", True, 0.12),
    ("restauration", True, 0.11),
    ("commerce_equipement", True, 0.09),
    ("transport", True, 0.06),
    ("loisirs_culture", True, 0.05),
    ("sante", True, 0.05),
    ("energie_telecom", True, 0.04),
    ("assurance", True, 0.04),
    ("batiment", False, 0.10),
    ("conseil", False, 0.09),
    ("informatique", False, 0.07),
    ("industrie", False, 0.06),
    ("immobilier_sci", False, 0.08),
    ("logistique_b2b", False, 0.04),
]

COMPANY_PREFIX = [
    "Atelier", "Maison", "Groupe", "Comptoir", "Societe", "Etablissements",
    "Agence", "Cabinet", "Studio", "Fabrique", "Entrepot", "Boutique",
    "Domaine", "Centre", "Compagnie",
]

COMPANY_ROOT = [
    "Verdier", "Lansac", "Maubert", "Verone", "Castelnau", "Brevard",
    "Soltane", "Harbeck", "Perrigny", "Vaucresson", "Tramont", "Belleroche",
    "Estaque", "Clavaire", "Monterre", "Fontaubert", "Rivesalte", "Chaligny",
    "Noirmont", "Pradelle", "Sauvigny", "Tourville", "Valmorel", "Bressac",
]

COMPANY_SUFFIX = [
    "SAS", "SARL", "SA", "EURL", "SASU", "SCI", "SNC",
]

ASSOCIATION_PREFIX = [
    "Association", "Fondation", "Collectif", "Comite", "Union", "Reseau",
    "Amis de", "Solidarite",
]

ASSOCIATION_ROOT = [
    "Espoir Partage", "Lumiere du Quartier", "Terre Vivante", "Main Tendue",
    "Horizon Jeunesse", "Elan Sportif", "Memoire et Patrimoine",
    "Lecture pour Tous", "Sante Sans Frontieres", "Toits Solidaires",
    "Chemins d'Avenir", "Harmonie Musicale", "Cap Handicap",
    "Jardins Communs", "Voix du Village",
]

ASSOCIATION_CAUSES = [
    "humanitaire", "sport", "culture", "sante", "education",
    "environnement", "social",
]

MERCHANT_LABELS = {
    "commerce_alimentaire": ["Courses", "Supermarche", "Epicerie", "Marche"],
    "restauration": ["Restaurant", "Dejeuner", "Brasserie", "Cafe"],
    "commerce_equipement": ["Achat equipement", "Vetements", "Electromenager"],
    "transport": ["Transport", "Carburant", "Billet train", "Peage"],
    "loisirs_culture": ["Cinema", "Librairie", "Salle de sport", "Concert"],
    "sante": ["Pharmacie", "Consultation", "Optique"],
    "energie_telecom": ["Facture energie", "Abonnement telecom", "Internet"],
    "assurance": ["Cotisation assurance", "Mutuelle"],
}

P2P_LABELS = [
    "Merci !", "Remboursement resto", "Part du cadeau", "Cagnotte",
    "Billets concert", "Essence weekend", "Courses partagees",
    "Je te rends", "Anniversaire", "Pour les vacances", "Taxi hier soir",
    "Part du gateau", "Location ski", "Repas equipe",
]

FRAUD_LABELS = {
    "faux_conseiller": [
        "Virement securite", "Mise en securite compte", "Transfert conseiller",
        "Operation urgente", "Sauvegarde fonds", "Virement verification",
    ],
    "faux_investissement": [
        "Placement", "Investissement crypto", "Souscription", "Versement capital",
        "Depot plateforme", "Portefeuille trading",
    ],
    "compte_collecteur": [
        "Virement", "Transfert", "Reglement", "Paiement",
    ],
    "smurfing": [
        "Virement", "Avance", "Reglement partiel", "Acompte",
    ],
    "chaine_mules": [
        "Transfert", "Reglement commande", "Virement partenaire", "Avance",
    ],
    "dormant_reactive": [
        "Virement", "Transfert", "Reglement",
    ],
    "cycle": [
        "Regularisation", "Transfert interne", "Reglement", "Compensation",
    ],
}
