import random
import re
from dataclasses import dataclass
from typing import List, Tuple, Dict, Set, Optional

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_TO_I = {r: i for i, r in enumerate(RANKS)}

POSITIONS_6MAX = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

# ----------------------------
# Hand + combo helpers
# ----------------------------
@dataclass(frozen=True)
class Hand:
    r1: str
    r2: str
    suited: Optional[bool]  # True = suited, False = offsuit, None = pair

    def label(self) -> str:
        a, b = self.r1, self.r2
        if a == b:
            return a + a
        hi, lo = (a, b) if RANK_TO_I[a] > RANK_TO_I[b] else (b, a)
        return f"{hi}{lo}{'s' if self.suited else 'o'}"

def all_hands() -> List[Hand]:
    hands = []
    for i, a in enumerate(RANKS):
        for j, b in enumerate(RANKS):
            if i < j:
                # non-pair: both suited + offsuit
                hands.append(Hand(a, b, True))
                hands.append(Hand(a, b, False))
            elif i == j:
                hands.append(Hand(a, a, None))
    return hands

ALL_HANDS = all_hands()

def random_hand() -> Hand:
    return random.choice(ALL_HANDS)

# ----------------------------
# Range parsing (like "AJs+", "77+", "KQo", "ATs-A8s")
# Produces a set of hand labels like {"AJs", "AQs", ...}
# ----------------------------
def expand_token(token: str) -> Set[str]:
    token = token.strip()
    if not token:
        return set()

    # Range with dash: "A5s-A2s", "KQo-KJo"
    if "-" in token:
        left, right = token.split("-", 1)
        return expand_dash(left.strip(), right.strip())

    # Plus: "AJs+", "77+"
    if token.endswith("+"):
        base = token[:-1]
        return expand_plus(base)

    # Exact: "KQo", "ATs", "JJ"
    return expand_exact(token)

def expand_exact(t: str) -> Set[str]:
    # Pair
    if len(t) == 2 and t[0] in RANKS and t[1] == t[0]:
        return {t}
    # Suited/offsuit
    if len(t) == 3 and t[0] in RANKS and t[1] in RANKS and t[2] in "so":
        a, b, x = t[0], t[1], t[2]
        if a == b:
            return {a + a}
        # Normalize to hi/lo order
        hi, lo = (a, b) if RANK_TO_I[a] > RANK_TO_I[b] else (b, a)
        return {f"{hi}{lo}{x}"}
    raise ValueError(f"Bad range token: {t}")

def expand_plus(base: str) -> Set[str]:
    out = set()

    # Pair like "77+"
    if len(base) == 2 and base[0] in RANKS and base[1] == base[0]:
        start = RANK_TO_I[base[0]]
        for r in RANKS[start:]:
            out.add(r + r)
        return out

    # Non-pair like "AJs+"
    if len(base) == 3 and base[0] in RANKS and base[1] in RANKS and base[2] in "so":
        a, b, x = base[0], base[1], base[2]
        if a == b:
            return {a + a}
        # We interpret "AJs+" as: AJ, AQ, AK (same first rank, kicker increases)
        fixed = a
        kicker_start = b
        # Ensure fixed is the higher rank in the label
        # Common poker notation assumes first char is the higher rank already (A,K,Q,...)
        # We'll allow if it's not: normalize and keep the suited flag.
        if RANK_TO_I[fixed] < RANK_TO_I[kicker_start]:
            fixed, kicker_start = kicker_start, fixed

        start_i = RANK_TO_I[kicker_start]
        fixed_i = RANK_TO_I[fixed]
        for k in RANKS[start_i:fixed_i]:
            hi, lo = fixed, k
            if hi == lo:
                continue
            out.add(f"{hi}{lo}{x}")
        return out

    raise ValueError(f"Bad + token: {base}+")

