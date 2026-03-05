"""
Real-time 8-max cash preflop "math-ish" trainer (NO CSV) + UI (tkinter)

Updated behavior (what you asked):
- BEFORE you choose: does NOT show the mix (mix label is blank)
- AFTER you choose: shows mix + your chosen action % + sampled action %
"""

import random
import re
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Tuple, Optional, Dict, List

# -----------------------------
# Constants / helpers
# -----------------------------
CHART_RANKS = "AKQJT98765432"
IDX = {r: i for i, r in enumerate(CHART_RANKS)}  # A=0 ... 2=12

POSITIONS = ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
POS_I = {p: i for i, p in enumerate(POSITIONS)}

# Chen-ish base
CHEN_BASE = {
    "A": 10, "K": 8, "Q": 7, "J": 6, "T": 5,
    "9": 4.5, "8": 4, "7": 3.5, "6": 3, "5": 2.5, "4": 2, "3": 1.5, "2": 1
}

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def fmt_pct(x: float) -> str:
    return f"{x*100:.1f}%"

def normalize_rcf(r: float, c: float, f: float) -> Tuple[float, float, float]:
    s = r + c + f
    if s <= 0:
        return (0.0, 0.0, 1.0)
    return (r/s, c/s, f/s)

def cell_hand_label(row_rank: str, col_rank: str) -> str:
    """Matrix convention: diagonal pairs, above suited, below offsuit."""
    if row_rank == col_rank:
        return row_rank + col_rank
    row_i = IDX[row_rank]
    col_i = IDX[col_rank]
    if row_i < col_i:
        return f"{row_rank}{col_rank}s"
    hi = col_rank if IDX[col_rank] < IDX[row_rank] else row_rank
    lo = row_rank if hi == col_rank else col_rank
    return f"{hi}{lo}o"

def parse_hand_label(lbl: str) -> str:
    lbl = lbl.strip().upper()
    if len(lbl) == 2 and lbl[0] in CHART_RANKS and lbl[1] == lbl[0]:
        return lbl
    if len(lbl) == 3 and lbl[0] in CHART_RANKS and lbl[1] in CHART_RANKS and lbl[2] in ("S", "O"):
        a, b, t = lbl[0], lbl[1], lbl[2].lower()
        if a == b:
            return a + a
        # normalize hi/lo
        if IDX[a] > IDX[b]:  # A=0 is highest; bigger index means lower rank
            a, b = b, a
        return f"{a}{b}{t}"
    raise ValueError(f"Bad hand label: {lbl}")

def all_169() -> List[str]:
    out = []
    for r in CHART_RANKS:
        out.append(r+r)
    for i, hi in enumerate(CHART_RANKS):
        for lo in CHART_RANKS[i+1:]:
            out.append(f"{hi}{lo}s")
            out.append(f"{hi}{lo}o")
    return out

ALL_169 = all_169()

# -----------------------------
# Config (editable in UI)
# -----------------------------
@dataclass
class Config:
    open_size_bb: float = 2.5
    threebet_ip: float = 7.5
    threebet_oop: float = 9.0
    rake_pct: float = 0.05
    rake_cap_bb: float = 1.0

    # “loosen/tighten” knobs
    call_req_discount: float = 0.00  # subtract from required equity (e.g. 0.02 to loosen calls)
    realize_ip_vs_open: float = 1.04
    realize_oop_vs_open: float = 0.95
    realize_ip_vs_3bet: float = 1.02
    realize_oop_vs_3bet: float = 0.93

    # SB limps
    sb_limp_enabled: bool = True

    # RFI looseness by position
    rfi_loose: Dict[str, float] = None

    def __post_init__(self):
        if self.rfi_loose is None:
            self.rfi_loose = {
                "UTG": 0.05, "UTG1": 0.10, "LJ": 0.18, "HJ": 0.28,
                "CO": 0.45, "BTN": 0.62, "SB": 0.58
            }

# -----------------------------
# “Math-ish” model
# -----------------------------
def rake_taken(cfg: Config, pot_bb: float) -> float:
    return min(pot_bb * cfg.rake_pct, cfg.rake_cap_bb)

