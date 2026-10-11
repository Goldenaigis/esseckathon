from bisect import bisect_left
from collections import defaultdict, deque

import numpy as np
import pandas as pd

HOUR = 3600.0
DAY = 86400.0
WEEK = 7 * DAY
MAX_WINDOW = WEEK
HISTORY_CAP = 200


class CausalState:
    """Historique glissant par compte, interrogeable uniquement sur le passé strict.

    Les deques d'arêtes sont purgées à 7 jours ; les compteurs « depuis toujours »
    (bénéficiaires connus, nombre d'encaissements, dernier encaissement) ne le sont
    pas, car la rupture comportementale se mesure sur toute l'histoire du compte.
    """

    def __init__(self):
        self.sent = defaultdict(deque)
        self.recv = defaultdict(deque)
        self.beneficiaries = defaultdict(set)
        self.amount_history = defaultdict(deque)
        self.last_sent_ts = {}
        self.prev_sent_gap = {}
        self.last_inflow_ts = {}
        self.inflow_count = defaultdict(int)

    @staticmethod
    def _window(dq, t, span):
        # ts < t strict : une transaction de timestamp identique ne doit pas peser sur
        # le score d'une autre, sinon le résultat dépend de l'ordre de tri des ex aequo.
        lo = t - span
        return [e for e in dq if lo <= e[0] < t]

    @staticmethod
    def _resend_delay(incoming, outgoing):
        if not incoming or not outgoing:
            return np.nan
        in_ts = [e[0] for e in incoming]
        delays = []
        for ts_out, _, _ in outgoing:
            i = bisect_left(in_ts, ts_out)
            if i > 0:
                delays.append(ts_out - in_ts[i - 1])
        return float(np.median(delays)) if delays else np.nan

    def features_for(self, ts, src, dst, amount):
        f = {}

        history = self.amount_history[src]
        if history:
            median = float(np.median(history))
            f["amount_over_src_median"] = amount / median if median > 0 else np.nan
        else:
            f["amount_over_src_median"] = np.nan

        sent_src = self.sent[src]
        s1h = self._window(sent_src, ts, HOUR)
        s24 = self._window(sent_src, ts, DAY)
        s7d = self._window(sent_src, ts, WEEK)
        f["src_n_tx_1h"] = len(s1h)
        f["src_n_tx_24h"] = len(s24)
        f["src_n_tx_7d"] = len(s7d)
        f["src_sum_24h"] = float(sum(e[2] for e in s24))
        f["src_sum_7d"] = float(sum(e[2] for e in s7d))
        f["src_n_distinct_dst_24h"] = len({e[1] for e in s24})
        f["src_n_distinct_dst_7d"] = len({e[1] for e in s7d})
        f["is_new_beneficiary"] = int(dst not in self.beneficiaries[src])

        if len(history) >= 2:
            arr = np.fromiter(history, dtype=float, count=len(history))
            sd = float(arr.std())
            f["amount_zscore_vs_src_history"] = float((amount - arr.mean()) / sd) if sd > 0 else 0.0
        else:
            f["amount_zscore_vs_src_history"] = np.nan

        last_sent = self.last_sent_ts.get(src)
        f["src_seconds_since_last_tx"] = ts - last_sent if last_sent is not None else np.nan
        f["src_dormancy_before"] = self.prev_sent_gap.get(src, np.nan)

        recv_dst = self.recv[dst]
        sent_dst = self.sent[dst]
        r1h = self._window(recv_dst, ts, HOUR)
        r24 = self._window(recv_dst, ts, DAY)
        r7d = self._window(recv_dst, ts, WEEK)
        o24 = self._window(sent_dst, ts, DAY)
        o7d = self._window(sent_dst, ts, WEEK)

        f["dst_n_distinct_src_1h"] = len({e[1] for e in r1h})
        f["dst_n_distinct_src_24h"] = len({e[1] for e in r24})
        f["dst_n_tx_in_1h"] = len(r1h)
        f["dst_n_tx_in_24h"] = len(r24)
        sum_in = float(sum(e[2] for e in r24))
        sum_out = float(sum(e[2] for e in o24))
        f["dst_sum_in_24h"] = sum_in
        f["dst_fanout_ratio"] = sum_out / sum_in if sum_in > 0 else np.nan
        f["dst_median_delay_in_to_out"] = self._resend_delay(r7d, o24)
        f["dst_degree_7d"] = len({e[1] for e in r7d} | {e[1] for e in o7d})

        # Rupture comportementale du destinataire : un compte ancien, peu sollicité,
        # qui devient soudain un point de convergence. Les mules recrutées parmi des
        # clients existants n'ont pas de signal d'ancienneté, seulement celui-ci.
        last_inflow = self.last_inflow_ts.get(dst)
        f["dst_seconds_since_last_inflow"] = ts - last_inflow if last_inflow is not None else np.nan
        f["dst_prior_inflow_count"] = self.inflow_count[dst]
        # Encaissements antérieurs à la rafale en cours. Reste proche de zéro pendant
        # toute la collecte sur un compte réellement dormant, alors que les deux
        # variables ci-dessus s'écrasent dès le deuxième virement reçu.
        f["dst_inflow_count_before_24h"] = self.inflow_count[dst] - len(r24)

        return f

    def commit(self, ts, src, dst, amount):
        last_sent = self.last_sent_ts.get(src)
        if last_sent is not None:
            self.prev_sent_gap[src] = ts - last_sent
        self.last_sent_ts[src] = ts

        self.beneficiaries[src].add(dst)
        history = self.amount_history[src]
        history.append(amount)
        if len(history) > HISTORY_CAP:
            history.popleft()

        self.last_inflow_ts[dst] = ts
        self.inflow_count[dst] += 1

        self.sent[src].append((ts, dst, amount))
        self.recv[dst].append((ts, src, amount))
        self._purge(src, ts)
        self._purge(dst, ts)

    def _purge(self, account, ts):
        lo = ts - MAX_WINDOW
        for dq in (self.sent[account], self.recv[account]):
            while dq and dq[0][0] < lo:
                dq.popleft()


def compute_causal_features(df):
    """df trié par ts_epoch croissant, colonnes ts_epoch/src_account/dst_account/amount."""
    state = CausalState()
    ts_arr = df["ts_epoch"].to_numpy(dtype=float)
    srcs = df["src_account"].to_numpy()
    dsts = df["dst_account"].to_numpy()
    amounts = df["amount"].to_numpy(dtype=float)

    rows = []
    n = len(df)
    i = 0
    while i < n:
        # Les transactions de timestamp identique sont scorées avant d'être toutes validées :
        # sinon l'historique non fenêtré laisserait une transaction simultanée influencer
        # le score de sa voisine.
        j = i
        while j < n and ts_arr[j] == ts_arr[i]:
            j += 1
        for k in range(i, j):
            rows.append(state.features_for(ts_arr[k], srcs[k], dsts[k], amounts[k]))
        for k in range(i, j):
            state.commit(ts_arr[k], srcs[k], dsts[k], amounts[k])
        i = j

    return pd.DataFrame(rows, index=df.index)
