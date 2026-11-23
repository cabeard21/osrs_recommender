# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Typed numerical scoring; all candidate loops operate on C values."""

from libc.math cimport floor, pow, fabs, isfinite
from libc.string cimport memset
from libcpp.vector cimport vector
from tracker.gear.native._effects cimport (
    BoltResult, bolt_damage, damage_mean, floor_div, marked_damage_total, vampyre_hit,
    vampyre_mean, positive_chance, V_LEGAL, V_WEAPON_ACCURACY, V_RING_ACCURACY, V_WIDTH,
)

from tracker.gear.compact_states import SLOT_NAMES


cdef double retention_distance(vector[double]& values, size_t dimensions, size_t first, size_t second) noexcept nogil:
    """CPython 3.12 compensated float sum, with the same squared-distance terms."""
    cdef size_t dimension
    cdef double difference, term, total, hi = 0.0, lo = 0.0
    for dimension in range(dimensions):
        difference = values[first * dimensions + dimension] - values[second * dimensions + dimension]
        term = pow(fabs(difference), 2.0)
        total = hi + term
        if fabs(hi) >= fabs(term):
            lo += (hi - total) + term
        else:
            lo += (term - total) + hi
        hi = total
    return hi + lo if lo and isfinite(lo) else hi


def farthest_indices(vectors, int limit):
    """Exact farthest-point retention for vectors already sorted by physical identity."""
    cdef size_t count = len(vectors), dimensions, index, dimension, maximum, minimum, anchor, chosen, target
    cdef vector[double] values, ranges, nearest
    cdef vector[unsigned char] included
    cdef vector[size_t] selected
    cdef double value, candidate_distance, best_distance
    if not count:
        return []
    dimensions = len(vectors[0])
    if not 1 <= dimensions <= 65:
        raise ValueError("Unsupported native retention dimensions")
    values.resize(count * dimensions)
    ranges.resize(dimensions)
    nearest.resize(count)
    included.resize(count, 0)
    for index in range(count):
        if len(vectors[index]) != dimensions:
            raise ValueError("Mismatched native retention dimensions")
        for dimension in range(dimensions):
            value = vectors[index][dimension]
            if not isfinite(value):
                raise ValueError("Non-finite native retention value")
            values[index * dimensions + dimension] = value
    # Stable identity order means maximum ties keep the first candidate, while
    # minimum ties keep the last: exactly Python's reverse-value sorted endpoints.
    for dimension in range(dimensions):
        maximum = minimum = 0
        for index in range(1, count):
            value = values[index * dimensions + dimension]
            if value > values[maximum * dimensions + dimension]:
                maximum = index
            if value <= values[minimum * dimensions + dimension]:
                minimum = index
        if not included[maximum]:
            included[maximum] = 1
            selected.push_back(maximum)
        if not included[minimum]:
            included[minimum] = 1
            selected.push_back(minimum)
        ranges[dimension] = values[maximum * dimensions + dimension] - values[minimum * dimensions + dimension]
    for index in range(count):
        for dimension in range(dimensions):
            values[index * dimensions + dimension] = values[index * dimensions + dimension] / ranges[dimension] if ranges[dimension] else 0.0
    target = min(count, max(limit, selected.size()))
    with nogil:
        for index in range(count):
            if included[index]:
                continue
            best_distance = retention_distance(values, dimensions, index, selected[0])
            for anchor in range(1, selected.size()):
                candidate_distance = retention_distance(values, dimensions, index, selected[anchor])
                if candidate_distance < best_distance:
                    best_distance = candidate_distance
            nearest[index] = best_distance
        while selected.size() < target:
            chosen = count
            best_distance = -1.0
            for index in range(count):
                if not included[index] and (chosen == count or nearest[index] > best_distance):
                    chosen = index
                    best_distance = nearest[index]
            selected.push_back(chosen)
            included[chosen] = 1
            for index in range(count):
                if included[index]:
                    continue
                candidate_distance = retention_distance(values, dimensions, index, chosen)
                if candidate_distance < nearest[index]:
                    nearest[index] = candidate_distance
    return [selected[index] for index in range(selected.size())]


