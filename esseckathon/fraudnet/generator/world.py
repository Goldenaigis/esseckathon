"""Construction de la population bancaire et utilitaires partages."""

import math
from datetime import datetime, timedelta

from . import names as N
from ..shared.schema import TX_TYPE_INSTRUMENT

# ------------------------------------------------------------ temps

HOUR_WEIGHTS = {
    "business": [0.1, 0.05, 0.05, 0.05, 0.1, 0.3, 1, 2.5, 5, 8, 9, 8,
                 6, 7, 8, 8, 7, 5, 2, 1, 0.6, 0.4, 0.3, 0.2],
    "diurnal": [0.3, 0.2, 0.15, 0.1, 0.15, 0.4, 1.2, 2.5, 4, 5, 6, 7,
                7.5, 6.5, 6, 6.5, 7, 7.5, 8, 7, 5, 3.5, 2, 1],
    "evening": [0.8, 0.4, 0.2, 0.15, 0.15, 0.2, 0.5, 1, 1.5, 2, 2.5, 3,
                3, 2.5, 2.5, 3, 4, 6, 9, 10, 9, 7, 4, 2],
    "night": [3, 3.5, 3, 2.5, 2, 1.5, 1, 0.6, 0.4, 0.3, 0.3, 0.3,
              0.3, 0.3, 0.3, 0.3, 0.4, 0.5, 0.8, 1.2, 1.8, 2.5, 3, 3.2],
}

def next_business_day(d):
    """Decale au prochain jour ouvre: les virements SEPA ne reglent pas le week-end."""
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
    return d


def pick_hour(rng, profile="diurnal"):
    return rng.choices(range(24), weights=HOUR_WEIGHTS[profile], k=1)[0]


def ts_on(rng, day, profile="diurnal"):
    """Horodatage aleatoire dans la journee `day` (objet date/datetime)."""
    base = datetime(day.year, day.month, day.day)
    return base + timedelta(
        hours=pick_hour(rng, profile),
        minutes=rng.randrange(60),
        seconds=rng.randrange(60),
    )


def lognormal_amount(rng, median, sigma, lo=1.0, hi=None):
    v = median * math.exp(rng.gauss(0, sigma))
    v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return round(v, 2)


def weighted_choice(rng, pairs):
    """pairs = [(valeur, poids), ...]"""
    population = [p[0] for p in pairs]
    weights = [p[1] for p in pairs]
    return rng.choices(population, weights=weights, k=1)[0]


def month_label(d):
    mois = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
            "aout", "septembre", "octobre", "novembre", "decembre"]
    return mois[d.month - 1]


# ------------------------------------------------------------ transactions

def make_tx(ts, src, dst, amount, tx_type, label, channel, status="completed",
            src_country="FR", dst_country="FR", is_fraud=0, scenario_id="",
            scenario_type="", decoy_id="", decoy_type="", split=""):
    return {
        "tx_id": "",
        "ts": ts,
        "src_account": src,
        "dst_account": dst,
        "amount": round(float(amount), 2),
        "currency": "EUR",
        "src_country": src_country,
        "dst_country": dst_country,
        "channel": channel,
        "status": status,
        "instrument": TX_TYPE_INSTRUMENT[tx_type],
        "tx_type": tx_type,
        "label": label,
        "gt_is_fraud": is_fraud,
        "gt_scenario_id": scenario_id,
        "gt_scenario_type": scenario_type,
        "gt_decoy_id": decoy_id,
        "gt_decoy_type": decoy_type,
        "gt_split": split,
    }


def pick_status(rng):
    r = rng.random()
    if r < 0.965:
        return "completed"
    if r < 0.988:
        return "pending"
    return "rejected"


# ------------------------------------------------------------ monde