def chen_score(lbl: str) -> float:
    if len(lbl) == 2:
        r = lbl[0]
        base = CHEN_BASE[r]
        score = base * 2
        if r in "AKQJT":
            score += 2
        elif r in "987":
            score += 1
        return max(score, 5.0)

    hi, lo, t = lbl[0], lbl[1], lbl[2]
    base = max(CHEN_BASE[hi], CHEN_BASE[lo])
    if t == "s":
        base += 2

    gap = abs(IDX[lo] - IDX[hi])
    if gap == 1:
        base += 1
    elif gap == 2:
        base -= 1
    elif gap == 3:
        base -= 2
    elif gap >= 4:
        base -= 4

    if t == "s" and hi in "98765" and gap <= 2:
        base += 0.5

    return max(0.0, base)

def score_to_equity(score: float) -> float:
    x = (score - 8.0) / 4.5
    eq = 0.45 + 0.18 * (x / (1 + abs(x)))
    return clamp01(eq)

def blockers(lbl: str) -> float:
    if len(lbl) == 2:
        return 0.2
    hi, lo = lbl[0], lbl[1]
    w = 0.0
    if hi == "A" or lo == "A":
        w += 1.0
    if hi == "K" or lo == "K":
        w += 0.6
    if hi == "Q" or lo == "Q":
        w += 0.3
    return w

def playability(lbl: str) -> float:
    if len(lbl) == 2:
        return 0.6
    hi, lo, t = lbl[0], lbl[1], lbl[2]
    gap = abs(IDX[lo] - IDX[hi])
    p = 0.0
    if t == "s":
        p += 0.6
    if gap == 1:
        p += 0.6
    elif gap == 2:
        p += 0.35
    elif gap == 3:
        p += 0.15
    if hi in "AKQJT" and lo in "AKQJT":
        p += 0.25
    return p

def required_equity_call(cfg: Config, call_bb: float, pot_before_call_bb: float) -> float:
    pot_after = pot_before_call_bb + call_bb
    req = call_bb / max(1e-9, pot_after)
    req += rake_taken(cfg, pot_after) / max(1e-9, pot_after)
    req -= cfg.call_req_discount
    return clamp01(req)

def is_in_position(hero: str, villain: str) -> bool:
    return POS_I[hero] > POS_I[villain]

def target_3bet_pct(hero: str, opener: str) -> float:
    base = {
        "UTG": 0.03, "UTG1": 0.04, "LJ": 0.05, "HJ": 0.06,
        "CO": 0.08, "BTN": 0.11, "SB": 0.10, "BB": 0.07
    }.get(hero, 0.06)
    base += 0.03 * (POS_I[opener] / (len(POSITIONS) - 1))
    return clamp01(base)

def target_4bet_pct(opener: str, threebettor: str) -> float:
    base = 0.03
    if opener in ("CO", "BTN") and threebettor in ("SB", "BB"):
        base += 0.01
    return clamp01(base)

def freqs_rfi(cfg: Config, hand: str, pos: str) -> Tuple[float, float, float]:
    """(raise, limp, fold) encoded as (R, C, F)."""
    eq = score_to_equity(chen_score(hand))
    loose = cfg.rfi_loose.get(pos, 0.0)
    thr = 0.49 - 0.09 * loose
    open_frac = clamp01((eq - (thr - 0.05)) / 0.10)
    if open_frac <= 0:
        return (0.0, 0.0, 1.0)

    limp = 0.0
    if pos == "SB" and cfg.sb_limp_enabled:
        p = playability(hand)
        b = blockers(hand)
        limp_pref = clamp01(0.55 * p - 0.25 * b)
        limp_pref *= clamp01(1.0 - 1.4 * max(0.0, eq - 0.55))
        limp_share = clamp01(0.55 * limp_pref)
        limp = open_frac * limp_share

    raise_ = open_frac - limp
    fold = 1.0 - open_frac
    return normalize_rcf(raise_, limp, fold)