cdef int required_defence_mask(int priority) noexcept nogil:
    cdef int melee, combination
    if priority == 20:
        return 31
    if priority == 21:
        return 24
    if 22 <= priority <= 26:
        return 1 << (priority - 22)
    if priority == 27:
        return 7
    if priority == 28:
        return 23
    if priority == 29:
        return 15
    # IDs 30-38 group each melee style with magic, ranged, then both.
    if 30 <= priority <= 38:
        melee = 1 << ((priority - 30) // 3)
        combination = (priority - 30) % 3
        if combination == 0:
            return melee | 16
        if combination == 1:
            return melee | 8
        return melee | 24
    return 0


cdef double accuracy_for(long long attack, long long defence) noexcept nogil:
    if attack < 0:
        attack = 0
    if defence < 0:
        defence = 0
    if attack > defence:
        return 1.0 - (defence + 2) / <double>(2 * (attack + 1))
    return attack / <double>(2 * (defence + 1))


cdef double armoured_mean(long long maximum, long long armour, long long hit_floor=1) noexcept nogil:
    cdef long long first = max(hit_floor, armour + 1)
    cdef long long count = max(0, maximum - first + 1)
    cdef double positive_sum = count * (first + maximum - 2 * armour) / 2.0
    return (min(hit_floor, maximum + 1) * max(0, hit_floor - armour) + positive_sum) / (maximum + 1)


cdef double status_damage(double chance, int speed, int duration, int kind,
                          int severity=26, bint exact=False) noexcept nogil:
    cdef double states[27]
    cdef double total = 0.0, unchanged, applied
    cdef int phase, tick, state, attacks, count
    if chance <= 0 or kind == 0:
        return 0.0
    for phase in range(1, 31):
        memset(states, 0, sizeof(states))
        states[0] = 1.0
        attacks = 0
        tick = phase
        while tick <= duration * 5 // 3:
            count = tick // speed + 1
            unchanged = pow(1 - chance, count - attacks)
            attacks = count
            if kind == 1:
                applied = states[0] * (1 - unchanged)
                states[0] *= unchanged
                states[1] += applied
                if not exact:
                    for state in range(1, 9):
                        total += states[state] * (4 + 2 * state)
                else:
                    total += status_tick_total(states, 8, True)
                for state in range(8, 1, -1):
                    if state == 8:
                        states[state] += states[state - 1]
                    else:
                        states[state] = states[state - 1]
                states[1] = 0
            else:
                for state in range(severity + 1):
                    states[state] *= unchanged
                states[severity] += 1 - unchanged
                if not exact:
                    for state in range(1, severity + 1):
                        total += states[state] * ((state + 4) // 5)
                else:
                    total += status_tick_total(states, severity, False)
                states[0] += states[1]
                for state in range(1, severity):
                    states[state] = states[state + 1]
                states[severity] = 0
            tick += 30
    return total / 30


cdef double status_tick_total(double* states, int maximum, bint venom) noexcept nogil:
    # Match sum(weighted_state_damage) for one timer tick in the Python reference.
    cdef double high = 0, low = 0, term, updated
    cdef int state
    for state in range(1, maximum + 1):
        term = states[state] * (4 + 2 * state if venom else (state + 4) // 5)
        updated = high + term
        if high >= term:
            low += (high - updated) + term
        else:
            low += (term - updated) + high
        high = updated
    return high + low


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
        self.amulet_mask = packed["amulet_mask"]
        self.amulet_bonus = packed["amulet_bonus"]
        self.tome_element = packed["tome_element"]
        self.bolt_family = packed["bolt_family"]
        self.reviewed_crossbow = packed["reviewed_crossbow"]
        self.zaryte = packed["zaryte"]
        self.hopper_shield = packed["hopper_shield"]
        self.spell_element = packed["spell_element"]
        self.searing = packed["searing"]
        self.ranged_level = packed["ranged_level"]
        self.diary = packed["diary"]
        self.target_hp = packed["target_hp"]
        self.target_traits = packed["target_traits"]
        self.slayer_bonus = packed["slayer_bonus"]
        self.salve_bonus = packed["salve_bonus"]
        self.slayer_staff = packed["slayer_staff"]
        self.on_slayer_task = packed["on_slayer_task"]
        self.wilderness_weapon = packed["wilderness_weapon"]
        self.magic_dart = packed["magic_dart"]
        self.magic_level = packed["magic_level"]
        self.leafy_weapon = packed["leafy_weapon"]
        self.broad_ammo = packed["broad_ammo"]
        self.seeking_ammo = packed["seeking_ammo"]
        self.target_leafy = packed["target_leafy"]
        self.vampyre_rule_offset = packed["vampyre_rule_offset"]
        self.vampyre_rules = packed["vampyre_rules"]
        self.silver_bolts = packed["silver_bolts"]
        self.silver_poison = packed["silver_poison"]
        self.target_poisonable = packed["target_poisonable"]
        self.efaritay = packed["efaritay"]
        self.elite_void_piece = packed["elite_void_piece"]
        self.size_damage_per_size = packed["size_damage_per_size"]
        self.size_damage_max_size = packed["size_damage_max_size"]
        self.target_size = packed["target_size"]
        self.status_kind = packed["status_kind"]
        self.status_duration = packed["status_duration"]
        self.halberd = packed["halberd"]
        self.serpentine = packed["serpentine"]
        self.dragonbane_accuracy = packed["dragonbane_accuracy"]
        self.dragonbane_damage = packed["dragonbane_damage"]
        self.demonbane_weapon = packed["demonbane_weapon"]
        self.holy_water = packed["holy_water"]
        self.purging_staff = packed["purging_staff"]
        self.scorching_bow = packed["scorching_bow"]
        self.target_demon = packed["target_demon"]
        self.demonbane_vulnerability = packed["demonbane_vulnerability"]
        self.demonbane_spell = packed["demonbane_spell"]
        self.mark_of_darkness = packed["mark_of_darkness"]
        self.priority = packed["priority"]
        self.objective_ids = packed["objective_ids"]
        self.objective_kinds = packed["objective_kinds"]
        self.objective_masks = packed["objective_masks"]
        self.objective_means = packed["objective_means"]

        if "gp_per_damage" in self.objective_ids:
            from tracker.gear.native.cost_context import pack_costs
            costs = pack_costs(search, self)
            self.serp_head = costs.serp_head
            self.serp_cost = costs.serp_cost
            self.option_kind = costs.option_kind
            self.option_cost = costs.option_cost
            self.option_on_hit_cost = costs.option_on_hit_cost
            self.option_per_second_cost = costs.option_per_second_cost
            self.supply_class = costs.supply_class
            self.supply_count = costs.supply_count
            self.ranged_kind = costs.ranged_kind
            self.ammo_valid = costs.ammo_valid
            self.body_recovery = costs.body_recovery
            self.unpriced_repair = costs.unpriced_repair
            self.unit_prices = costs.unit_prices
            self.recovery = costs.recovery

    cdef double attack_cost(self, const int* slots, Score* score) noexcept:
        cdef int option = score.option_index
        cdef int cost_index
        cdef int weapon = slots[0], ammo = slots[2], cape = slots[4], shield = slots[1], slot, source
        cdef double rate, head_cost = 0.0, quantity = 1.0, ring_cost = 0.0
        if not score.supported or option < 0:
            return -1
        if score.ring_charge_probability >= 0:
            if self.unit_prices[slots[10]] < 0:
                return -1
            ring_cost = score.ring_charge_probability * (self.unit_prices[slots[10]] * 0.005)
        if self.serp_head[slots[3]]:
            if self.serp_cost[option] < 0:
                return -1
            head_cost = self.serp_cost[option]
        for slot in range(11):
            if self.unpriced_repair[slots[slot]]:
                return -1
        if not self.option_kind[option]:
            cost_index = option * self.supply_count + self.supply_class[shield]
            if self.option_cost[cost_index] < 0 or self.option_on_hit_cost[cost_index] < 0 or self.option_per_second_cost[cost_index] < 0:
                return -1
            return (self.option_cost[cost_index] + head_cost) + score.accuracy * self.option_on_hit_cost[cost_index] + self.option_per_second_cost[cost_index] * score.interval + ring_cost
        if self.ranged_kind[weapon] == 3:
            return self.unit_prices[weapon] + head_cost + ring_cost if self.unit_prices[weapon] >= 0 else -1
        if self.ranged_kind[weapon] == 1:
            if not ammo or not self.ammo_valid[ammo]:
                return -1
            source = ammo
        elif self.ranged_kind[weapon] == 2:
            source = weapon
        else:
            return -1
        rate = self.recovery[cape]
        if rate < 0:
            return -1
        if rate > 0:
            if self.body_recovery[slots[6]] == 2:
                rate = 0
            elif self.body_recovery[slots[6]] == 3:
                # This affects only the cost objective. DPS remains supported.
                return -1
        if self.unit_prices[source] < 0:
            return -1
        if self.ranged_kind[weapon] == 1 and self.reviewed_crossbow[weapon] and self.hopper_shield[shield] and ammo:
            # evaluate() already checked physical ammunition compatibility.
            quantity = 1.11
        return (quantity - quantity * rate) * self.unit_prices[source] + head_cost + ring_cost

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
            if self.priority == 27:
                return min(rolls[0], rolls[1], rolls[2])
            if self.priority == 28:
                return min(rolls[0], rolls[1], rolls[2], rolls[4])
            if self.priority == 29:
                return min(rolls[0], rolls[1], rolls[2], rolls[3])
            if 30 <= self.priority <= 38:
                index = (self.priority - 30) // 3
                if (self.priority - 30) % 3 == 0:
                    return min(rolls[index], rolls[4])
                if (self.priority - 30) % 3 == 1:
                    return min(rolls[index], rolls[3])
                return min(rolls[index], rolls[4], rolls[3])
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

    cdef void prepare_gear(self, const int* slots, const int* order,
                           PreparedGear* gear) noexcept nogil:
        cdef int slot, item, field, position, index
        cdef int weapon = slots[0], ammo = slots[2]
        cdef double* bonuses = gear.bonuses
        cdef double term, hi=0.0, lo=0.0, total
        cdef bint legal = True, ammo_ok = False
        memset(bonuses, 0, sizeof(gear.bonuses))
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
        gear.legal = legal and not (weapon and self.two_handed[weapon] and slots[1])
        if self.ammo_required[weapon]:
            if ammo:
                for index in range(self.ammo_offsets[weapon], self.ammo_offsets[weapon + 1]):
                    if self.ammo_codes[index] == self.ammo_types[ammo]:
                        ammo_ok = True
                        break
        else:
            ammo_ok = True
        gear.ammo_ok = ammo_ok
        gear.elite_void_ranged = (self.elite_void_piece[slots[3]] and self.elite_void_piece[slots[6]]
                                  and self.elite_void_piece[slots[7]] and self.elite_void_piece[slots[8]])

    cdef void evaluate(self, const int* slots, int role_index, bint metric, Score* output,
                       const int* order=NULL, int specific_option=-1,
                       const unsigned char* allowed=NULL,
                       PreparedGear* prepared=NULL) noexcept nogil:
        cdef PreparedGear local
        cdef int weapon = slots[0], ammo = slots[2], field
        cdef int start, length, index, base, style, pattern, best_tie = -1, tie
        cdef bint ranged, tome, hopper, wilderness_weapon
        cdef bint strength_ranged, ranged_task_damage
        cdef int element, family, task_bonus, hit_floor, demon_accuracy, demon_damage, vulnerability
        cdef int salve, salve_num, salve_den, salve_magic
        cdef int dragon_accuracy, dragon_damage
        cdef bint demon_spell, holy
        cdef BoltResult proc, extra
        cdef long long spell_base, minimum, weakness_roll
        cdef double secondary_accuracy
        cdef double status_proc, positive
        cdef long long maximum, attack, defence, strength, armor, cap, first, second
        cdef long long effective_attack, effective_strength
        cdef double accuracy, dps, expected, secondary, second_probability, magic_bonus, term
        cdef double* bonuses
        cdef const int* vampyre
        cdef int rule_offset
        cdef long long roll, marked_total, marked_hit
        cdef double miss, bypass, ring_chance
        if prepared == NULL:
            self.prepare_gear(slots, order, &local)
            prepared = &local
        bonuses = prepared.bonuses
        memset(output, 0, sizeof(Score))
        output.option_index = -1
        output.ring_charge_probability = -1
        for field in range(14):
            output.bonuses[field] = bonuses[field]
        if self.fixed_roles[role_index]:
            if self.role_styles[role_index] == 3 and ammo and not self.ammo_required[weapon]:
                output.bonuses[3] -= self.item_bonuses[ammo * 14 + 3]
                output.bonuses[6] -= self.item_bonuses[ammo * 14 + 6]
            output.secondary = self.secondary_for(output.bonuses, 0.0, -1)
        if not prepared.legal:
            return
        base = ((<int>metric * self.role_count + role_index) * self.item_count + weapon)
        start, length = self.offsets[base], self.lengths[base]
        if specific_option >= 0:
            start, length = specific_option, 1
        for index in range(start, start + length):
            if allowed != NULL and not allowed[index - start]:
                continue
            base = index * 18
            if not self.options[base + 9]:
                continue
            style = <int>self.options[base]
            ranged = style == 3
            strength_ranged = ranged and self.original_ids[weapon] == 29305
            task_bonus = self.slayer_bonus[slots[3]] if self.on_slayer_task[index] else 0
            salve = self.salve_bonus[slots[5]] if self.target_traits[index] & 4 else 0
            if salve == 2 or salve == 4:
                salve_num, salve_den = 6, 5
            else:
                salve_num, salve_den = 7, 6
            salve_magic = (15 if salve == 3 else 20 if salve == 4 else 0) if style == 4 else 0
            ranged_task_damage = ranged and not strength_ranged and task_bonus == 2 and salve < 3
            wilderness_weapon = self.wilderness_weapon[index] != 0
            if self.serpentine[slots[3]] and (not self.halberd[weapon] or style >= 3):
                continue
            if ranged and not prepared.ammo_ok:
                continue
            rule_offset = self.vampyre_rule_offset[index]
            vampyre = NULL
            if rule_offset >= 0:
                if ranged and self.ammo_required[weapon] and self.silver_bolts[ammo]:
                    rule_offset += 2 * V_WIDTH
                if self.efaritay[slots[10]]:
                    rule_offset += V_WIDTH
                vampyre = &self.vampyre_rules[rule_offset]
                if not vampyre[V_LEGAL]:
                    continue
            if self.target_leafy[index]:
                if style < 3 and not self.leafy_weapon[weapon]:
                    continue
                if ranged and not (self.ammo_required[weapon] and prepared.ammo_ok and self.broad_ammo[ammo]):
                    continue
                if style == 4 and not self.magic_dart[index]:
                    continue
            demon_spell = style == 4 and self.demonbane_spell[index] and self.target_demon[index]
            holy = ranged and self.holy_water[weapon]
            vulnerability = self.demonbane_vulnerability[index]
            dragon_accuracy = self.dragonbane_accuracy[weapon] if self.target_traits[index] & 2 else 0
            dragon_damage = self.dragonbane_damage[weapon] if self.target_traits[index] & 2 else 0
            demon_accuracy = 0
            demon_damage = 0
            if self.target_demon[index]:
                if demon_spell:
                    demon_accuracy = (40 if self.mark_of_darkness[index] else 20) * (2 if self.purging_staff[weapon] else 1)
                    demon_damage = (50 if self.purging_staff[weapon] else 25) if self.mark_of_darkness[index] else 0
                elif style < 4:
                    demon_accuracy = 0 if holy else self.demonbane_weapon[weapon]
                    demon_damage = self.demonbane_weapon[weapon]
            hit_floor = 3 if ranged and self.ammo_required[weapon] and self.seeking_ammo[ammo] else 1
            strength = <long long>bonuses[6 if ranged and not strength_ranged else 5]
            attack = <long long>bonuses[style]
            if ranged and ammo and not self.ammo_required[weapon]:
                if not strength_ranged:
                    strength -= self.item_bonuses[ammo * 14 + 6]
                attack -= self.item_bonuses[ammo * 14 + 3]
            minimum = 0
            effective_attack, effective_strength = self.options[base + 1], self.options[base + 2]
            if ranged and prepared.elite_void_ranged:
                effective_attack = floor_div(effective_attack * 11, 10)
                effective_strength = floor_div(effective_strength * 9, 8)
            element = self.spell_element[index]
            tome = element != 0 and self.tome_element[slots[1]] == element
            if style == 4:
                magic_bonus = min(100.0, bonuses[7] * 3) if self.options[base + 12] else bonuses[7]
                spell_base = self.options[base + 10]
                if self.magic_dart[index]:
                    spell_base = 13 + self.magic_level[index] // 6 if self.on_slayer_task[index] and self.slayer_staff[weapon] else 10 + self.magic_level[index] // 10
                if element and self.amulet_mask[slots[5]] & (1 << element):
                    spell_base += self.amulet_bonus[slots[5]]
                maximum = <long long>floor(spell_base * (100 + magic_bonus + self.options[base + 11] + salve_magic) / 100.0)
                if task_bonus == 2 and not salve_magic:
                    maximum = floor_div(maximum * 23, 20)
                if dragon_damage:
                    maximum = floor_div(maximum * (100 + dragon_damage), 100)
                if wilderness_weapon:
                    maximum = floor_div(maximum * 3, 2)
                maximum += floor_div(spell_base * self.options[base + 13], 100)
                if self.options[base + 12]:
                    attack *= 3
            else:
                maximum = <long long>floor(0.5 + effective_strength * (strength + 64) / 640.0)
            if holy:
                maximum = <long long>floor(0.5 + (self.ranged_level[index] + 10) * (self.item_bonuses[weapon * 14 + 6] + 64) / 640.0)
            attack = effective_attack * (attack + 64)
            if style == 4:
                weakness_roll = floor_div(attack * self.options[base + 13], 100)
                if salve_magic:
                    attack = floor_div(attack * (100 + salve_magic), 100)
                if dragon_accuracy:
                    attack = floor_div(attack * (100 + dragon_accuracy), 100)
                if task_bonus == 2 and not salve_magic:
                    attack = floor_div(attack * 23, 20)
                if wilderness_weapon:
                    attack = floor_div(attack * 3, 2)
                if tome and element == 2:
                    attack = floor_div(attack * 120, 100)
                attack += weakness_roll
                if tome:
                    if element == 4 and self.searing[index]:
                        minimum = floor_div(maximum, 10)
                    maximum = floor_div(maximum * 110, 100)
            elif not ranged:
                if salve:
                    maximum = floor_div(maximum * salve_num, salve_den)
                    attack = floor_div(attack * salve_num, salve_den)
                elif task_bonus:
                    maximum = floor_div(maximum * 7, 6)
                    attack = floor_div(attack * 7, 6)
            else:
                if salve >= 3:
                    attack = floor_div(attack * salve_num, salve_den)
                elif task_bonus == 2:
                    attack = floor_div(attack * 23, 20)
                if not holy:
                    if salve >= 3 or (salve and strength_ranged):
                        maximum = floor_div(maximum * salve_num, salve_den)
                    elif strength_ranged and task_bonus:
                        maximum = floor_div(maximum * 7, 6)
                    elif ranged_task_damage:
                        if wilderness_weapon:
                            maximum = floor_div(maximum * 33, 20)
                        elif dragon_damage == 25:
                            maximum = floor_div(maximum * 140, 100)
                        elif self.scorching_bow[weapon] and self.target_demon[index]:
                            maximum = floor_div(maximum * (115 + floor_div(demon_damage * vulnerability, 100)), 100)
                        else:
                            maximum = floor_div(maximum * 23, 20)
            if style != 4 and wilderness_weapon:
                attack = floor_div(attack * 3, 2)
                if not ranged_task_damage:
                    maximum = floor_div(maximum * 3, 2)
            if style != 4 and dragon_accuracy:
                attack = floor_div(attack * (100 + dragon_accuracy), 100)
            if style != 4 and dragon_damage and not ranged_task_damage:
                maximum = floor_div(maximum * (100 + dragon_damage), 100)
            if demon_accuracy:
                attack += floor_div(attack * floor_div(demon_accuracy * vulnerability, 100), 100)
            if vampyre != NULL:
                attack = floor_div(attack * (100 + vampyre[V_WEAPON_ACCURACY]), 100)
                attack = floor_div(attack * (100 + vampyre[V_RING_ACCURACY]), 100)
            if demon_damage and not demon_spell and not (self.scorching_bow[weapon] and ranged_task_damage):
                maximum += floor_div(maximum * floor_div(demon_damage * vulnerability, 100), 100)
            if style < 3 and self.target_leafy[index] and self.leafy_weapon[weapon] == 2:
                maximum = floor_div(maximum * 47, 40)
            if style < 3:
                maximum += self.size_damage_per_size[weapon] * min(self.target_size[index], self.size_damage_max_size[weapon])
            if maximum < 0:
                maximum = 0
            defence = self.options[base + 3]
            pattern, armor, cap = <int>self.options[base + 5], self.options[base + 6], self.options[base + 7]
            if pattern == 0:
                first, second = maximum, 0
            else:
                first = maximum // 2
                second = maximum - first
            if cap >= 0:
                if vampyre != NULL:
                    marked_hit = first
                    if demon_spell and self.mark_of_darkness[index]:
                        marked_hit += floor_div(floor_div(first * demon_damage, 100) * vulnerability, 100)
                    if self.options[base + 15]:
                        marked_hit = max(1, marked_hit) + 8
                    if vampyre_hit(marked_hit, vampyre, armor, hit_floor) > cap or (pattern != 0 and vampyre_hit(second, vampyre, armor, hit_floor) > cap):
                        continue
                elif demon_spell and self.mark_of_darkness[index]:
                    if max(hit_floor, first) + floor_div(floor_div(max(hit_floor, first) * demon_damage, 100) * vulnerability, 100) > cap:
                        continue
                elif max(hit_floor, first) + 8 * self.options[base + 15] > cap or (pattern != 0 and max(hit_floor, second) > cap):
                    continue
            accuracy = accuracy_for(attack, defence)
            expected = 0.0 + accuracy * armoured_mean(first, armor, hit_floor)
            if pattern != 0:
                second_probability = pow(accuracy, 2.0) if pattern == 2 else accuracy
                expected += second_probability * armoured_mean(second, armor, hit_floor)
            if demon_spell and self.mark_of_darkness[index]:
                expected = accuracy * marked_damage_total(maximum, demon_damage, vulnerability) / (maximum + 1)
            if minimum > 0:
                expected = accuracy * (minimum + maximum) / 2
            if self.options[base + 15]:
                expected += accuracy * 0.2 * 8
            if vampyre != NULL:
                expected = accuracy * vampyre_mean(first, vampyre, armor, hit_floor, 0, 1, minimum)
                if pattern != 0:
                    expected += second_probability * vampyre_mean(second, vampyre, armor, hit_floor)
                if demon_spell and self.mark_of_darkness[index]:
                    marked_total = 0
                    for roll in range(maximum + 1):
                        marked_hit = roll + floor_div(floor_div(roll * demon_damage, 100) * vulnerability, 100)
                        marked_total += vampyre_hit(marked_hit, vampyre, armor, hit_floor)
                    expected = accuracy * (<double>marked_total / (maximum + 1))
                if self.options[base + 15]:
                    expected = accuracy * (0.8 * vampyre_mean(first, vampyre, armor, hit_floor, 0, 1, minimum) + 0.2 * vampyre_mean(first, vampyre, armor, 1, 0, 1, 0, True))
            family = self.bolt_family[ammo] if ranged and self.ammo_required[weapon] else 0
            proc.activation = 0
            if family:
                if family == 3 and self.target_hp[index] < 0:
                    continue
                proc = bolt_damage(family, self.ranged_level[index], maximum, accuracy,
                    self.target_hp[index], self.diary[index], self.zaryte[weapon],
                    self.target_traits[index], armor, 1, 1.0, vampyre)
                if cap >= 0 and proc.maximum > cap:
                    continue
                expected = proc.expected
            hopper = ranged and self.ammo_required[weapon] and self.reviewed_crossbow[weapon] and self.hopper_shield[slots[1]] and prepared.ammo_ok and ammo != 0
            if hopper:
                secondary_accuracy = accuracy_for(floor_div(attack * 2, 3), defence)
                if family:
                    extra = bolt_damage(family, self.ranged_level[index], maximum, secondary_accuracy,
                        self.target_hp[index], self.diary[index], self.zaryte[weapon],
                        self.target_traits[index], armor, 3, (1 - proc.activation) / 3, vampyre)
                    expected += 0.11 * extra.expected
                else:
                    expected += 0.11 * (secondary_accuracy * damage_mean(maximum, armor, 0, 3, vampyre))
            dps = expected / (self.options[base + 4] * 0.6)
            status_proc = (0.5 if self.serpentine[slots[3]] else 1.0 / 3) if self.original_ids[weapon] == 29796 else (1.0 / 6 if self.halberd[weapon] and self.serpentine[slots[3]] else 0.0)
            if style < 3 and status_proc and self.status_kind[index]:
                positive = positive_chance(maximum, vampyre, armor)
                dps += status_damage(status_proc * accuracy * positive, <int>self.options[base + 4], self.status_duration[index], self.status_kind[index], 26, vampyre != NULL) / self.status_duration[index]
            elif ranged and self.ammo_required[weapon] and self.silver_poison[ammo] and self.target_poisonable[index]:
                status_proc = 0.125 * accuracy * positive_chance(maximum, vampyre, armor)
                if hopper:
                    positive = 0.11 * 0.125 * secondary_accuracy * positive_chance(maximum, vampyre, armor, 3)
                    status_proc = 1 - (1 - status_proc) * (1 - positive)
                dps += status_damage(status_proc, <int>self.options[base + 4], self.status_duration[index], 2, self.silver_poison[ammo], True) / self.status_duration[index]
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
            ring_chance = -1
            if vampyre != NULL and self.efaritay[slots[10]]:
                bypass = proc.activation if family in (1, 2, 3, 4) else 0.0
                miss = (1 - accuracy) * (1 - bypass)
                if pattern == 1:
                    miss *= 1 - accuracy
                if hopper:
                    miss *= 1 - 0.11 * (secondary_accuracy + (1 - secondary_accuracy) * bypass / 3)
                ring_chance = 1 - miss
            output.ring_charge_probability = ring_chance
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

    cdef void build_option_mask(self, const int* slots, int role_index, int start, int length,
                                object option_allowed, object equipment,
                                int settled_slot, vector[unsigned char]& mask) except *:
        cdef int index, slot, base
        if option_allowed is None or self.role_styles[role_index] != 4 or not length:
            return
        if equipment is None:
            equipment = {SLOT_NAMES[slot]: self.original_ids[slots[slot]]
                         for slot in range(settled_slot + 1) if slots[slot]}
        mask.resize(length, 1)
        for index in range(start, start + length):
            base = index * 18
            if self.options[base] == 4 and self.options[base + 9]:
                configured, option = self.option_records[index]
                mask[index - start] = bool(option_allowed(equipment, configured, option))

    cdef void evaluate_filtered(self, const int* slots, int role_index, bint metric, Score* output,
                                const int* order, object option_allowed, object equipment=None,
                                int settled_slot=10) except *:
        cdef int offset = ((<int>metric * self.role_count + role_index) * self.item_count + slots[0])
        cdef vector[unsigned char] mask
        self.build_option_mask(slots, role_index, self.offsets[offset], self.lengths[offset],
                               option_allowed, equipment, settled_slot, mask)
        self.evaluate(slots, role_index, metric, output, order, -1, &mask[0] if mask.size() else NULL)

    cdef void project_objectives(self, const int* slots, Score* result, double* values) except *:
        cdef int index, style, count, mask, kind
        cdef double value, roll
        for index in range(self.objective_kinds.shape[0]):
            kind = self.objective_kinds[index]
            if kind == 0:
                mask = self.objective_masks[index]
                value, count = 0.0, 0
                for style in range(5):
                    if not mask & (1 << style):
                        continue
                    roll = result.defence_rolls[style]
                    if roll < 0:
                        raise ValueError("Player defensive roll is unavailable: required combat levels are unknown")
                    value = value + roll if self.objective_means[index] else min(value, roll) if count else roll
                    count += 1
                if count == 0:
                    raise ValueError("Empty native defence group")
                values[index] = value / count if self.objective_means[index] else value
            elif kind == 1:
                values[index] = result.bonuses[13]
            elif kind == 2:
                values[index] = result.bonuses[5]
            elif kind == 3:
                values[index] = result.bonuses[6]
            elif kind == 4:
                values[index] = result.bonuses[7]
            elif kind == 5:
                values[index] = result.accuracy
            elif kind == 7 or kind == 8:
                # Whole-kit objectives are filled after combining the physical loadouts.
                values[index] = 0.0
            else:
                value = self.attack_cost(slots, result)
                values[index] = -(value / result.interval) / result.dps if value >= 0 and result.interval > 0 and result.dps > 0 else -1e100

    cdef bint project_slots(self, const int* slots, int role_index, const int* order, double* maximum,
                            object option_allowed=None, object equipment=None, int settled_slot=10,
                            const unsigned char* prepared_mask=NULL) except -1:
        cdef Score result
        cdef double values[64]
        cdef int index, dimension
        cdef int offset = role_index * self.item_count + slots[0]
        cdef int start = self.offsets[offset], length = self.lengths[offset]
        cdef bint supported = False
        cdef vector[unsigned char] mask
        cdef PreparedGear gear
        self.prepare_gear(slots, order, &gear)
        if prepared_mask == NULL:
            self.build_option_mask(slots, role_index, start, length, option_allowed, equipment, settled_slot, mask)
            if mask.size():
                prepared_mask = &mask[0]
        for index in range(start, start + length):
            if prepared_mask != NULL and not prepared_mask[index - start]:
                continue
            self.evaluate(slots, role_index, False, &result, order, index, NULL, &gear)
            if not result.supported:
                continue
            self.project_objectives(slots, &result, values)
            if not supported or result.dps > maximum[0]:
                maximum[0] = result.dps
            for dimension in range(self.objective_kinds.shape[0]):
                if not supported or values[dimension] > maximum[dimension + 1]:
                    maximum[dimension + 1] = values[dimension]
            supported = True
        return supported

    def score_projection(self, equipment, int role_index, *, option_allowed=None,
                         const unsigned char[::1] option_mask=None):
        """Return component maxima for a partial beam, without public option records.

        This is a heuristic envelope, never a complete configuration's vector.
        Concrete archives must still use score_variants and full feasibility.
        """
        cdef int slots[11]
        cdef int order[11]
        cdef double maximum[65]
        cdef int position = 0, offset, dimension
        cdef const unsigned char* packed_mask = NULL
        cdef bint supported = False
        if role_index < 0 or role_index >= self.role_count:
            raise ValueError("Invalid native role index")
        memset(slots, 0, sizeof(slots))
        memset(order, -1, sizeof(order))
        for slot, item in equipment.items():
            if slot not in SLOT_NAMES or type(item) is not int or item not in self.dense_index or item == 0:
                raise ValueError("Invalid native equipment")
            slots[SLOT_NAMES.index(slot)] = self.dense_index[item]
            order[position] = SLOT_NAMES.index(slot)
            position += 1
        if option_mask is not None:
            offset = role_index * self.item_count + slots[0]
            if option_mask.shape[0] != self.lengths[offset]:
                raise ValueError("Invalid native option mask length")
            if option_mask.shape[0]:
                packed_mask = &option_mask[0]
        supported = self.project_slots(
            slots, role_index, order, maximum, option_allowed, equipment, 10, packed_mask
        )
        return tuple(maximum[dimension] for dimension in range(self.objective_kinds.shape[0] + 1)) if supported else None

    def score_variants(self, equipment, int role_index, *, option_allowed=None,
                       const unsigned char[::1] option_mask=None, bint compact=False,
                       bint include_charge_probability=False):
        """Score every concrete configured option, without projection-based pruning."""
        cdef int slots[11]
        cdef int order[11]
        cdef Score result
        cdef PreparedGear gear
        cdef double values[64]
        cdef int index, position = 0, start, length, offset
        cdef vector[unsigned char] mask
        cdef const unsigned char* packed_mask = NULL
        if role_index < 0 or role_index >= self.role_count:
            raise ValueError("Invalid native role index")
        memset(slots, 0, sizeof(slots))
        memset(order, -1, sizeof(order))
        for slot, item in equipment.items():
            if slot not in SLOT_NAMES or type(item) is not int or item not in self.dense_index or item == 0:
                raise ValueError("Invalid native equipment")
            slots[SLOT_NAMES.index(slot)] = self.dense_index[item]
            order[position] = SLOT_NAMES.index(slot)
            position += 1
        offset = role_index * self.item_count + slots[0]
        start, length = self.offsets[offset], self.lengths[offset]
        if option_mask is not None:
            if option_mask.shape[0] != length:
                raise ValueError("Invalid native option mask length")
            if length:
                packed_mask = &option_mask[0]
        else:
            self.build_option_mask(slots, role_index, start, length, option_allowed, equipment, 10, mask)
            if mask.size():
                packed_mask = &mask[0]
        self.prepare_gear(slots, order, &gear)
        rows = []
        for index in range(start, start + length):
            if packed_mask != NULL and not packed_mask[index - start]:
                continue
            self.evaluate(slots, role_index, False, &result, order, index, NULL, &gear)
            if not result.supported:
                continue
            self.project_objectives(slots, &result, values)
            if compact:
                row = (result.option_index, (result.dps, *(
                    (None if values[position] == -1e100 else -values[position])
                    if self.objective_kinds[position] == 6 else values[position]
                    for position in range(self.objective_kinds.shape[0])
                )), result.accuracy, result.interval)
                if include_charge_probability:
                    row += (result.ring_charge_probability if result.ring_charge_probability >= 0 else None,)
                rows.append(row)
                continue
            rows.append({
                "supported": True,
                "dps": result.dps,
                "accuracy": result.accuracy,
                "ring_charge_probability": result.ring_charge_probability if result.ring_charge_probability >= 0 else None,
                "secondary": result.secondary,
                "interval": result.interval,
                "player_defence_rolls": {name: result.defence_rolls[position] if result.defence_rolls[position] >= 0 else None for position, name in enumerate(("stab", "slash", "crush", "ranged", "magic"))},
                "option_index": result.option_index,
                "bonuses": tuple(result.bonuses[position] for position in range(14)),
                "objective_values": {
                    name: ((None if values[position] == -1e100 else -values[position])
                           if self.objective_kinds[position] == 6 else values[position])
                    for position, name in enumerate(self.objective_ids)
                },
            })
        return rows

    def score(self, equipment, int role_index, bint metric=False, *, option_allowed=None,
              const unsigned char[::1] option_mask=None):
        cdef int slots[11]
        cdef int order[11]
        cdef Score result
        cdef int index
        cdef int needed, offset
        cdef const unsigned char* packed_mask = NULL
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
        if option_mask is not None:
            offset = ((<int>metric * self.role_count + role_index) * self.item_count + slots[0])
            if option_mask.shape[0] != self.lengths[offset]:
                raise ValueError("Invalid native option mask length")
            if option_mask.shape[0]:
                packed_mask = &option_mask[0]
            self.evaluate(slots, role_index, metric, &result, order, -1, packed_mask)
        elif option_allowed is None or self.role_styles[role_index] != 4:
            self.evaluate(slots, role_index, metric, &result, order)
        else:
            self.evaluate_filtered(slots, role_index, metric, &result, order, option_allowed, equipment)
        if result.supported and self.priority >= 20:
            needed = required_defence_mask(self.priority)
            for index in range(5):
                if needed & (1 << index) and result.defence_rolls[index] < 0:
                    raise ValueError("Player defensive roll is unavailable: required combat levels are unknown")
        return {
            "supported": bool(result.supported),
            "dps": result.dps if result.supported else None,
            "accuracy": result.accuracy if result.supported else None,
            "ring_charge_probability": result.ring_charge_probability if result.ring_charge_probability >= 0 else None,
            "secondary": result.secondary,
            "interval": result.interval if result.supported else None,
            "player_defence_rolls": {name: result.defence_rolls[index] if result.defence_rolls[index] >= 0 else None for index, name in enumerate(("stab", "slash", "crush", "ranged", "magic"))},
            "option_index": result.option_index,
            "bonuses": tuple(result.bonuses[index] for index in range(14)),
        }
