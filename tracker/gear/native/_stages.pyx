# cython: language_level=3, boundscheck=False, wraparound=False
# distutils: language=c++
"""Native expansion, constraints and stable retention for ordinary gear beams."""

from libc.math cimport fabs, isfinite
from libc.string cimport memset, memcpy
from libcpp.vector cimport vector
from libcpp.string cimport string, to_string
from libcpp.algorithm cimport sort

from tracker.gear.native._scoring cimport ScoringContext, Score

from tracker.gear.compact_states import SLOT_NAMES
from tracker.gear.native.stage_context import pack_stage


cdef struct Candidate:
    int slots[44]
    int order[44]
    int order_count[4]
    int present
    double key[5]
    long long ids[22]
    int identity_count
    int kind
    long long sequence
    string identity


cdef struct Sum:
    double hi
    double lo


cdef void add(Sum* total, double value) noexcept nogil:
    cdef double t = total.hi + value
    if fabs(total.hi) >= fabs(value):
        total.lo += (total.hi - t) + value
    else:
        total.lo += (value - t) + total.hi
    total.hi = t


cdef double value(Sum* total) noexcept nogil:
    if total.lo and isfinite(total.lo):
        return total.hi + total.lo
    return total.hi


cdef bint less(const Candidate& a, const Candidate& b) noexcept nogil:
    cdef int index
    for index in range(5):
        if a.key[index] != b.key[index]:
            return a.key[index] < b.key[index]
    if a.kind == 0:
        # Lexical slot indices and numerical item IDs match tuple identity.
        for index in range(a.identity_count if a.identity_count < b.identity_count else b.identity_count):
            if a.ids[index] != b.ids[index]:
                return a.ids[index] < b.ids[index]
            if a.ids[index + 11] != b.ids[index + 11]:
                return a.ids[index + 11] < b.ids[index + 11]
        if a.identity_count != b.identity_count:
            return a.identity_count < b.identity_count
    elif a.identity != b.identity:
        return a.identity < b.identity
    return a.sequence < b.sequence


cdef bint secondary_less(const Candidate& a, const Candidate& b) noexcept nogil:
    if a.key[1] != b.key[1]:
        return a.key[1] < b.key[1]
    return less(a, b)


cdef bint same(const Candidate& a, const Candidate& b) noexcept nogil:
    cdef int index
    if a.present != b.present:
        return False
    for index in range(44):
        if a.slots[index] != b.slots[index]:
            return False
    return True


cdef bint contains(vector[Candidate]& rows, const Candidate& row) noexcept nogil:
    cdef size_t index
    for index in range(rows.size()):
        if same(rows[index], row):
            return True
    return False


