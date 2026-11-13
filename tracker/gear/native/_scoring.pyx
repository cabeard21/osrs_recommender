# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Typed numerical scoring; all candidate loops operate on C values."""

from libc.math cimport floor, pow, fabs, isfinite
from libc.string cimport memset


cdef double accuracy_for(long long attack, long long defence) noexcept nogil:
    if attack < 0:
        attack = 0
    if defence < 0:
        defence = 0
    if attack > defence:
        return 1.0 - (defence + 2) / <double>(2 * (attack + 1))
    return attack / <double>(2 * (defence + 1))


cdef double armoured_mean(long long maximum, long long armour) noexcept nogil:
    cdef long long first = max(1, armour + 1)
    cdef long long count = max(0, maximum - first + 1)
    cdef double positive_sum = count * (first + maximum - 2 * armour) / 2.0
    return (max(0, 1 - armour) + positive_sum) / (maximum + 1)


cdef class ScoringContext:
    def __init__(self, search):
        from tracker.gear.native.packing import pack
        packed = pack(search)
        self.item_count = packed["item_count"]
        self.role_count = packed["role_count"]
        self.dense_ids = packed["dense_ids"]
        self.dense_index = packed["dense_index"]
        self.option_records = packed["option_records"]
        self.option_weapons = packed["option_weapons"]
        self.original_ids = packed["original_ids"]
        self.item_bonuses = packed["item_bonuses"]
        self.item_magic_damage = packed["item_magic_damage"]
        self.item_slots = packed["item_slots"]
        self.two_handed = packed["two_handed"]
        self.eligible = packed["eligible"]
        self.bad_items = packed["bad_items"]
        self.ammo_required = packed["ammo_required"]
        self.ammo_types = packed["ammo_types"]
        self.ammo_offsets = packed["ammo_offsets"]
        self.ammo_codes = packed["ammo_codes"]
        self.offsets = packed["offsets"]
        self.lengths = packed["lengths"]
        self.options = packed["options"]
        self.fixed_roles = packed["fixed_roles"]
        self.role_styles = packed["role_styles"]
        self.priority = packed["priority"]

    cdef double secondary_for(self, const double* bonuses, double accuracy, int option_index) noexcept nogil:
        cdef double rolls[5]
        cdef double physical, magical
        cdef int index
        if self.priority >= 20:
            if option_index < 0:
                return 0.0
            physical = self.options[option_index * 18 + 16]
            magical = self.options[option_index * 18 + 17]
            for index in range(5):
                rolls[index] = max(0.0, (magical if index == 4 else physical) * (bonuses[index + 8] + 64))
            if self.priority == 20:
                return (rolls[0] + rolls[1] + rolls[2] + rolls[3] + rolls[4]) / 5.0
            if self.priority == 21:
                return min(rolls[3], rolls[4])
            return rolls[self.priority - 22]
        if self.priority == 0:
            return 0.0
        if self.priority == 1:
            return (bonuses[8] + bonuses[9] + bonuses[10] + bonuses[11] + bonuses[12]) / 5.0
        if self.priority == 2:
            return min(bonuses[11], bonuses[12])
        if self.priority == 3:
            return accuracy
        return bonuses[self.priority - 4]

    cdef void evaluate(self, const int* slots, int role_index, bint metric, Score* output, const int* order=NULL) noexcept nogil:
        cdef int slot, item, field, weapon = slots[0], ammo = slots[2]
        cdef int start, length, index, base, style, pattern, best_tie = -1, tie, position
        cdef bint legal = True, ammo_ok = False, ranged
        cdef double bonuses[14]
        cdef long long maximum, attack, defence, strength, armor, cap, first, second
        cdef double accuracy, dps, expected, secondary, second_probability, magic_bonus, term, hi=0.0, lo=0.0, total
        memset(output, 0, sizeof(Score))
        output.option_index = -1
        memset(bonuses, 0, sizeof(bonuses))
        for position in range(11):
            slot = order[position] if order != NULL else position
            if slot < 0:
                continue
            item = slots[slot]
            if item:
                if self.item_slots[item] != slot or self.bad_items[item]:
                    legal = False
                for field in range(14):
                    bonuses[field] += self.item_bonuses[item * 14 + field]
                # CPython 3.12's compensated floating sum, in equipment order.
                term = self.item_magic_damage[item]
                total = hi + term
                if fabs(hi) >= fabs(term):
                    lo += (hi - total) + term
                else:
                    lo += (term - total) + hi
                hi = total
        bonuses[7] = hi + lo if lo and isfinite(lo) else hi
        for field in range(14):
            output.bonuses[field] = bonuses[field]
        if self.fixed_roles[role_index]:
            if self.role_styles[role_index] == 3 and ammo and not self.ammo_required[weapon]:
                output.bonuses[3] -= self.item_bonuses[ammo * 14 + 3]
                output.bonuses[6] -= self.item_bonuses[ammo * 14 + 6]
            output.secondary = self.secondary_for(output.bonuses, 0.0, -1)
        if not legal or (weapon and self.two_handed[weapon] and slots[1]):
            return
        if self.ammo_required[weapon]:
            if ammo:
                for index in range(self.ammo_offsets[weapon], self.ammo_offsets[weapon + 1]):
                    if self.ammo_codes[index] == self.ammo_types[ammo]:
                        ammo_ok = True
                        break
        else:
            ammo_ok = True
        base = ((<int>metric * self.role_count + role_index) * self.item_count + weapon)
        start, length = self.offsets[base], self.lengths[base]
        for index in range(start, start + length):
            base = index * 18
            if not self.options[base + 9]:
                continue
            style = <int>self.options[base]
            ranged = style == 3
            if ranged and not ammo_ok:
                continue
            strength = <long long>bonuses[6 if ranged else 5]
            attack = <long long>bonuses[style]
            if ranged and ammo and not self.ammo_required[weapon]:
                strength -= self.item_bonuses[ammo * 14 + 6]
                attack -= self.item_bonuses[ammo * 14 + 3]
            if style == 4:
                magic_bonus = min(100.0, bonuses[7] * 3) if self.options[base + 12] else bonuses[7]
                maximum = <long long>floor(self.options[base + 10] * (100 + magic_bonus + self.options[base + 11]) / 100.0)
                maximum += self.options[base + 14]
                if self.options[base + 12]:
                    attack *= 3
            else:
                maximum = <long long>floor(0.5 + self.options[base + 2] * (strength + 64) / 640.0)
            if maximum < 0:
                maximum = 0
            attack = self.options[base + 1] * (attack + 64)
            if style == 4:
                attack += <long long>floor(attack * self.options[base + 13] / 100.0)
            defence = self.options[base + 3]
            pattern, armor, cap = <int>self.options[base + 5], self.options[base + 6], self.options[base + 7]
            if pattern == 0:
                first, second = maximum, 0
            else:
                first = maximum // 2
                second = maximum - first
            if cap >= 0 and (max(1, first) + 8 * self.options[base + 15] > cap or (pattern != 0 and max(1, second) > cap)):
                continue
            accuracy = accuracy_for(attack, defence)
            expected = 0.0 + accuracy * armoured_mean(first, armor)
            if pattern != 0:
                second_probability = pow(accuracy, 2.0) if pattern == 2 else accuracy
                expected += second_probability * armoured_mean(second, armor)
            if self.options[base + 15]:
                expected += accuracy * 0.2 * 8
            dps = expected / (self.options[base + 4] * 0.6)
            secondary = self.secondary_for(bonuses, accuracy, index)
            # Ranged offensive bonus priorities use the ammunition-adjusted view.
            if ranged and ammo and not self.ammo_required[weapon] and self.priority == 10:
                secondary -= self.item_bonuses[ammo * 14 + 6]
            tie = <int>self.options[base + 8]
            if output.supported:
                if metric:
                    if secondary < output.secondary:
                        continue
                    if secondary == output.secondary and dps < output.dps:
                        continue
                    if secondary == output.secondary and dps == output.dps and tie <= best_tie:
                        continue
                else:
                    if dps < output.dps or (dps == output.dps and tie <= best_tie):
                        continue
            output.supported = True
            output.dps, output.accuracy, output.secondary = dps, accuracy, secondary
            output.option_index = index
            output.interval = self.options[base + 4] * 0.6
            best_tie = tie
        if output.supported:
            base = output.option_index * 18
            for field in range(5):
                term = self.options[base + (17 if field == 4 else 16)]
                output.defence_rolls[field] = max(0.0, term * (bonuses[field + 8] + 64)) if term >= 0 else -1.0
                if term < 0:
                    output.missing_defence = True
        if output.supported and self.options[output.option_index * 18] == 3 and ammo and not self.ammo_required[weapon]:
            output.bonuses[3] = bonuses[3] - self.item_bonuses[ammo * 14 + 3]
            output.bonuses[6] = bonuses[6] - self.item_bonuses[ammo * 14 + 6]

    def score(self, equipment, int role_index, bint metric=False):
        from tracker.gear.compact_states import SLOT_NAMES
        cdef int slots[11]
        cdef int order[11]
        cdef Score result
        cdef int index
        cdef object needed
        if role_index < 0 or role_index >= self.role_count:
            raise ValueError("Invalid native role index")
        memset(slots, 0, sizeof(slots))
        memset(order, -1, sizeof(order))
        index = 0
        for slot, item in equipment.items():
            if slot not in SLOT_NAMES or type(item) is not int or item not in self.dense_index or item == 0:
                raise ValueError("Invalid native equipment")
            slots[SLOT_NAMES.index(slot)] = self.dense_index[item]
            order[index] = SLOT_NAMES.index(slot)
            index += 1
        self.evaluate(slots, role_index, metric, &result, order)
        if result.supported and self.priority >= 20:
            if self.priority == 20:
                needed = range(5)
            elif self.priority == 21:
                needed = (3, 4)
            else:
                needed = (self.priority - 22,)
            for index in needed:
                if result.defence_rolls[index] < 0:
                    raise ValueError("Player defensive roll is unavailable: required combat levels are unknown")
        return {
            "supported": bool(result.supported),
            "dps": result.dps if result.supported else None,
            "accuracy": result.accuracy if result.supported else None,
            "secondary": result.secondary,
            "interval": result.interval if result.supported else None,
            "player_defence_rolls": {name: result.defence_rolls[index] if result.defence_rolls[index] >= 0 else None for index, name in enumerate(("stab", "slash", "crush", "ranged", "magic"))},
            "option_index": result.option_index,
            "bonuses": tuple(result.bonuses[index] for index in range(14)),
        }
