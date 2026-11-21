# cython: language_level=3, boundscheck=False, wraparound=False
# distutils: language=c++
"""Native expansion, constraints and stable retention for ordinary gear beams."""

from libc.math cimport fabs, isfinite
from libc.limits cimport LLONG_MIN
from libc.string cimport memset, memcpy
from cpython.bytes cimport PyBytes_FromStringAndSize
from libcpp.vector cimport vector
from libcpp.string cimport string, to_string
from libcpp.algorithm cimport sort

from tracker.gear.native._scoring cimport ScoringContext, Score, required_defence_mask

from tracker.gear.compact_states import SLOT_NAMES
from tracker.gear.native import record
from tracker.gear.native.stage_context import pack_stage, pack_runes

include "_transitions.pxi"


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
    cdef long long[::1] copy_adjustments
    cdef int[::1] copy_family_offsets, copy_form_bits
    cdef int[::1] untradeable, edges, melee, scored
    cdef double[::1] weights, marginals
    cdef vector[string] role_names, slot_names
    cdef int role_order[4]
    cdef int slot_order[11]
    cdef long long purchase_budget, risk_budget
    cdef int capacity
    cdef bint acquisition_ties
    cdef long long[::1] risk_unavoidable, risk_recoverable
    cdef int[::1] risk_priorities, risk_unpriced
    cdef int risk_kept_slots, risk_dimension
    cdef object risk_feasible
    cdef int[::1] guarded_ammunition
    cdef int ammunition_users, ammunition_keepers, ammunition_attack_roles
    cdef object rune_option_allowed
    cdef bint packed_runes
    cdef unsigned long long[::1] rune_suppliers, rune_tomes, rune_collisions, rune_masks
    cdef int[::1] rune_gear, rune_recipes, rune_quantities
    cdef long long[::1] rune_prices

    def __init__(self, ScoringContext scoring, search):
        cdef bytes encoded
        cdef int index
        self.scoring = scoring
        self.data = pack_stage(search, scoring)
        self.markets = self.data.markets
        self.costs = self.data.costs
        self.copy_adjustments = self.data.copy_adjustments
        self.copy_family_offsets = self.data.copy_family_offsets
        self.copy_form_bits = self.data.copy_form_bits
        self.untradeable = self.data.untradeable
        self.edges = self.data.edges
        self.melee = self.data.melee
        self.scored = self.data.scored
        self.weights = self.data.weights
        self.marginals = self.data.marginals
        self.purchase_budget = -1 if self.data.purchase_budget is None else self.data.purchase_budget
        self.capacity = self.data.capacity
        self.acquisition_ties = self.data.acquisition_ties
        self.rune_option_allowed = (
            search.rune_option_allowed if getattr(search, "rune_limits_active", False) else None
        )
        runes = pack_runes(search, scoring)
        self.packed_runes = runes is not None
        if self.packed_runes:
            self.rune_suppliers = runes.suppliers
            self.rune_tomes = runes.tome_suppliers
            self.rune_collisions = runes.collisions
            self.rune_masks = runes.recipe_masks
            self.rune_gear = runes.known_gear
            self.rune_recipes = runes.recipes
            self.rune_quantities = runes.quantities
            self.rune_prices = runes.prices
            record("rune_option_mask", roles=self.data.role_names)
        elif self.rune_option_allowed is not None:
            record("fallback", reason="Wilderness rune bounds exceed native range")
        self.risk_dimension = (scoring.objective_ids.index("wilderness_loss_gp") + 1
                               if "wilderness_loss_gp" in scoring.objective_ids else -1)
        self.risk_feasible = None
        if self.data.risk is not None:
            self.risk_budget = self.data.risk.limit
            self.guarded_ammunition = self.data.risk.guarded_ammunition
            self.ammunition_users = self.data.risk.ammunition_users
            self.ammunition_keepers = self.data.risk.ammunition_keepers
            self.ammunition_attack_roles = self.data.risk.ammunition_attack_roles
            self.risk_unavoidable = self.data.risk.unavoidable
            self.risk_recoverable = self.data.risk.recoverable
            self.risk_priorities = self.data.risk.priorities
            self.risk_unpriced = self.data.risk.unpriced
            self.risk_kept_slots = self.data.risk.kept_slots
            self.risk_feasible = self.data.risk.feasible
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

    def begin_projection(self, *, states, choices, slot, roles):
        if slot not in SLOT_NAMES or slot == SLOT_NAMES[10]:
            raise ValueError("Native projection requires a partial equipment slot")
        return Expansion(self, "loadout", states, choices, slot, roles, None, False, False, None)

    cdef bint may_equip_ammunition(self, const int* slots, int* roles, int nroles) noexcept:
        cdef int index, mask = 0
        if not self.guarded_ammunition[slots[2]]:
            return True
        for index in range(nroles):
            mask |= 1 << roles[index]
        return (self.ammunition_users & ~mask) or self.uses_ammunition(slots, mask)

    cdef bint uses_ammunition(self, const int* slots, int mask) noexcept:
        cdef int ammo = slots[2], weapon = slots[0], index
        if self.ammunition_keepers & mask:
            return True
        if self.ammunition_attack_roles & mask:
            for index in range(self.scoring.ammo_offsets[weapon], self.scoring.ammo_offsets[weapon + 1]):
                if self.scoring.ammo_types[ammo] == self.scoring.ammo_codes[index]:
                    return True
        return False

    cdef bint complete_ammunition_allowed(self, const Candidate* row) noexcept:
        cdef int r, other, ammo
        for r in range(self.scoring.role_count):
            ammo = row.slots[r * 11 + 2]
            if not self.guarded_ammunition[ammo]:
                continue
            for other in range(self.scoring.role_count):
                if row.slots[other * 11 + 2] == ammo and self.uses_ammunition(&row.slots[other * 11], 1 << other):
                    break
            else:
                return False
        return True

    cdef bint wilderness_bound(self, const Candidate* row, int slot, double* bound=NULL) noexcept:
        """Deduct unavoidable costs plus losses outside the best possible protection."""
        cdef int distinct[44]
        cdef int count = 0, r, s, item, j
        cdef int nroles = 1 if row.kind == 0 else self.scoring.role_count
        cdef int nslots = 11 if row.kind == 2 else slot + 1
        cdef bint duplicate, needs_protection = False
        cdef long long saved[4]
        cdef long long amount, remaining = self.risk_budget
        memset(saved, 0, sizeof(saved))
        for r in range(nroles):
            if row.kind != 0 and not row.present & (1 << r):
                continue
            # Items in later slots may be provisional synergy seed equipment.
            for s in range(nslots):
                item = row.slots[r * 11 + s]
                if not item:
                    continue
                duplicate = False
                for j in range(count):
                    if distinct[j] == item:
                        duplicate = True
                        break
                if duplicate:
                    continue
                if self.risk_unpriced[item] == 2:
                    return False
                needs_protection |= self.risk_unpriced[item] == 1
                distinct[count] = item
                count += 1
                amount = self.risk_unavoidable[item]
                if bound != NULL:
                    bound[0] += amount
                if self.risk_budget >= 0:
                    if amount > remaining:
                        return False
                    remaining -= amount
                amount = self.risk_recoverable[item]
                for j in range(self.risk_kept_slots):
                    if amount > saved[j]:
                        amount, saved[j] = saved[j], amount
                if bound != NULL:
                    bound[0] += amount
                if self.risk_budget >= 0:
                    if amount > remaining:
                        return False
                    remaining -= amount
        if needs_protection:
            for j in range(count):
                if self.risk_unpriced[distinct[j]] == 1 and self.wilderness_could_expose(distinct, count, j):
                    return False
        return True

    cdef bint wilderness_could_expose(self, const int* physical, int count, int target) noexcept:
        cdef int remaining = self.risk_kept_slots
        cdef int target_priority = self.risk_priorities[physical[target]]
        cdef int other_priority, j
        if not remaining:
            return True
        # An unknown priority can precede any known priority. An equal
        # priority might also win a slot because inventory order is unknown.
        for j in range(count):
            if j == target:
                continue
            other_priority = self.risk_priorities[physical[j]]
            if other_priority == -2:
                continue
            if target_priority == -1 or other_priority == -1 or other_priority >= target_priority:
                remaining -= 1
                if not remaining:
                    return True
        return False

    cdef bint wilderness_complete(self, const int* physical, int count) except -1:
        # Share the item-specific minimum quantity and death rules with Python.
        cdef int j
        ids = {self.scoring.original_ids[physical[j]] for j in range(count)}
        return self.risk_feasible(ids)

    cdef bint rune_bundle_fits(self, unsigned long long bundle, unsigned long long collisions,
                               int recipe, long long exposed, const long long* gear_saved) noexcept:
        cdef long long saved[4]
        cdef long long price, swap
        cdef int rune, quantity, copy, slot
        cdef int rune_count = self.rune_prices.shape[0]
        if bundle & collisions:
            return False
        memcpy(saved, gear_saved, sizeof(saved))
        for rune in range(rune_count):
            if not bundle & (1ULL << rune):
                continue
            price = self.rune_prices[rune]
            quantity = self.rune_quantities[recipe * rune_count + rune]
            if price == -2 or (price == -1 and quantity > self.risk_kept_slots):
                return False
            if price <= 0:
                continue
            exposed += price * quantity
            for copy in range(min(quantity, self.risk_kept_slots)):
                price = self.rune_prices[rune]
                for slot in range(self.risk_kept_slots):
                    if price > saved[slot]:
                        swap = price
                        price = saved[slot]
                        saved[slot] = swap
        if self.risk_budget < 0:
            return True
        for slot in range(self.risk_kept_slots):
            exposed -= saved[slot]
        return exposed <= self.risk_budget

    cdef void fill_rune_mask(self, const int* slots, int role, bint metric, int settled,
                             vector[unsigned char]& mask) except *:
        cdef int physical[11]
        cdef long long saved[4]
        cdef long long amount, swap, exposed = 0, gear_loss
        cdef unsigned long long supplies = self.rune_suppliers[slots[0]] | self.rune_tomes[slots[1]]
        cdef unsigned long long collisions = 0, bundle
        cdef int offset = ((<int>metric * self.scoring.role_count + role) * self.scoring.item_count + slots[0])
        cdef int start = self.scoring.offsets[offset], length = self.scoring.lengths[offset]
        cdef int position, count = 0, j, item, recipe, index
        cdef bint gear_fits = True
        if self.scoring.role_styles[role] != 4 or not length:
            return
        memset(saved, 0, sizeof(saved))
        for position in range(settled + 1):
            item = slots[position]
            if not item:
                continue
            for j in range(count):
                if physical[j] == item:
                    break
            else:
                physical[count] = item
                count += 1
                gear_fits &= self.rune_gear[item] and self.risk_unpriced[item] != 2
                collisions |= self.rune_collisions[item]
                amount = self.risk_recoverable[item]
                exposed += self.risk_unavoidable[item] + amount
                for j in range(self.risk_kept_slots):
                    if amount > saved[j]:
                        swap = amount
                        amount = saved[j]
                        saved[j] = swap
        gear_loss = exposed
        for j in range(self.risk_kept_slots):
            gear_loss -= saved[j]
        gear_fits &= self.risk_budget < 0 or gear_loss <= self.risk_budget
        for j in range(count):
            if self.risk_unpriced[physical[j]] == 1 and self.wilderness_could_expose(physical, count, j):
                gear_fits = False
                break
        mask.resize(length, 1)
        for index in range(start, start + length):
            if self.scoring.options[index * 18] != 4 or not self.scoring.options[index * 18 + 9]:
                continue
            recipe = self.rune_recipes[index]
            if recipe == -2:
                continue
            if recipe == -1:
                mask[index - start] = 0
                continue
            bundle = self.rune_masks[recipe] & ~supplies
            mask[index - start] = not bundle or (gear_fits and self.rune_bundle_fits(
                bundle, collisions, recipe, exposed, saved
            ))

    def option_mask(self, equipment, int role_index, bint metric=False):
        """Return the native mask for a Python-requested concrete option batch."""
        cdef int slots[11]
        cdef vector[unsigned char] mask
        if not self.packed_runes:
            return None
        if not 0 <= role_index < self.scoring.role_count:
            raise ValueError("Invalid native role index")
        memset(slots, 0, sizeof(slots))
        for slot, item in equipment.items():
            if slot not in SLOT_NAMES or type(item) is not int or item not in self.scoring.dense_index or item == 0:
                raise ValueError("Invalid native equipment")
            slots[SLOT_NAMES.index(slot)] = self.scoring.dense_index[item]
        self.fill_rune_mask(slots, role_index, metric, 10, mask)
        return PyBytes_FromStringAndSize(<char*>&mask[0], mask.size()) if mask.size() else None

    cdef long long copy_cost_delta(self, Candidate* row, int role_count) noexcept nogil:
        """A repeated physical form shares one weapon across the role union."""
        cdef int groups[4]
        cdef int masks[4]
        cdef int group_count = 0, r, j, item, family
        cdef long long total = 0, adjustment
        if self.copy_adjustments.shape[0] == 1:
            return 0
        for r in range(role_count):
            if row.kind != 0 and not (row.present & (1 << r)):
                continue
            item = row.slots[r * 11]
            family = self.copy_family_offsets[item]
            if family == 0:
                continue
            for j in range(group_count):
                if groups[j] == family:
                    masks[j] |= self.copy_form_bits[item]
                    break
            else:
                groups[group_count] = family
                masks[group_count] = self.copy_form_bits[item]
                group_count += 1
        for j in range(group_count):
            adjustment = self.copy_adjustments[groups[j] + masks[j]]
            if adjustment == LLONG_MIN:
                return LLONG_MIN
            total += adjustment
        return total

    cdef bint purchase_fits(self, const int* physical, int count, long long cost, long long copy_delta,
                            bint head_pending) noexcept:
        if self.purchase_budget < 0:
            return True
        if self.risk_feasible is None or not head_pending:
            return cost <= self.purchase_budget
        # A Wilderness synergy seed may still replace its provisional head.
        # Market aliases use the highest physical ID among settled items.
        cdef int j, k, item, later
        # These adjustments concern weapons, already settled independently of head.
        cdef long long market, settled_cost = copy_delta
        for j in range(count):
            item = physical[j]
            market = self.markets[item]
            if not market or self.scoring.item_slots[item] == 3:
                continue
            for k in range(j + 1, count):
                later = physical[k]
                if self.scoring.item_slots[later] != 3 and self.markets[later] == market:
                    break
            else:
                settled_cost += self.costs[item]
        return settled_cost <= self.purchase_budget

    cdef bint project_partial(self, Candidate* row, int* roles, int nroles, int slot, double* output) except -1:
        """Only the Python partial beam's compatibility, eligibility and cost filters."""
        cdef int physical[11]
        cdef int count = 0, s, j, k, item, role, dimension
        cdef long long copy_delta = self.copy_cost_delta(row, 1)
        cdef long long cost = copy_delta
        cdef bint duplicate, later, supported
        cdef double maximum[65]
        cdef Sum totals[65]
        cdef Sum weight = Sum(0.0, 0.0)
        cdef double denominator, risk_bound = 0.0
        cdef int dimensions = self.scoring.objective_kinds.shape[0] + 1
        cdef vector[unsigned char] mask
        if copy_delta == LLONG_MIN:
            return False
        if row.slots[0] and row.slots[1] and self.scoring.two_handed[row.slots[0]]:
            return False
        if slot == 2 and self.risk_feasible is not None and not self.may_equip_ammunition(row.slots, roles, nroles):
            return False
        for s in range(11):
            item = row.slots[s]
            if not item:
                continue
            if not self.scoring.eligible[item]:
                return False
            duplicate = False
            for j in range(count):
                if physical[j] == item:
                    duplicate = True
                    break
            if not duplicate:
                physical[count] = item
                count += 1
        # Dense indices follow ascending physical IDs; aliases retain the last quote.
        for j in range(1, count):
            item = physical[j]
            k = j
            while k > 0 and physical[k - 1] > item:
                physical[k] = physical[k - 1]
                k -= 1
            physical[k] = item
        for j in range(count):
            item = physical[j]
            if not self.markets[item]:
                continue
            later = False
            for k in range(j + 1, count):
                if self.markets[physical[k]] == self.markets[item]:
                    later = True
                    break
            if not later:
                cost += self.costs[item]
        if not self.purchase_fits(physical, count, cost, copy_delta, slot < 3):
            return False
        if self.risk_feasible is not None and not self.wilderness_bound(row, slot, &risk_bound):
            return False
        memset(totals, 0, sizeof(totals))
        for j in range(nroles):
            role = roles[j]
            if not self.scored[role]:
                continue
            memset(maximum, 0, sizeof(maximum))
            if self.packed_runes and slot >= 2:
                mask.clear()
                self.fill_rune_mask(row.slots, role, False, slot, mask)
                supported = self.scoring.project_slots(
                    row.slots, role, row.order, maximum, None, None, slot,
                    &mask[0] if mask.size() else NULL,
                )
            elif self.rune_option_allowed is not None and slot >= 2:
                supported = self.scoring.project_slots(
                    row.slots, role, row.order, maximum, self.rune_option_allowed, None, slot
                )
            else:
                supported = self.scoring.project_slots(row.slots, role, row.order, maximum)
            if not supported and slot > 1:
                return False
            add(&weight, self.weights[role])
            if supported:
                for dimension in range(dimensions):
                    add(&totals[dimension], maximum[dimension] * self.weights[role])
        denominator = value(&weight) or 1.0
        for dimension in range(dimensions):
            output[dimension] = value(&totals[dimension]) / denominator
        if self.risk_dimension >= 0:
            output[self.risk_dimension] = -risk_bound
        return True

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

    cdef bint evaluate(self, Candidate* row, int* roles, int nroles, int slot,
                       int cap, bint metric) except -1:
        cdef int physical[44]
        cdef vector[unsigned char] mask
        cdef int count = 0
        cdef int index, item, previous, r, s, j, k, d, outside
        cdef int equipment_offset
        cdef long long cost, copy_delta
        cdef long long amount, market, untradeable = 0, strength = 0
        cdef bint duplicate, later, complete, all_melee = True
        cdef Score score
        cdef Sum primary = Sum(0.0, 0.0)
        cdef Sum secondary = Sum(0.0, 0.0)
        cdef Sum weight = Sum(0.0, 0.0)
        cdef int row_roles = 1 if row.kind == 0 else self.scoring.role_count
        copy_delta = self.copy_cost_delta(row, row_roles)
        if copy_delta == LLONG_MIN:
            return False
        cost = copy_delta
        if self.risk_feasible is not None:
            if row.kind == 0 and slot == 2 and not self.may_equip_ammunition(row.slots, roles, nroles):
                return False
            if row.kind != 0 and (slot == 2 or row.kind == 2) and row.present == (1 << row_roles) - 1:
                if not self.complete_ammunition_allowed(row):
                    return False
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
        if not self.purchase_fits(physical, count, cost, copy_delta, row.kind != 2 and slot < 3):
            return False
        if self.risk_feasible is not None and not self.wilderness_bound(row, slot):
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
        if self.risk_feasible is not None and (slot == 10 or row.kind == 2):
            if row.kind == 0:
                complete = nroles == self.scoring.role_count
            else:
                complete = row.present == (1 << self.scoring.role_count) - 1
            if complete and not self.wilderness_complete(physical, count):
                return False
        for index in range(nroles):
            r = roles[index]
            if row.kind != 0 and not row.present & (1 << r):
                continue
            equipment_offset = 0 if row.kind == 0 else r * 11
            all_melee = all_melee and (
                self.melee[r] or (
                    self.scoring.role_styles[r] == 3
                    and self.scoring.original_ids[row.slots[equipment_offset]] == 29305
                )
            )
            if not self.scored[r]:
                continue
            if self.packed_runes and self.scoring.role_styles[r] == 4 and (row.kind == 2 or slot >= 2):
                mask.clear()
                self.fill_rune_mask(&row.slots[equipment_offset], r, metric, 10 if row.kind == 2 else slot, mask)
                self.scoring.evaluate(
                    &row.slots[equipment_offset], r, metric, &score, &row.order[equipment_offset],
                    -1, &mask[0] if mask.size() else NULL,
                )
                if not score.supported:
                    return False
            elif self.rune_option_allowed is not None and self.scoring.role_styles[r] == 4 and (row.kind == 2 or slot >= 2):
                self.scoring.evaluate_filtered(
                    &row.slots[equipment_offset], r, metric, &score, &row.order[equipment_offset],
                    self.rune_option_allowed, None, 10 if row.kind == 2 else slot,
                )
                if not score.supported:
                    return False
            else:
                self.scoring.evaluate(&row.slots[equipment_offset], r, metric, &score,
                                      &row.order[equipment_offset])
            if score.supported and self.scoring.priority >= 20:
                for j in range(5):
                    if required_defence_mask(self.scoring.priority) & (1 << j) and score.defence_rolls[j] < 0:
                        raise ValueError("Player defensive roll is unavailable: required combat levels are unknown")
            if row.kind != 2 and slot > 1 and not score.supported:
                return False
            add(&weight, self.weights[r])
            add(&secondary, score.secondary * self.weights[r])
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

    def advance_projection(self, max_attempts=1024):
        """Stream an attempt-ordered chunk of accepted partial equipment envelopes."""
        cdef long long end, combination, consumed = 0
        cdef Candidate row
        cdef int assigned, s, dimension
        cdef double projection[65]
        if self.kind != 0 or self.slot < 0 or self.slot >= 10:
            raise ValueError("Native projection requires a partial loadout stage")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 1024:
            raise ValueError("Native chunks require 1 through 1024 attempts")
        if self.finished:
            raise ValueError("Native stage already finalized")
        end = min(self.total, self.cursor + max_attempts)
        result = []
        while self.cursor < end:
            row = self.states[self.cursor // self.combinations]
            combination = self.cursor % self.combinations
            assigned = self.choices[0][combination]
            if assigned:
                if not row.slots[self.slot]:
                    row.order[row.order_count[0]] = self.slot
                    row.order_count[0] += 1
                row.slots[self.slot] = assigned
            self.cursor += 1
            consumed += 1
            if self.context.project_partial(&row, self.roles, self.nroles, self.slot, projection):
                result.append((
                    {SLOT_NAMES[row.order[s]]: self.context.scoring.dense_ids[row.slots[row.order[s]]]
                     for s in range(row.order_count[0])},
                    tuple(projection[dimension] for dimension in range(self.context.scoring.objective_kinds.shape[0] + 1)),
                ))
        self.consumed += consumed
        self.candidate_count += len(result)
        return result

    def complete_candidates(self):
        """Stream expanded mappings before retention; caller decides stage completeness."""
        cdef size_t index
        cdef int r, s
        cdef Candidate row
        if self.finished:
            raise ValueError("Native stage already finalized")
        for index in range(self.candidates.size()):
            row = self.candidates[index]
            if self.kind == 0:
                yield {SLOT_NAMES[row.order[s]]: self.context.scoring.dense_ids[row.slots[row.order[s]]]
                       for s in range(row.order_count[0])}
            else:
                yield {self.context.data.role_names[r]: {
                    SLOT_NAMES[row.order[r * 11 + s]]: self.context.scoring.dense_ids[row.slots[r * 11 + row.order[r * 11 + s]]]
                    for s in range(row.order_count[r])
                } for r in range(self.context.scoring.role_count) if row.present & (1 << r)}

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

cdef struct TripRule:
    long long priority, exposed, protected, charge
    bint slot, ammo, charged, always_lost

cdef struct TripItem:
    TripRule rule
    long long item, quantity

cdef struct TripEntry:
    long long item, priority, exposed, protected, saving


cdef bint trip_order(const TripEntry& left, const TripEntry& right) noexcept nogil:
    if left.priority != right.priority:
        return left.priority > right.priority
    if left.saving != right.saving:
        return left.saving < right.saving
    return left.item < right.item


cdef long long trip_amount(TripRule rule, long long quantity, bint kept) noexcept nogil:
    cdef long long base = rule.protected if kept else rule.exposed
    if base < 0:
        return -1
    if rule.charged and (rule.always_lost or not kept):
        return -1 if rule.charge < 0 else base + quantity * rule.charge
    return base * quantity if rule.ammo else base


cdef long long trip_interpretation(vector[TripItem]& items, int keep, bint stack) except -2:
    cdef vector[TripEntry] known, uncertain
    cdef TripItem item
    cdef TripEntry entry
    cdef size_t i
    cdef long long exposed = 0, worst = 0, total, amount, remainder, copies
    cdef int keep_known, keep_uncertain, j
    for i in range(items.size()):
        item = items[i]
        entry.item = item.item
        entry.priority = item.rule.priority
        if stack and item.rule.ammo and entry.priority >= 0:
            entry.priority *= item.quantity
        copies = min(keep, item.quantity) if not stack and item.rule.ammo else 1
        if item.rule.slot:
            entry.exposed = trip_amount(item.rule, item.quantity if stack or not item.rule.ammo else 1, False)
            entry.protected = trip_amount(item.rule, item.quantity if stack or not item.rule.ammo else 1, True)
            if entry.exposed < 0:
                entry.saving = 1LL << 57
            elif entry.protected < 0:
                entry.saving = -(1LL << 57)
            else:
                entry.saving = entry.exposed - entry.protected
            for j in range(copies):
                if entry.priority < 0:
                    uncertain.push_back(entry)
                else:
                    known.push_back(entry)
        remainder = item.quantity if not item.rule.slot else item.quantity - copies
        if not item.rule.slot or (item.rule.ammo and not stack and remainder > 0):
            amount = trip_amount(item.rule, remainder, False)
            if amount < 0:
                return -1
            exposed += amount
    sort(known.begin(), known.end(), trip_order)
    sort(uncertain.begin(), uncertain.end(), trip_order)
    keep = min(keep, <int>(known.size() + uncertain.size()))
    for keep_uncertain in range(max(0, keep - <int>known.size()), min(keep, <int>uncertain.size()) + 1):
        keep_known = keep - keep_uncertain
        total = exposed
        for i in range(known.size()):
            amount = known[i].protected if i < <size_t>keep_known else known[i].exposed
            if amount < 0:
                return -1
            total += amount
        for i in range(uncertain.size()):
            amount = uncertain[i].protected if i < <size_t>keep_uncertain else uncertain[i].exposed
            if amount < 0:
                return -1
            total += amount
        worst = max(worst, total)
    return worst


cdef class TripLossContext:
    """Frozen death rules and numeric worst-case stack loss for a complete trip."""
    cdef vector[TripRule] rules
    cdef dict indices

    def __init__(self, death_rules):
        cdef TripRule rule
        self.indices = {}
        for item, death in death_rules.items():
            charge = death.charge
            values = (death.priority, death.unprotected_loss_gp, death.protected_loss_gp,
                      charge.unit_gp if charge else 0)
            if any(value is not None and not 0 <= value < (1 << 55) for value in values):
                raise OverflowError("Wilderness death rules exceed native range")
            rule.priority, rule.exposed, rule.protected, rule.charge = [
                -1 if value is None else value for value in values
            ]
            rule.slot = death.protection_slot
            rule.ammo = death.ammo
            rule.charged = charge is not None
            rule.always_lost = bool(charge and charge.always_lost)
            self.indices[item] = self.rules.size()
            self.rules.push_back(rule)

    def loss(self, quantities, int keep):
        cdef vector[TripItem] items
        cdef TripItem item
        cdef long long whole, units, maximum, safe_term_limit = 1LL << 54
        cdef bint check_units = False
        if not 0 <= keep <= 4 or len(quantities) > 64:
            raise OverflowError("Wilderness trip dimensions exceed native range")
        for item_id, quantity in quantities.items():
            index = self.indices.get(item_id)
            if index is None:
                return None
            if not 1 <= quantity <= (1 << 31) - 1:
                raise OverflowError("Wilderness quantity exceeds native range")
            item.item = item_id
            item.quantity = quantity
            item.rule = self.rules[<size_t>index]
            maximum = max(item.rule.exposed, item.rule.protected, item.rule.charge, item.rule.priority)
            # Reserve room for two terms per item before multiplying or adding.
            if maximum >= (safe_term_limit // item.quantity):
                raise OverflowError("Wilderness trip value exceeds native range")
            check_units |= item.rule.ammo and item.quantity > 1
            items.push_back(item)
        whole = trip_interpretation(items, keep, True)
        if whole < 0:
            return None
        if keep and check_units:
            units = trip_interpretation(items, keep, False)
            if units < 0:
                return None
            whole = max(whole, units)
        return whole