def expand_dash(left: str, right: str) -> Set[str]:
    # Must be same "shape": e.g. "A5s-A2s" or "KQo-KJo"
    L = list(expand_exact(left))[0]
    R = list(expand_exact(right))[0]
    out = set()

    # Pairs: "99-66"
    if len(L) == 2 and len(R) == 2:
        start = RANK_TO_I[R[0]]
        end = RANK_TO_I[L[0]]
        if start > end:
            start, end = end, start
        for r in RANKS[start:end + 1]:
            out.add(r + r)
        return out

    # Non-pairs: "A5s-A2s" etc. First rank must match, suited flag must match
    if len(L) == 3 and len(R) == 3 and L[0] == R[0] and L[2] == R[2]:
        fixed = L[0]
        x = L[2]
        k1 = L[1]
        k2 = R[1]
        i1 = RANK_TO_I[k1]
        i2 = RANK_TO_I[k2]
        lo = min(i1, i2)
        hi = max(i1, i2)
        fixed_i = RANK_TO_I[fixed]
        for idx in range(lo, hi + 1):
            k = RANKS[idx]
            if k == fixed:
                continue
            # Ensure label order hi/lo
            a, b = fixed, k
            if RANK_TO_I[a] < RANK_TO_I[b]:
                a, b = b, a
            out.add(f"{a}{b}{x}")
        return out

    raise ValueError(f"Bad dash token: {left}-{right}")

def parse_range(s: str) -> Set[str]:
    s = s.replace(" ", "")
    if not s:
        return set()
    tokens = s.split(",")
    out = set()
    for tok in tokens:
        out |= expand_token(tok)
    return out

# ----------------------------
# Simplified "GTO-ish" preflop charts (6-max, ~100bb)
# These are intentionally conservative + easy to drill.
# ----------------------------
OPEN_RANGES: Dict[str, str] = {
    "UTG": "22+,AJs+,KQs,AQo+ ,ATs,KJs,QJs,JTs,T9s,98s",
    "HJ":  "22+,ATs+,KQs,KJs,QJs,JTs,T9s,98s,87s, AQo+,KQo",
    "CO":  "22+,A9s+,KTs+,QTs+,JTs,T9s,98s,87s,76s,65s, ATo+,KJo+,QJo",
    "BTN": "22+,A2s+,K7s+,Q8s+,J8s+,T8s+,98s,87s,76s,65s,54s, A8o+,KTo+,QTo+,JTo",
    "SB":  "22+,A2s+,K8s+,Q9s+,J9s+,T9s,98s,87s,76s,65s, A9o+,KTo+,QTo+,JTo",
}

# Versus an open: simplified 3bet range (linear-ish, no mixed frequencies)
THREEBET_VS_OPEN: Dict[Tuple[str, str], str] = {
    # (hero_pos, opener_pos) -> 3bet range
    ("BTN", "CO"): "99+,AQs+,AKo, AJs,KQs",
    ("BTN", "HJ"): "TT+,AQs+,AKo, KQs",
    ("BTN", "UTG"): "JJ+,AKs,AKo",
    ("CO", "HJ"):  "TT+,AQs+,AKo, AJs,KQs",
    ("CO", "UTG"): "JJ+,AKs,AKo",
    ("SB", "CO"):  "TT+,AQs+,AKo, AJs,KQs",
    ("SB", "BTN"): "TT+,AQs+,AKo, AJs,KQs",
    ("BB", "BTN"): "TT+,AQs+,AKo",
}

# Optional flat-call ranges vs open (very simplified)
CALL_VS_OPEN: Dict[Tuple[str, str], str] = {
    ("BTN", "CO"): "22-88,A2s-A9s,KTs-KJs,QTs-QJs,JTs,T9s,98s,87s, AJo,KQo",
    ("CO", "HJ"):  "22-99,A2s-AQs,KTs-KQs,QTs-QJs,JTs,T9s,98s, AJo",
    ("BTN", "HJ"): "22-99,A2s-AQs,KJs-KQs,QJs,JTs,T9s,98s, AJo",
    ("SB", "BTN"): "22-99,A2s-AQs,KTs-KQs,QTs-QJs,JTs,T9s,98s",
    ("BB", "BTN"): "22-99,A2s-AQs,KTs-KQs,QTs-QJs,JTs,T9s,98s,87s,76s,65s, ATo-AQo,KJo-KQo,QJo",
}

