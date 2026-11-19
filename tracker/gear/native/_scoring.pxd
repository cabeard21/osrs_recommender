from libcpp.vector cimport vector

cdef int required_defence_mask(int priority) noexcept nogil

cdef struct Score:
    bint supported
    double dps
    double accuracy
    double secondary
    double interval
    double defence_rolls[5]
    bint missing_defence
    int option_index
    double bonuses[14]

cdef struct PreparedGear:
    double bonuses[14]
    bint legal
    bint ammo_ok

cdef class ScoringContext:
    cdef readonly int item_count, role_count
    cdef readonly object dense_ids, dense_index, option_records, option_weapons
    cdef long long[::1] original_ids, item_bonuses
    cdef double[::1] item_magic_damage
    cdef int[::1] item_slots, two_handed, eligible
    cdef int[::1] bad_items, ammo_required, ammo_types, ammo_offsets, ammo_codes
    cdef int[::1] offsets, lengths, fixed_roles, role_styles
    cdef long long[::1] options
    cdef int[::1] amulet_mask, amulet_bonus, tome_element, bolt_family, reviewed_crossbow, zaryte, hopper_shield
    cdef int[::1] spell_element, searing, ranged_level, diary, target_hp, target_traits
    cdef int[::1] slayer_bonus, slayer_staff, on_slayer_task, magic_dart, magic_level
    cdef int[::1] leafy_weapon, broad_ammo, seeking_ammo, target_leafy
    cdef int[::1] size_damage_per_size, size_damage_max_size, target_size
    cdef int[::1] status_kind, status_duration, halberd, serpentine
    cdef int[::1] dragonbane_accuracy, dragonbane_damage
    cdef int[::1] demonbane_weapon, holy_water, purging_staff, scorching_bow
    cdef int[::1] target_demon, demonbane_vulnerability, demonbane_spell, mark_of_darkness
    cdef int priority
    cdef readonly object objective_ids
    cdef int[::1] objective_kinds, objective_masks, objective_means
    cdef int[::1] option_kind, ranged_kind, ammo_valid, body_recovery, torag
    cdef int[::1] supply_class
    cdef int[::1] serp_head
    cdef double[::1] serp_cost
    cdef int supply_count
    cdef double[::1] option_cost, option_on_hit_cost, option_per_second_cost, unit_prices, recovery
    cdef double attack_cost(self, const int* slots, Score* score) noexcept
    cdef void project_objectives(self, const int* slots, Score* result, double* values) except *
    cdef void build_option_mask(self, const int* slots, int role_index, int start, int length,
                                object option_allowed, object equipment,
                                int settled_slot, vector[unsigned char]& mask) except *
    cdef bint project_slots(self, const int* slots, int role_index, const int* order, double* maximum,
                            object option_allowed=*, object equipment=*, int settled_slot=*,
                            const unsigned char* prepared_mask=*) except -1
    cdef double secondary_for(self, const double* bonuses, double accuracy, int option_index) noexcept nogil
    cdef void prepare_gear(self, const int* slots, const int* order, PreparedGear* gear) noexcept nogil
    cdef void evaluate(self, const int* slots, int role_index, bint metric, Score* output,
                       const int* order=*, int specific_option=*, const unsigned char* allowed=*,
                       PreparedGear* prepared=*) noexcept nogil
    cdef void evaluate_filtered(self, const int* slots, int role_index, bint metric, Score* output,
                                const int* order, object option_allowed, object equipment=*,
                                int settled_slot=*) except *