def freqs_vs_open(cfg: Config, hand: str, hero: str, opener: str) -> Tuple[float, float, float]:
    """(3bet, call, fold) encoded as (R, C, F)."""
    eq = score_to_equity(chen_score(hand))

    ip = is_in_position(hero, opener)
    pot0 = 1.5 + cfg.open_size_bb
    call_cost = cfg.open_size_bb
    req_call = required_equity_call(cfg, call_cost, pot0)

    realization = cfg.realize_ip_vs_open if ip else cfg.realize_oop_vs_open
    eq_eff = clamp01(eq * realization)

    call_frac = clamp01((eq_eff - (req_call - 0.03)) / 0.08)

    tgt = target_3bet_pct(hero, opener)
    value_thr = 0.58 if ip else 0.60
    value = clamp01((eq - (value_thr - 0.03)) / 0.06)

    b = blockers(hand)
    p = playability(hand)
    bluff_seed = clamp01(0.55 * b + 0.15 * p - 0.55 * eq)
    bluff = bluff_seed * 0.35

    three_raw = clamp01(0.75 * value + 0.25 * bluff)
    three_frac = clamp01(three_raw * (tgt / 0.10))

    cont = call_frac + three_frac
    if cont > 1.0:
        scale = 1.0 / cont
        call_frac *= scale
        three_frac *= scale

    fold = 1.0 - (call_frac + three_frac)
    return normalize_rcf(three_frac, call_frac, fold)

def freqs_vs_3bet(cfg: Config, hand: str, opener: str, threebettor: str) -> Tuple[float, float, float]:
    """(4bet, call, fold) encoded as (R, C, F)."""
    eq = score_to_equity(chen_score(hand))

    ip = is_in_position(opener, threebettor)
    size3 = cfg.threebet_ip if ip else cfg.threebet_oop

    pot0 = 1.5 + cfg.open_size_bb + size3
    call_cost = max(0.0, size3 - cfg.open_size_bb)
    req_call = required_equity_call(cfg, call_cost, pot0)

    realization = cfg.realize_ip_vs_3bet if ip else cfg.realize_oop_vs_3bet
    eq_eff = clamp01(eq * realization)

    call_frac = clamp01((eq_eff - (req_call - 0.03)) / 0.08)

    tgt4 = target_4bet_pct(opener, threebettor)
    value = clamp01((eq - (0.64 - 0.02)) / 0.05)

    b = blockers(hand)
    bluff_seed = clamp01(0.70 * b - 0.85 * eq + 0.10 * playability(hand))
    bluff = bluff_seed * (0.20 + (0.08 if threebettor in ("SB", "BB") else 0.0))

    four_raw = clamp01(0.85 * value + 0.15 * bluff)
    four_frac = clamp01(four_raw * (tgt4 / 0.04))

    cont = call_frac + four_frac
    if cont > 1.0:
        scale = 1.0 / cont
        call_frac *= scale
        four_frac *= scale

    fold = 1.0 - (call_frac + four_frac)
    return normalize_rcf(four_frac, call_frac, fold)

# -----------------------------
# Spot naming + action labels
# -----------------------------
def spot_type(spot: str) -> str:
    s = spot.upper()
    if s.startswith("RFI_") and "_VS_3BET_" not in s:
        return "RFI"
    if "_VS_3BET_" in s:
        return "VS3B"
    if s.startswith("VS_") and "_OPEN_" in s:
        return "VSOPEN"
    return "OTHER"

def spot_actions(spot: str) -> Tuple[str, str, str]:
    t = spot_type(spot)
    if t == "RFI":
        return ("RAISE", "LIMP", "FOLD")
    if t == "VSOPEN":
        return ("3BET", "CALL", "FOLD")
    if t == "VS3B":
        return ("4BET", "CALL", "FOLD")
    return ("RAISE", "CALL", "FOLD")

def parse_spot_parts(spot: str) -> Tuple[str, str, Optional[str]]:
    s = spot.strip()
    if s.startswith("RFI_") and "_VS_3BET_" not in s:
        return ("RFI", s.split("_", 1)[1], None)
    m = re.match(r"^VS_([A-Z0-9]+)_OPEN_([A-Z0-9]+)$", s, re.IGNORECASE)
    if m:
        return ("VSOPEN", m.group(1).upper(), m.group(2).upper())
    m = re.match(r"^RFI_([A-Z0-9]+)_VS_3BET_([A-Z0-9]+)$", s, re.IGNORECASE)
    if m:
        return ("VS3B", m.group(1).upper(), m.group(2).upper())
    raise ValueError(f"Unrecognized spot: {spot}")

def compute_freqs(cfg: Config, spot: str, hand: str) -> Tuple[float, float, float]:
    t, a, b = parse_spot_parts(spot)
    if t == "RFI":
        return freqs_rfi(cfg, hand, a)
    if t == "VSOPEN":
        return freqs_vs_open(cfg, hand, hero=b, opener=a)  # type: ignore
    if t == "VS3B":
        return freqs_vs_3bet(cfg, hand, opener=a, threebettor=b)  # type: ignore
    return (0.0, 0.0, 1.0)