cdef class StageContext:
    cdef ScoringContext scoring
    cdef object data
    cdef long long[::1] markets, costs
    cdef int[::1] untradeable, edges, melee, scored
    cdef int[::1] option_kind, ranged_kind, ammo_valid, interference, torag
    cdef double[::1] option_cost, unit_prices, recovery
    cdef bint cost_objective
    cdef double[::1] weights, marginals
    cdef vector[string] role_names, slot_names
    cdef int role_order[4]
    cdef int slot_order[11]
    cdef long long budget
    cdef int capacity
    cdef bint acquisition_ties

    def __init__(self, ScoringContext scoring, search):
        cdef bytes encoded
        cdef int index
        self.scoring = scoring
        self.data = pack_stage(search, scoring)
        self.markets = self.data.markets
        self.costs = self.data.costs
        self.untradeable = self.data.untradeable
        self.edges = self.data.edges
        self.melee = self.data.melee
        self.scored = self.data.scored
        self.cost_objective = self.data.cost_data is not None
        if self.cost_objective:
            self.option_kind = self.data.cost_data.option_kind
            self.option_cost = self.data.cost_data.option_cost
            self.ranged_kind = self.data.cost_data.ranged_kind
            self.ammo_valid = self.data.cost_data.ammo_valid
            self.interference = self.data.cost_data.interference
            self.torag = self.data.cost_data.torag
            self.unit_prices = self.data.cost_data.unit_prices
            self.recovery = self.data.cost_data.recovery
        self.weights = self.data.weights
        self.marginals = self.data.marginals
        self.budget = self.data.budget
        self.capacity = self.data.capacity
        self.acquisition_ties = self.data.acquisition_ties
        for encoded in self.data.role_json:
            self.role_names.push_back(encoded)
        for encoded in self.data.slot_json:
            self.slot_names.push_back(encoded)
        for index, role in enumerate(sorted(range(scoring.role_count), key=lambda r: self.data.role_names[r])):
            self.role_order[index] = role
        for index, slot in enumerate(sorted(range(11), key=lambda s: SLOT_NAMES[s])):
            self.slot_order[index] = slot

    def begin(self, *, kind, states, choices, slot=None, roles=None, cap=None,
              frontier=False, metric=False, tuple_role=None):
        return Expansion(self, kind, states, choices, slot, roles, cap, frontier, metric, tuple_role)

    cdef void identity(self, Candidate* row) except *:
        cdef int r, s, order, j, n = 0
        cdef bint first_role = True
        cdef bint first_slot
        row.identity.clear()
        if row.kind == 0:
            # Encode lexical slot keys into a fixed-width integer preceding each ID.
            # Store one pair per present slot in the string-free numeric identity buffer.
            for order in range(11):
                s = self.slot_order[order]
                if row.slots[s]:
                    row.ids[n] = order
                    row.ids[n + 11] = self.scoring.original_ids[row.slots[s]]
                    n += 1
            row.identity_count = n
            return
        row.identity.push_back(123)
        for order in range(self.scoring.role_count):
            r = self.role_order[order]
            if not row.present & (1 << r):
                continue
            if not first_role:
                row.identity.append(<const char*>b", ")
            first_role = False
            row.identity.append(self.role_names[r])
            row.identity.append(<const char*>b": {")
            first_slot = True
            for j in range(11):
                s = self.slot_order[j]
                if not row.slots[r * 11 + s]:
                    continue
                if not first_slot:
                    row.identity.append(<const char*>b", ")
                first_slot = False
                row.identity.append(self.slot_names[s])
                row.identity.append(<const char*>b": ")
                row.identity.append(to_string(self.scoring.original_ids[row.slots[r * 11 + s]]))
            row.identity.push_back(125)
        row.identity.push_back(125)

    cdef int lower_bound(self, const int* old, const int* new) noexcept:
        cdef int result = 0
        cdef int s
        for s in range(11):
            result += old[s] != new[s]
        if new[0] and new[0] != old[0] and self.scoring.two_handed[new[0]]:
            result -= old[1] != 0 and new[1] == 0
        if new[1] and new[1] != old[1] and old[0] and self.scoring.two_handed[old[0]]:
            result -= old[0] != 0 and new[0] == 0
        return result

    cdef double attack_cost(self, const int* slots, Score* score) noexcept:
        cdef int option = score.option_index
        cdef int weapon = slots[0], ammo = slots[2], cape = slots[4], slot, source
        cdef double rate
        if not score.supported or option < 0:
            return -1
        for slot in range(11):
            if self.torag[slots[slot]]:
                return -1
        if not self.option_kind[option]:
            return self.option_cost[option]
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
        if self.interference[slots[6]]:
            rate = 0
        if self.unit_prices[source] < 0:
            return -1
        return (1 - rate) * self.unit_prices[source]

    cdef bint evaluate(self, Candidate* row, int* roles, int nroles, int slot,
                       int cap, bint metric) except -1:
        cdef int physical[44]
        cdef int count = 0
        cdef int index, item, previous, r, s, j, k, d, outside
        cdef int first_defence, last_defence
        cdef long long cost = 0
        cdef long long amount, market, untradeable = 0, strength = 0
        cdef bint duplicate, later, all_melee = True
        cdef bint costs_known = True, active_cost = False
        cdef double attack_cost, hourly
        cdef Score score
        cdef Sum primary = Sum(0.0, 0.0)
        cdef Sum secondary = Sum(0.0, 0.0)
        cdef Sum weight = Sum(0.0, 0.0)
        cdef Sum spend = Sum(0.0, 0.0)
        cdef Sum damage = Sum(0.0, 0.0)
        cdef int row_roles = 1 if row.kind == 0 else self.scoring.role_count
        for r in range(row_roles):
            if row.kind != 0 and not row.present & (1 << r):
                continue
            if row.slots[r * 11] and row.slots[r * 11 + 1] and self.scoring.two_handed[row.slots[r * 11]]:
                return False
            for s in range(11):
                item = row.slots[r * 11 + s]
                if not item:
                    continue
                if not self.scoring.eligible[item] or self.scoring.item_slots[item] != s:
                    return False
                duplicate = False
                for j in range(count):
                    if physical[j] == item:
                        duplicate = True
                        break
                if not duplicate:
                    physical[count] = item
                    count += 1
        # Sorted physical IDs ensure the historical highest-ID market-alias overwrite.
        for j in range(1, count):
            item = physical[j]
            k = j
            while k > 0 and self.scoring.original_ids[physical[k - 1]] > self.scoring.original_ids[item]:
                physical[k] = physical[k - 1]
                k -= 1
            physical[k] = item
        for j in range(count):
            item = physical[j]
            untradeable += self.untradeable[item]
            market = self.markets[item]
            if not market:
                continue
            later = False
            for k in range(j + 1, count):
                if self.markets[physical[k]] == market:
                    later = True
                    break
            if not later:
                cost += self.costs[item]
        if cost > self.budget:
            return False
        if row.kind == 1:
            for r in range(row_roles):
                outside = count
                for j in range(count):
                    for s in range(11):
                        if row.slots[r * 11 + s] == physical[j]:
                            outside -= 1
                            break
                if outside > self.capacity:
                    return False
        if row.kind != 0 and cap >= 0:
            for index in range(0, self.edges.shape[0], 2):
                r, d = self.edges[index], self.edges[index + 1]
                if row.present & (1 << r) and row.present & (1 << d):
                    if self.lower_bound(&row.slots[r * 11], &row.slots[d * 11]) > cap:
                        return False
        for index in range(nroles):
            r = roles[index]
            if row.kind != 0 and not row.present & (1 << r):
                continue
            all_melee = all_melee and self.melee[r]
            if not self.scored[r]:
                continue
            self.scoring.evaluate(&row.slots[0 if row.kind == 0 else r * 11], r, metric, &score,
                                  &row.order[0 if row.kind == 0 else r * 11])
            if score.supported and self.scoring.priority >= 20:
                if self.scoring.priority == 20:
                    first_defence, last_defence = 0, 5
                elif self.scoring.priority == 21:
                    first_defence, last_defence = 3, 5
                else:
                    first_defence = self.scoring.priority - 22
                    last_defence = first_defence + 1
                for j in range(first_defence, last_defence):
                    if score.defence_rolls[j] < 0:
                        raise ValueError("Player defensive roll is unavailable: required combat levels are unknown")
            if row.kind != 2 and slot > 1 and not score.supported:
                return False
            add(&weight, self.weights[r])
            add(&secondary, score.secondary * self.weights[r])
            if self.cost_objective:
                # CostSearch rejects unsupported included roles even at zero weight.
                if not score.supported:
                    costs_known = False
                if self.weights[r] > 0:
                    active_cost = True
                    attack_cost = self.attack_cost(&row.slots[0 if row.kind == 0 else r * 11], &score)
                    if attack_cost < 0 or score.interval <= 0:
                        costs_known = False
                    else:
                        hourly = (attack_cost / score.interval) * 3600
                        if not isfinite(hourly) or hourly < 0:
                            costs_known = False
                        add(&spend, self.weights[r] * hourly / 3600)
                    add(&damage, self.weights[r] * score.dps)
            if row.kind == 1:
                for j in range(row.order_count[r]):
                    s = row.order[r * 11 + j]
                    item = row.slots[r * 11 + s]
                    if item:
                        add(&primary, self.marginals[r * self.scoring.item_count + item] * self.weights[r])
            else:
                add(&primary, score.dps * self.weights[r] if score.supported else 0.0)
        row.key[0] = -value(&primary)
        row.key[1] = -value(&secondary) / (value(&weight) or 1.0)
        if self.cost_objective:
            row.key[1] = value(&spend) / value(&damage) if costs_known and active_cost and value(&damage) > 0 else 1e100
        if row.kind == 0:
            if all_melee:
                for s in range(11):
                    item = row.slots[s]
                    if item:
                        strength += self.scoring.item_bonuses[item * 14 + 5]
            row.key[2], row.key[3], row.key[4] = cost, -strength, untradeable
        elif row.kind == 1:
            row.key[2], row.key[3], row.key[4] = count, cost, untradeable
        else:
            row.key[2] = count
            row.key[3] = cost if self.acquisition_ties else 0
            row.key[4] = untradeable if self.acquisition_ties else 0
        if metric:
            row.key[0], row.key[1] = row.key[1], row.key[0]
        self.identity(row)
        return True