# Vs a 3bet after you open: simplified continue ranges (call or 4bet)
CONTINUE_VS_3BET: Dict[Tuple[str, str], Dict[str, str]] = {
    # (hero_open_pos, threebettor_pos): {"4bet": "...", "call": "..."}
    ("CO", "BTN"): {"4bet": "QQ+,AKs,AKo", "call": "99-JJ,AQs-AJs,KQs"},
    ("HJ", "CO"):  {"4bet": "QQ+,AKs,AKo", "call": "TT-JJ,AQs"},
    ("UTG", "HJ"): {"4bet": "QQ+,AKs,AKo", "call": "JJ,AQs"},
    ("BTN", "SB"): {"4bet": "QQ+,AKs,AKo,AQs", "call": "99-JJ,AJs,KQs"},
}

def in_range(hand: Hand, rset: Set[str]) -> bool:
    return hand.label() in rset

def advice_open(hand: Hand, pos: str) -> Tuple[str, str]:
    rset = parse_range(OPEN_RANGES[pos])
    if in_range(hand, rset):
        return ("RAISE", f"Open-raise from {pos}.")
    return ("FOLD", f"Fold from {pos} (not in simplified open range).")

def advice_vs_open(hand: Hand, hero_pos: str, opener_pos: str) -> Tuple[str, str]:
    key = (hero_pos, opener_pos)
    t3 = parse_range(THREEBET_VS_OPEN.get(key, ""))
    tc = parse_range(CALL_VS_OPEN.get(key, ""))

    if t3 and in_range(hand, t3):
        return ("3BET", f"3bet vs {opener_pos} (strong value / pressure range).")
    if tc and in_range(hand, tc):
        return ("CALL", f"Call vs {opener_pos} (playable, keeps weaker hands in).")
    return ("FOLD", f"Fold vs {opener_pos} (too weak for this spot).")

def advice_vs_3bet(hand: Hand, hero_open_pos: str, threebettor_pos: str) -> Tuple[str, str]:
    key = (hero_open_pos, threebettor_pos)
    pack = CONTINUE_VS_3BET.get(key)
    if not pack:
        # fallback: tight generic
        four = parse_range("QQ+,AKs,AKo")
        call = parse_range("TT-JJ,AQs-AJs,KQs")
    else:
        four = parse_range(pack["4bet"])
        call = parse_range(pack["call"])

    if in_range(hand, four):
        return ("4BET", f"4bet for value / deny equity vs {threebettor_pos}.")
    if in_range(hand, call):
        return ("CALL", f"Call the 3bet (strong but not always a 4bet).")
    return ("FOLD", f"Fold vs 3bet (dominated / poor playability).")

# ----------------------------
# Training loop
# ----------------------------
SCENARIOS = ["OPEN", "VS_OPEN", "VS_3BET"]

def pick_positions_for_scenario(scn: str) -> Tuple[str, Optional[str]]:
    if scn == "OPEN":
        pos = random.choice(["UTG", "HJ", "CO", "BTN", "SB"])
        return pos, None
    if scn == "VS_OPEN":
        # choose hero behind opener
        opener = random.choice(["UTG", "HJ", "CO", "BTN"])
        valid_behind = [p for p in POSITIONS_6MAX if POSITIONS_6MAX.index(p) > POSITIONS_6MAX.index(opener)]
        hero = random.choice(valid_behind)
        return hero, opener
    if scn == "VS_3BET":
        hero_open = random.choice(["UTG", "HJ", "CO", "BTN"])
        # 3bettor behind
        behind = [p for p in POSITIONS_6MAX if POSITIONS_6MAX.index(p) > POSITIONS_6MAX.index(hero_open)]
        threebettor = random.choice(behind)
        return hero_open, threebettor
    raise ValueError("unknown scenario")

def print_quick_help():
    print("\nCommands:")
    print("  a) choose action shown in prompt")
    print("  r) reveal ranges for the spot")
    print("  s) switch scenario mix (open / vs open / vs 3bet)")
    print("  q) quit\n")

def reveal_ranges_open(pos: str):
    print(f"Open range {pos}: {OPEN_RANGES[pos]}")