def sample_action_from_freqs(freqs: Tuple[float, float, float]) -> str:
    r, c, f = freqs
    x = random.random()
    if x < r:
        return "R"
    if x < r + c:
        return "C"
    return "F"

# -----------------------------
# UI
# -----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Poker Preflop Trainer (8-max cash, realtime math-ish, limp-aware)")
        self.geometry("1200x760")

        self.cfg = Config()

        # State
        self.mode = tk.StringVar(value="Practice")  # Practice / Chart
        self.current_spot = tk.StringVar(value="RFI_BTN")
        self.current_hand = tk.StringVar(value="AKs")
        self.lock_spot = tk.BooleanVar(value=False)

        self.score = 0
        self.total = 0
        self.last_sampled: Optional[str] = None

        # NEW: hide mix until answered
        self.answered = False

        self._build_ui()
        self._refresh_all()

    # ---------- Build ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(top, text="Mode:").pack(side=tk.LEFT)
        ttk.OptionMenu(top, self.mode, self.mode.get(), "Practice", "Chart",
                       command=lambda _: self._refresh_all()).pack(side=tk.LEFT, padx=6)

        ttk.Label(top, text="Spot:").pack(side=tk.LEFT, padx=(14, 2))
        self.spot_menu = ttk.Combobox(top, textvariable=self.current_spot, width=32, state="readonly")
        self.spot_menu["values"] = self._all_spots()
        self.spot_menu.bind("<<ComboboxSelected>>", lambda e: self._on_new_question())
        self.spot_menu.pack(side=tk.LEFT)

        ttk.Checkbutton(top, text="Lock spot (Practice)", variable=self.lock_spot).pack(side=tk.LEFT, padx=10)

        ttk.Button(top, text="Random spot", command=self._random_spot).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Random hand", command=self._random_hand).pack(side=tk.LEFT, padx=6)

        ttk.Separator(self).pack(side=tk.TOP, fill=tk.X, pady=4)

        main = ttk.Frame(self, padding=8)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        right = ttk.Frame(main)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(left, text="Variables (live)", font=("Arial", 12, "bold")).pack(anchor="w", pady=(0, 6))

        self._add_num(left, "Open size (bb)", "open_size_bb", 0.5, 6.0, 0.1)
        self._add_num(left, "3bet IP size (bb)", "threebet_ip", 3.0, 20.0, 0.5)
        self._add_num(left, "3bet OOP size (bb)", "threebet_oop", 3.0, 24.0, 0.5)
        self._add_num(left, "Rake %", "rake_pct", 0.0, 0.12, 0.005, is_pct=True)
        self._add_num(left, "Rake cap (bb)", "rake_cap_bb", 0.0, 5.0, 0.1)

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        self._add_num(left, "Call req discount (loosen calls)", "call_req_discount", 0.0, 0.06, 0.005, is_pct=True)
        self._add_num(left, "Realize IP vs open", "realize_ip_vs_open", 0.85, 1.20, 0.01)
        self._add_num(left, "Realize OOP vs open", "realize_oop_vs_open", 0.70, 1.10, 0.01)
        self._add_num(left, "Realize IP vs 3bet", "realize_ip_vs_3bet", 0.80, 1.15, 0.01)
        self._add_num(left, "Realize OOP vs 3bet", "realize_oop_vs_3bet", 0.70, 1.10, 0.01)

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        self.sb_limp_var = tk.BooleanVar(value=self.cfg.sb_limp_enabled)
        ttk.Checkbutton(left, text="Enable SB limps (RFI_SB)", variable=self.sb_limp_var,
                        command=self._on_cfg_change).pack(anchor="w")

        ttk.Separator(left).pack(fill=tk.X, pady=8)

        ttk.Label(left, text="RFI looseness (0..1)", font=("Arial", 10, "bold")).pack(anchor="w")
        self.rfi_vars: Dict[str, tk.DoubleVar] = {}
        for p in ["UTG", "UTG1", "LJ", "HJ", "CO", "BTN", "SB"]:
            v = tk.DoubleVar(value=self.cfg.rfi_loose.get(p, 0.0))
            self.rfi_vars[p] = v
            row = ttk.Frame(left)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=p, width=6).pack(side=tk.LEFT)
            s = ttk.Scale(row, from_=0.0, to=1.0, variable=v, command=lambda _=None: self._on_cfg_change())
            s.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        # Right panels
        self.practice_frame = ttk.Frame(right)
        self.chart_frame = ttk.Frame(right)

        # Practice panel
        ttk.Label(self.practice_frame, text="Practice", font=("Arial", 12, "bold")).pack(anchor="w")

        pr_top = ttk.Frame(self.practice_frame)
        pr_top.pack(fill=tk.X, pady=6)

        ttk.Label(pr_top, text="Hand:").pack(side=tk.LEFT)
        self.hand_entry = ttk.Entry(pr_top, textvariable=self.current_hand, width=8)
        self.hand_entry.pack(side=tk.LEFT, padx=6)
        ttk.Button(pr_top, text="Set hand", command=self._set_hand_from_entry).pack(side=tk.LEFT, padx=4)

        self.prompt_lbl = ttk.Label(self.practice_frame, text="", font=("Arial", 12))
        self.prompt_lbl.pack(anchor="w", pady=(10, 4))

        self.mix_lbl = ttk.Label(self.practice_frame, text="", font=("Consolas", 11))
        self.mix_lbl.pack(anchor="w", pady=(2, 10))

        btns = ttk.Frame(self.practice_frame)
        btns.pack(anchor="w", pady=6)
        self.act_btn1 = ttk.Button(btns, text="A", command=lambda: self._answer(0))
        self.act_btn2 = ttk.Button(btns, text="B", command=lambda: self._answer(1))
        self.act_btn3 = ttk.Button(btns, text="C", command=lambda: self._answer(2))
        for b in (self.act_btn1, self.act_btn2, self.act_btn3):
            b.pack(side=tk.LEFT, padx=6)

        self.result_lbl = ttk.Label(self.practice_frame, text="", justify="left")
        self.result_lbl.pack(anchor="w", pady=(8, 2))

        self.score_lbl = ttk.Label(self.practice_frame, text="Score: 0/0")
        self.score_lbl.pack(anchor="w", pady=(2, 2))

        ttk.Button(self.practice_frame, text="Next (random)", command=self._next_question).pack(anchor="w", pady=8)

        # Chart panel
        ttk.Label(self.chart_frame, text="Chart", font=("Arial", 12, "bold")).pack(anchor="w")
        ttk.Label(self.chart_frame, text="Grid shows R/C/F for each hand class; updates live with variables.").pack(anchor="w", pady=(0, 6))

        chart_controls = ttk.Frame(self.chart_frame)
        chart_controls.pack(fill=tk.X, pady=4)
        ttk.Label(chart_controls, text="Cell display:").pack(side=tk.LEFT)
        self.cell_mode = tk.StringVar(value="Raise%")
        ttk.OptionMenu(chart_controls, self.cell_mode, self.cell_mode.get(), "Raise%", "Call%", "Fold%", "All",
                       command=lambda _: self._refresh_chart()).pack(side=tk.LEFT, padx=6)

        self.chart_canvas = tk.Canvas(self.chart_frame, bg="white", highlightthickness=1, highlightbackground="#ccc")
        self.chart_canvas.pack(fill=tk.BOTH, expand=True, pady=6)
        self.chart_canvas.bind("<Button-1>", self._chart_click)

    def _add_num(self, parent, label, attr, mn, mx, step, is_pct=False):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, pady=2)
        ttk.Label(frame, text=label, width=26).pack(side=tk.LEFT)

        var = tk.DoubleVar(value=getattr(self.cfg, attr))
        entry = ttk.Entry(frame, textvariable=var, width=10)
        entry.pack(side=tk.LEFT, padx=4)

        def on_entry(_=None):
            try:
                val = float(var.get())
                if is_pct and val > 1.0:
                    val = val / 100.0
                    var.set(val)
                val = max(mn, min(mx, val))
                setattr(self.cfg, attr, val)
                self._on_cfg_change()
            except Exception:
                pass

        entry.bind("<Return>", on_entry)
        entry.bind("<FocusOut>", on_entry)

        scale = ttk.Scale(frame, from_=mn, to=mx, command=lambda _: on_entry())
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        def sync_scale():
            try:
                scale.set(float(var.get()))
            except Exception:
                pass

        sync_scale()
        var.trace_add("write", lambda *_: sync_scale())
        scale.configure(command=lambda val: var.set(float(val)))
        var.trace_add("write", lambda *_: on_entry())

    # ---------- Spots ----------
    def _all_spots(self) -> List[str]:
        spots = []
        for p in POSITIONS:
            if p != "BB":
                spots.append(f"RFI_{p}")
        for opener in POSITIONS:
            if opener == "BB":
                continue
            for hero in POSITIONS:
                if POS_I[hero] > POS_I[opener]:
                    spots.append(f"VS_{opener}_OPEN_{hero}")
        for opener in POSITIONS:
            if opener == "BB":
                continue
            for tb in POSITIONS:
                if POS_I[tb] > POS_I[opener]:
                    spots.append(f"RFI_{opener}_VS_3BET_{tb}")
        return spots

    # ---------- Events ----------
    def _on_cfg_change(self):
        self.cfg.sb_limp_enabled = bool(self.sb_limp_var.get())
        for p, v in self.rfi_vars.items():
            self.cfg.rfi_loose[p] = float(v.get())
        self._refresh_all()

    def _on_new_question(self):
        # any manual change to spot/hand resets "answered"
        self.answered = False
        self.result_lbl.config(text="")
        self._refresh_all()

    def _set_hand_from_entry(self):
        try:
            self.current_hand.set(parse_hand_label(self.current_hand.get()))
        except Exception:
            pass
        self._on_new_question()

    def _random_hand(self):
        self.current_hand.set(random.choice(ALL_169))
        self._on_new_question()

    def _random_spot(self):
        self.current_spot.set(random.choice(self._all_spots()))
        self._on_new_question()

    # ---------- Practice ----------
    def _next_question(self):
        if not self.lock_spot.get():
            self.current_spot.set(random.choice(self._all_spots()))
        self.current_hand.set(random.choice(ALL_169))
        self.answered = False
        self.result_lbl.config(text="")
        self._refresh_practice()

    def _answer(self, idx: int):
        spot = self.current_spot.get()
        hand = self.current_hand.get()

        freqs = compute_freqs(self.cfg, spot, hand)  # (R,C,F)
        sampled = sample_action_from_freqs(freqs)    # "R"/"C"/"F"
        self.last_sampled = sampled

        labels = spot_actions(spot)  # (action1, action2, action3)
        chosen = ["R", "C", "F"][idx]

        r, c, f = freqs
        chosen_pct = {"R": r, "C": c, "F": f}[chosen]
        sampled_pct = {"R": r, "C": c, "F": f}[sampled]

        chosen_label = labels[["R","C","F"].index(chosen)]
        sampled_label = labels[["R","C","F"].index(sampled)]

        self.total += 1
        if chosen == sampled:
            self.score += 1
            verdict = "✅ Correct (mixed-frequency draw)"
        else:
            verdict = "❌ Not this time"

        # Mark answered so mix becomes visible
        self.answered = True

        breakdown = (
            f"{verdict}\n"
            f"Mix: {labels[0]} {fmt_pct(r)}   {labels[1]} {fmt_pct(c)}   {labels[2]} {fmt_pct(f)}\n"
            f"You chose: {chosen_label} ({fmt_pct(chosen_pct)})\n"
            f"Sampled: {sampled_label} ({fmt_pct(sampled_pct)})"
        )

        self.result_lbl.config(text=breakdown)
        self.score_lbl.config(text=f"Score: {self.score}/{self.total}")
        self._refresh_practice()

    # ---------- Refresh ----------
    def _refresh_all(self):
        try:
            self.current_hand.set(parse_hand_label(self.current_hand.get()))
        except Exception:
            pass

        if self.mode.get() == "Practice":
            self.chart_frame.pack_forget()
            self.practice_frame.pack(fill=tk.BOTH, expand=True)
            self._refresh_practice()
        else:
            self.practice_frame.pack_forget()
            self.chart_frame.pack(fill=tk.BOTH, expand=True)
            self._refresh_chart()

    def _refresh_practice(self):
        spot = self.current_spot.get()
        hand = self.current_hand.get()

        try:
            freqs = compute_freqs(self.cfg, spot, hand)
        except Exception as e:
            self.prompt_lbl.config(text=f"Error: {e}")
            return

        a1, a2, a3 = spot_actions(spot)
        self.act_btn1.config(text=a1)
        self.act_btn2.config(text=a2)
        self.act_btn3.config(text=a3)

        self.prompt_lbl.config(text=f"Spot: {spot}    Hand: {hand}    Choose: {a1} / {a2} / {a3}")

        # IMPORTANT: hide mix until answered
        r, c, f = freqs
        if self.answered:
            self.mix_lbl.config(text=f"Mix: {a1} {fmt_pct(r)}   {a2} {fmt_pct(c)}   {a3} {fmt_pct(f)}")
        else:
            self.mix_lbl.config(text="")

    # ---------- Chart drawing ----------
    def _refresh_chart(self):
        spot = self.current_spot.get()
        mode = self.cell_mode.get()

        w = self.chart_canvas.winfo_width()
        h = self.chart_canvas.winfo_height()
        if w < 50 or h < 50:
            return

        self.chart_canvas.delete("all")

        pad = 10
        header = 24
        bottom_text = 26

        usable_w = max(10, w - pad*2 - header)
        usable_h = max(10, h - pad*2 - header - bottom_text)

        cell = min(usable_w / 13, usable_h / 13)
        cell = max(10, cell)  # don't clip; just shrink cells

        x0 = pad
        y0 = pad

        a1, a2, a3 = spot_actions(spot)

        # Title (inside canvas to avoid negative y)
        self.chart_canvas.create_text(
            x0, y0, anchor="nw",
            text=f"{spot}   (R={a1}, C={a2}, F={a3})   Display: {mode}"
        )

        # Headers
        for j, rnk in enumerate(CHART_RANKS):
            x = x0 + header + j * cell + cell/2
            self.chart_canvas.create_text(x, y0 + header/2, text=rnk)
        for i, rnk in enumerate(CHART_RANKS):
            y = y0 + header + i * cell + cell/2
            self.chart_canvas.create_text(x0 + header/2, y, text=rnk)

        # Cells
        for i, rr in enumerate(CHART_RANKS):
            for j, cc in enumerate(CHART_RANKS):
                hand = cell_hand_label(rr, cc)
                r, c, f = compute_freqs(self.cfg, spot, hand)

                x1 = x0 + header + j * cell
                y1 = y0 + header + i * cell
                x2 = x1 + cell
                y2 = y1 + cell

                shade = int(255 - (r * 140))
                shade = max(90, min(255, shade))
                fill = f"#{shade:02x}{shade:02x}{shade:02x}"

                self.chart_canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline="#ddd")

                if mode == "Raise%":
                    txt = f"{round(r*100)}"
                elif mode == "Call%":
                    txt = f"{round(c*100)}"
                elif mode == "Fold%":
                    txt = f"{round(f*100)}"
                else:
                    txt = f"{round(r*100)}/{round(c*100)}/{round(f*100)}"

                self.chart_canvas.create_text((x1+x2)/2, (y1+y2)/2, text=txt, font=("Consolas", 9))

        # Border
        grid_x1 = x0 + header
        grid_y1 = y0 + header
        grid_x2 = x0 + header + 13*cell
        grid_y2 = y0 + header + 13*cell
        self.chart_canvas.create_rectangle(grid_x1, grid_y1, grid_x2, grid_y2, outline="#aaa")

        # Help text
        self.chart_canvas.create_text(
            x0, grid_y2 + 6, anchor="nw",
            text="Tip: click a cell to set Practice hand to that combo class."
        )

        # Scrollregion (optional, but keeps bounds sane)
        self.chart_canvas.config(scrollregion=(0, 0, max(w, grid_x2 + pad), max(h, grid_y2 + pad + 40)))

    def _chart_click(self, event):
        w = self.chart_canvas.winfo_width()
        h = self.chart_canvas.winfo_height()
        pad = 10
        header = 24
        cell = min((w - pad*2 - header) / 13, (h - pad*2 - header) / 13)
        cell = max(18, min(cell, 46))
        x0 = pad
        y0 = pad

        gx = event.x - (x0 + header)
        gy = event.y - (y0 + header)
        if gx < 0 or gy < 0:
            return
        j = int(gx // cell)
        i = int(gy // cell)
        if not (0 <= i < 13 and 0 <= j < 13):
            return
        rr = CHART_RANKS[i]
        cc = CHART_RANKS[j]
        hand = cell_hand_label(rr, cc)
        self.current_hand.set(hand)
        self.mode.set("Practice")
        self.answered = False
        self.result_lbl.config(text="")
        self._refresh_all()

# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    app = App()
    app.mainloop()