class World:
    def __init__(self, cfg, rng):
        self.cfg = cfg
        self.rng = rng
        self.window_start = cfg.window_start
        self.window_end = cfg.window_start + timedelta(days=cfg.window_days)
        self.split_boundary = cfg.window_start + timedelta(days=cfg.train_days)

        self.banks = []
        self.persons = []
        self.companies = []
        self.associations = []
        self.accounts = []

        self._acct_by_id = {}
        self._seq = {"person": 0, "company": 0, "association": 0, "account": 0}

        self.contacts = {}          # person_id -> [person_id]
        self.habitual_merchants = {}  # person_id -> [account_id]
        self.main_account = {}      # owner_id -> account_id
        self.savings_account = {}
        self.domestic_banks = []
        self.foreign_banks = []
        self.merchant_accounts = []
        self.employer_account = {}  # company_id -> account_id

    # ---------------------------------------------------------- accessoires

    def days(self):
        return [self.window_start + timedelta(days=i)
                for i in range(self.cfg.window_days)]

    def split_of(self, ts):
        return "train" if ts < self.split_boundary else "test"

    def account(self, account_id):
        return self._acct_by_id[account_id]

    def next_id(self, kind, prefix, width=6):
        self._seq[kind] += 1
        return f"{prefix}{self._seq[kind]:0{width}d}"

    # ---------------------------------------------------------- construction

    def build(self):
        self._build_banks()
        self._build_companies()
        self._build_associations()
        self._build_persons()
        self._build_social_graph()
        return self

    def _build_banks(self):
        cfg, rng = self.cfg, self.rng
        for i, (name, bic) in enumerate(N.DOMESTIC_BANKS[: cfg.n_domestic_banks]):
            b = {
                "bank_id": f"BNK_{i + 1:02d}",
                "bank_name": name,
                "bic": bic,
                "country": "FR",
                "is_domestic": 1,
                "n_accounts": 0,
                "_profile": "retail",
            }
            self.banks.append(b)
            self.domestic_banks.append(b)
        for i, (name, country, profile) in enumerate(N.FOREIGN_BANKS):
            b = {
                "bank_id": f"EXT_{i + 1:02d}",
                "bank_name": name,
                "bic": f"{name[:4].upper().replace(' ', 'X')}{country}2X",
                "country": country,
                "is_domestic": 0,
                "n_accounts": 0,
                "_profile": profile,
            }
            self.banks.append(b)
            self.foreign_banks.append(b)

    def _pick_domestic_bank(self):
        # Les grandes banques concentrent plus de comptes, la neobanque attire
        # les jeunes profils.
        weights = [6, 5, 4, 3, 3, 4, 2, 2][: len(self.domestic_banks)]
        return self.rng.choices(self.domestic_banks, weights=weights, k=1)[0]

    def _open_account(self, owner_type, owner_id, owner_name, bank, product,
                      segment, opened_at, balance, role="normal",
                      scenario_id=""):
        acct_id = self.next_id("account", "ACC_")
        acct = {
            "account_id": acct_id,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "bank_id": bank["bank_id"],
            "bank_name": bank["bank_name"],
            "country": bank["country"],
            "iban_masked": f"{bank['country']}** **** **** {acct_id[-4:]}",
            "product": product,
            "segment": segment,
            "opened_at": opened_at,
            "account_age_days": 0,
            "balance": round(balance, 2),
            "gt_role": role,
            "gt_scenario_id": scenario_id,
        }
        self.accounts.append(acct)
        self._acct_by_id[acct_id] = acct
        bank["n_accounts"] += 1
        return acct

    def _build_companies(self):
        cfg, rng = self.cfg, self.rng
        sector_pairs = [(s, w) for s, _, w in N.COMPANY_SECTORS]
        merchant_flag = {s: m for s, m, _ in N.COMPANY_SECTORS}

        for _ in range(cfg.n_companies):
            cid = self.next_id("company", "CMP_", 5)
            sector = weighted_choice(rng, sector_pairs)
            form = "SCI" if sector == "immobilier_sci" else rng.choice(
                N.COMPANY_SUFFIX[:5]
            )
            legal_name = (
                f"{rng.choice(N.COMPANY_PREFIX)} {rng.choice(N.COMPANY_ROOT)} {form}"
            )
            size_band = weighted_choice(
                rng, [("TPE", 0.62), ("PME", 0.30), ("ETI", 0.08)]
            )
            n_emp = {
                "TPE": rng.randrange(1, 10),
                "PME": rng.randrange(10, 250),
                "ETI": rng.randrange(250, 1200),
            }[size_band]
            revenue = {
                "TPE": lognormal_amount(rng, 28_000, 0.8, 3_000),
                "PME": lognormal_amount(rng, 420_000, 0.7, 40_000),
                "ETI": lognormal_amount(rng, 3_800_000, 0.6, 500_000),
            }[size_band]
            created = self.window_start - timedelta(
                days=rng.randrange(200, 11_000)
            )
            city = weighted_choice(rng, N.CITIES)

            self.companies.append({
                "company_id": cid,
                "legal_name": legal_name,
                "legal_form": form,
                "sector": sector,
                "size_band": size_band,
                "n_employees": n_emp,
                "created_at": created.date().isoformat(),
                "city": city,
                "country": "FR",
                "declared_monthly_revenue": round(revenue, 2),
                "is_merchant": int(merchant_flag[sector]),
                "gt_role": "normal",
                "gt_scenario_id": "",
            })

            bank = self._pick_domestic_bank()
            acct = self._open_account(
                "company", cid, legal_name, bank, "pro", "pro",
                max(created, self.window_start - timedelta(days=10_900)).date().isoformat(),
                lognormal_amount(rng, revenue * 0.6, 0.7, 500),
            )
            self.main_account[cid] = acct["account_id"]
            self.employer_account[cid] = acct["account_id"]
            if merchant_flag[sector]:
                self.merchant_accounts.append(acct["account_id"])

    def _build_associations(self):
        cfg, rng = self.cfg, self.rng
        for _ in range(cfg.n_associations):
            aid = self.next_id("association", "ASO_", 4)
            name = f"{rng.choice(N.ASSOCIATION_PREFIX)} {rng.choice(N.ASSOCIATION_ROOT)}"
            created = self.window_start - timedelta(days=rng.randrange(400, 9_000))
            self.associations.append({
                "association_id": aid,
                "association_name": name,
                "cause": rng.choice(N.ASSOCIATION_CAUSES),
                "created_at": created.date().isoformat(),
                "city": weighted_choice(rng, N.CITIES),
                "country": "FR",
                "n_members": rng.randrange(12, 2_400),
                "declared_annual_budget": lognormal_amount(rng, 85_000, 1.0, 2_000),
                "gt_role": "normal",
                "gt_scenario_id": "",
            })
            bank = self._pick_domestic_bank()
            acct = self._open_account(
                "association", aid, name, bank, "courant", "association",
                created.date().isoformat(),
                lognormal_amount(rng, 18_000, 1.0, 300),
            )
            self.main_account[aid] = acct["account_id"]

    def _build_persons(self):
        cfg, rng = self.cfg, self.rng
        csp_pairs = [(k, v["w"]) for k, v in N.CSP.items()]
        employers = [c for c in self.companies]

        for _ in range(cfg.n_persons):
            pid = self.next_id("person", "PER_", 6)
            csp = weighted_choice(rng, csp_pairs)
            spec = N.CSP[csp]
            age = rng.randrange(spec["age"][0], spec["age"][1] + 1)
            birth = self.window_start - timedelta(days=age * 365 + rng.randrange(365))
            income = round(rng.uniform(*spec["income"]), 2)

            # Aisance numerique: decroit avec l'age, avec du bruit.
            lit = max(0.02, min(0.99, 1.15 - (age - 18) / 70 + rng.gauss(0, 0.16)))

            employer = ""
            if csp not in ("retraite", "etudiant", "sans_emploi"):
                if rng.random() < cfg.employed_ratio + 0.2:
                    employer = rng.choice(employers)["company_id"]

            first, last = rng.choice(N.FIRST_NAMES), rng.choice(N.LAST_NAMES)
            self.persons.append({
                "person_id": pid,
                "first_name": first,
                "last_name": last,
                "birth_date": birth.date().isoformat(),
                "age": age,
                "age_band": "18-30" if age < 30 else ("30-60" if age < 60 else "60+"),
                "csp": csp,
                "employer_id": employer,
                "city": weighted_choice(rng, N.CITIES),
                "country": "FR",
                "declared_monthly_income": income,
                "sim_digital_literacy": round(lit, 3),
                "gt_role": "normal",
                "gt_scenario_id": "",
            })

            # Ancienneté: la plupart des comptes sont anciens, une minorite recente.
            if rng.random() < 0.08:
                age_days = rng.randrange(5, 200)
            else:
                age_days = rng.randrange(200, min(age - 17, 45) * 365 + 400)
            opened = self.window_start - timedelta(days=age_days)
            bank = self._pick_domestic_bank()
            full = f"{first} {last}"
            main = self._open_account(
                "person", pid, full, bank, "courant", "particulier",
                opened.date().isoformat(),
                lognormal_amount(rng, income * 1.4, 0.9, 20),
            )
            self.main_account[pid] = main["account_id"]

            # Le compte d'epargne est ouvert apres le compte courant, mais
            # toujours avant le debut de la fenetre: sinon on obtient des
            # comptes utilises avant leur propre date d'ouverture.
            if age_days > 60 and rng.random() < cfg.savings_ratio:
                offset = rng.randrange(30, min(400, age_days))
                sav = self._open_account(
                    "person", pid, full, bank, "epargne", "particulier",
                    (self.window_start
                     - timedelta(days=age_days - offset)).date().isoformat(),
                    lognormal_amount(rng, income * 6, 1.1, 50),
                )
                self.savings_account[pid] = sav["account_id"]

    def _build_social_graph(self):
        """Cercles sociaux par attachement preferentiel + proximite geographique."""
        rng = self.rng
        persons = self.persons
        by_city = {}
        for p in persons:
            by_city.setdefault(p["city"], []).append(p["person_id"])

        pool = []  # attachement preferentiel
        for p in persons:
            pid = p["person_id"]
            n = max(2, min(14, int(rng.gauss(6, 2.5))))
            local = by_city[p["city"]]
            picks = set()
            for _ in range(n):
                if pool and rng.random() < 0.35:
                    cand = rng.choice(pool)
                elif len(local) > 1 and rng.random() < 0.7:
                    cand = rng.choice(local)
                else:
                    cand = rng.choice(persons)["person_id"]
                if cand != pid:
                    picks.add(cand)
            self.contacts[pid] = sorted(picks)
            pool.extend([pid] * max(1, len(picks) // 2))

        # Reciprocite partielle
        for pid, lst in list(self.contacts.items()):
            for other in lst:
                if rng.random() < 0.6 and pid not in self.contacts[other]:
                    self.contacts[other].append(pid)

        for p in persons:
            k = max(3, min(12, int(rng.gauss(7, 2.2))))
            self.habitual_merchants[p["person_id"]] = rng.sample(
                self.merchant_accounts, min(k, len(self.merchant_accounts))
            )

    # ------------------------------------------- comptes crees par scenario

    def open_mule_account(self, scenario_id, role="mule", foreign=False,
                          profile="emi", max_age_days=40, min_age_days=2):
        """Cree un compte controle par un fraudeur (ou une mule recrutee)."""
        rng = self.rng
        if foreign:
            pool = [b for b in self.foreign_banks if b["_profile"] == profile] \
                or self.foreign_banks
            bank = rng.choice(pool)
        else:
            bank = self._pick_domestic_bank()
        age_days = rng.randrange(min_age_days, max_age_days + 1)
        opened = self.window_start + timedelta(
            days=rng.randrange(0, max(1, self.cfg.window_days - 5))
        ) - timedelta(days=age_days)
        opened = max(opened, self.window_start - timedelta(days=max_age_days))

        first, last = rng.choice(N.FIRST_NAMES), rng.choice(N.LAST_NAMES)
        acct = self._open_account(
            "person", "", f"{first} {last}", bank, "courant", "particulier",
            opened.date().isoformat(), lognormal_amount(rng, 120, 1.2, 0),
            role=role, scenario_id=scenario_id,
        )
        return acct

    def recruit_existing_mule(self, scenario_id, used):
        """Mule recrutee parmi des clients existants (profils jeunes/precaires)."""
        rng = self.rng
        cands = [
            p for p in self.persons
            if p["gt_role"] == "normal"
            and p["csp"] in ("etudiant", "sans_emploi", "employe", "ouvrier")
            and self.main_account[p["person_id"]] not in used
        ]
        if not cands:
            return None
        p = rng.choice(cands)
        p["gt_role"] = "mule"
        p["gt_scenario_id"] = scenario_id
        acct = self.account(self.main_account[p["person_id"]])
        acct["gt_role"] = "mule"
        acct["gt_scenario_id"] = scenario_id
        return acct

    def pick_victims(self, n, scenario_id, elderly_bias=True, used=None):
        """Selectionne des victimes. Biais vulnerabilite, sans etre exclusif."""
        rng = self.rng
        used = used or set()
        cands = [
            p for p in self.persons
            if p["gt_role"] == "normal"
            and self.main_account[p["person_id"]] not in used
        ]
        if elderly_bias:
            weights = [
                (0.35 + 2.4 * (1 - p["sim_digital_literacy"]))
                * (2.2 if p["age"] >= 60 else 1.0)
                * (0.25 if p["age"] < 30 else 1.0)
                for p in cands
            ]
        else:
            weights = [
                1.0 + p["declared_monthly_income"] / 4000.0 for p in cands
            ]
        chosen, seen = [], set()
        attempts = 0
        while len(chosen) < n and attempts < n * 40 and cands:
            c = rng.choices(cands, weights=weights, k=1)[0]
            if c["person_id"] not in seen:
                seen.add(c["person_id"])
                c["gt_role"] = "victim"
                c["gt_scenario_id"] = scenario_id
                acct = self.account(self.main_account[c["person_id"]])
                acct["gt_role"] = "victim"
                acct["gt_scenario_id"] = scenario_id
                chosen.append(c)
            attempts += 1
        return chosen

    def pick_scenario_start(self, duration_hours, split):
        """Place un scenario entierement dans sa partition (anti-fuite)."""
        rng = self.rng
        dur_days = max(1, math.ceil(duration_hours / 24))
        if split == "train":
            lo, hi = 0, self.cfg.train_days - dur_days - 1
        else:
            lo, hi = self.cfg.train_days, self.cfg.window_days - dur_days - 1
        if hi <= lo:
            hi = lo + 1
        day = rng.randrange(lo, hi)
        return self.window_start + timedelta(
            days=day, hours=rng.randrange(7, 20), minutes=rng.randrange(60)
        )

    def finalize_accounts(self):
        """Ancienneté et solde arretes a la fin de fenetre (informatif)."""
        for a in self.accounts:
            opened = datetime.fromisoformat(a["opened_at"])
            a["account_age_days"] = max(0, (self.window_end - opened).days)