cdef class Expansion:
    cdef StageContext context
    cdef vector[Candidate] states, candidates, equipment
    cdef vector[int] choices[4]
    cdef int roles[4]
    cdef int nroles, kind, slot, cap, tuple_role
    cdef bint frontier, metric
    cdef long long cursor, total, combinations
    cdef public long long consumed
    cdef public long long candidate_count
    cdef bint finished

    def __init__(self, StageContext context, kind, states, choices, slot, roles, cap,
                 frontier, metric, tuple_role):
        cdef Candidate row
        cdef int r, s, index, dense
        cdef object mapping, equipment
        self.context = context
        if kind not in ("loadout", "joint", "tuple"):
            raise ValueError("Unknown native stage kind")
        self.kind = {"loadout": 0, "joint": 1, "tuple": 2}[kind]
        self.slot = SLOT_NAMES.index(slot) if slot is not None else -1
        self.cap = -1 if cap is None else cap
        self.frontier, self.metric = frontier, metric
        self.tuple_role = context.data.role_names.index(tuple_role) if tuple_role is not None else -1
        roles = context.data.role_names if roles is None else roles
        self.nroles = len(roles)
        if not 1 <= self.nroles <= 4:
            raise ValueError("Native stages require one to four roles")
        for index, role in enumerate(roles):
            self.roles[index] = context.data.role_names.index(role)
        for mapping in states:
            memset(row.slots, 0, sizeof(row.slots))
            memset(row.order, -1, sizeof(row.order))
            memset(row.order_count, 0, sizeof(row.order_count))
            row.present = 0
            row.kind = self.kind
            if self.kind == 0:
                for name, item in mapping.items():
                    s = SLOT_NAMES.index(name)
                    row.slots[s] = context.scoring.dense_index[item]
                    row.order[row.order_count[0]] = s
                    row.order_count[0] += 1
                row.present = 1
            else:
                for role, equipment in mapping.items():
                    r = context.data.role_names.index(role)
                    row.present |= 1 << r
                    for name, item in equipment.items():
                        s = SLOT_NAMES.index(name)
                        row.slots[r * 11 + s] = context.scoring.dense_index[item]
                        row.order[r * 11 + row.order_count[r]] = s
                        row.order_count[r] += 1
            self.states.push_back(row)
        self.combinations = 1
        if self.kind == 2:
            if self.tuple_role < 0:
                raise ValueError("Tuple stages require tuple_role")
            for mapping in choices:
                memset(row.slots, 0, sizeof(row.slots))
                memset(row.order, -1, sizeof(row.order))
                memset(row.order_count, 0, sizeof(row.order_count))
                for name, item in mapping.items():
                    s = SLOT_NAMES.index(name)
                    row.slots[s] = context.scoring.dense_index[item]
                    row.order[row.order_count[0]] = s
                    row.order_count[0] += 1
                self.equipment.push_back(row)
            self.combinations = self.equipment.size()
        else:
            if self.slot < 0:
                raise ValueError("Slot expansion requires slot")
            grouped = [choices] if self.kind == 0 else choices
            if len(grouped) != (1 if self.kind == 0 else context.scoring.role_count):
                raise ValueError("Wrong native choice groups")
            for r, group in enumerate(grouped):
                for item in group:
                    dense = 0 if item is None else context.scoring.dense_index[item]
                    self.choices[r].push_back(dense)
                self.combinations *= self.choices[r].size()
        self.total = self.states.size() * self.combinations

    @property
    def done(self):
        return self.cursor >= self.total

    def advance(self, max_attempts=1024):
        cdef long long end, consumed = 0, combination
        cdef Candidate row
        cdef int r, assigned
        if type(max_attempts) is not int or not 1 <= max_attempts <= 1024:
            raise ValueError("Native chunks require 1 through 1024 attempts")
        if self.finished:
            raise ValueError("Native stage already finalized")
        end = min(self.total, self.cursor + max_attempts)
        while self.cursor < end:
            row = self.states[self.cursor // self.combinations]
            row.sequence = self.cursor
            combination = self.cursor % self.combinations
            if self.kind == 2:
                memcpy(&row.slots[self.tuple_role * 11], self.equipment[combination].slots, 11 * sizeof(int))
                memcpy(&row.order[self.tuple_role * 11], self.equipment[combination].order, 11 * sizeof(int))
                row.order_count[self.tuple_role] = self.equipment[combination].order_count[0]
                row.present |= 1 << self.tuple_role
            elif self.kind == 0:
                assigned = self.choices[0][combination]
                if assigned:
                    if not row.slots[self.slot]:
                        row.order[row.order_count[0]] = self.slot
                        row.order_count[0] += 1
                    row.slots[self.slot] = assigned
            else:
                for r in range(self.context.scoring.role_count - 1, -1, -1):
                    assigned = self.choices[r][combination % self.choices[r].size()]
                    combination //= self.choices[r].size()
                    if assigned:
                        if not row.slots[r * 11 + self.slot]:
                            row.order[r * 11 + row.order_count[r]] = self.slot
                            row.order_count[r] += 1
                        row.slots[r * 11 + self.slot] = assigned
            self.cursor += 1
            consumed += 1
            if self.context.evaluate(&row, self.roles, self.nroles, self.slot, self.cap, self.metric):
                self.candidates.push_back(row)
        self.consumed += consumed
        self.candidate_count = self.candidates.size()
        return consumed

    def finish(self, limit):
        cdef vector[Candidate] selected
        cdef vector[Candidate] bands[8]
        cdef size_t positions[8]
        cdef size_t index, extreme = 0
        cdef int band, r, s
        cdef double low, high, score
        cdef bint remaining
        cdef Candidate row
        if type(limit) is not int or limit < 1:
            raise ValueError("Native retention limit must be positive")
        if self.finished:
            raise ValueError("Native stage already finalized")
        self.finished = True
        sort(self.candidates.begin(), self.candidates.end(), less)
        if not self.frontier or self.candidates.size() <= limit:
            for index in range(min(self.candidates.size(), limit)):
                selected.push_back(self.candidates[index])
        elif self.candidates.size():
            low = high = -self.candidates[0].key[0]
            for index in range(self.candidates.size()):
                score = -self.candidates[index].key[0]
                low = min(low, score)
                high = max(high, score)
                if secondary_less(self.candidates[index], self.candidates[extreme]):
                    extreme = index
            for index in range(self.candidates.size()):
                score = -self.candidates[index].key[0]
                band = min(7, <int>(8 * (score - low) / (high - low))) if high > low else 0
                bands[band].push_back(self.candidates[index])
            for band in range(8):
                sort(bands[band].begin(), bands[band].end(), secondary_less)
                positions[band] = 0
            selected.push_back(self.candidates[0])
            if not same(self.candidates[0], self.candidates[extreme]):
                selected.push_back(self.candidates[extreme])
            remaining = True
            while selected.size() < limit and remaining:
                remaining = False
                for band in range(8):
                    if positions[band] < bands[band].size():
                        remaining = True
                        row = bands[band][positions[band]]
                        positions[band] += 1
                        if not contains(selected, row):
                            selected.push_back(row)
                            if selected.size() == limit:
                                break
        result = []
        for index in range(min(selected.size(), limit) if self.metric else selected.size()):
            row = selected[index]
            if self.kind == 0:
                result.append({SLOT_NAMES[row.order[s]]: self.context.scoring.dense_ids[row.slots[row.order[s]]]
                               for s in range(row.order_count[0])})
            else:
                result.append({self.context.data.role_names[r]: {
                    SLOT_NAMES[row.order[r * 11 + s]]: self.context.scoring.dense_ids[row.slots[r * 11 + row.order[r * 11 + s]]]
                    for s in range(row.order_count[r])
                } for r in range(self.context.scoring.role_count) if row.present & (1 << r)})
        return result