def reveal_ranges_vs_open(hero: str, opener: str):
    key = (hero, opener)
    print(f"3bet range {hero} vs {opener}: {THREEBET_VS_OPEN.get(key, '(none defined)')}")
    print(f"call range  {hero} vs {opener}: {CALL_VS_OPEN.get(key, '(none defined)')}")

def reveal_ranges_vs_3bet(hero_open: str, threebettor: str):
    key = (hero_open, threebettor)
    pack = CONTINUE_VS_3BET.get(key)
    if pack:
        print(f"4bet range {hero_open} vs 3bet from {threebettor}: {pack['4bet']}")
        print(f"call  range {hero_open} vs 3bet from {threebettor}: {pack['call']}")
    else:
        print("No exact chart for this spot (using tight fallback): QQ+,AKs,AKo (4bet) and TT-JJ,AQs-AJs,KQs (call)")

def main():
    print("=== Poker Preflop Practice (Simplified GTO-ish Advice) ===")
    print("This trainer drills common 6-max preflop spots with conservative solver-inspired ranges.")
    print("Not a real GTO solver. Use it for repetition + pattern learning.\n")
    print_quick_help()

    scenario_mix = ["OPEN", "VS_OPEN", "VS_3BET"]
    score = 0
    total = 0

    while True:
        scn = random.choice(scenario_mix)
        h = random_hand()

        if scn == "OPEN":
            pos, _ = pick_positions_for_scenario("OPEN")
            correct, why = advice_open(h, pos)
            prompt_actions = ["RAISE", "FOLD"]

            print(f"\nSpot: Folds to you. You are {pos}. Hand: {h.label()}")
            print(f"Choose action: {', '.join(prompt_actions)}")

        elif scn == "VS_OPEN":
            hero, opener = pick_positions_for_scenario("VS_OPEN")
            correct, why = advice_vs_open(h, hero, opener)
            prompt_actions = ["FOLD", "CALL", "3BET"]

            print(f"\nSpot: {opener} opens. You are {hero}. Hand: {h.label()}")
            print(f"Choose action: {', '.join(prompt_actions)}")

        else:  # VS_3BET
            hero_open, threebettor = pick_positions_for_scenario("VS_3BET")
            correct, why = advice_vs_3bet(h, hero_open, threebettor)
            prompt_actions = ["FOLD", "CALL", "4BET"]

            print(f"\nSpot: You open from {hero_open}. {threebettor} 3bets. Hand: {h.label()}")
            print(f"Choose action: {', '.join(prompt_actions)}")

        cmd = input("> ").strip().upper()

        if cmd == "Q":
            break
        if cmd == "H":
            print_quick_help()
            continue
        if cmd == "S":
            print("\nCurrent mix:", scenario_mix)
            print("Type a comma list from: OPEN,VS_OPEN,VS_3BET (example: OPEN,VS_OPEN)")
            newmix = input("new mix> ").strip().upper().replace(" ", "")
            if newmix:
                items = [x for x in newmix.split(",") if x in SCENARIOS]
                if items:
                    scenario_mix = items
                    print("Updated mix:", scenario_mix)
                else:
                    print("No valid scenarios found, keeping previous.")
            continue
        if cmd == "R":
            if scn == "OPEN":
                reveal_ranges_open(pos)
            elif scn == "VS_OPEN":
                reveal_ranges_vs_open(hero, opener)  # type: ignore
            else:
                reveal_ranges_vs_3bet(hero_open, threebettor)  # type: ignore
            continue

        # Treat input as action
        action = cmd
        if action not in prompt_actions:
            print("Invalid action. Type H for help.")
            continue

        total += 1
        if action == correct:
            score += 1
            print(f"✅ Correct: {correct}. {why}")
        else:
            print(f"❌ Your action: {action} | Suggested: {correct}")
            print(f"Reason: {why}")

        print(f"Score: {score}/{total} ({(score/total)*100:.1f}%)")

    print(f"\nFinal score: {score}/{total} ({(score/total)*100:.1f}%)")
    print("Bye!")

if __name__ == "__main__":
    main()