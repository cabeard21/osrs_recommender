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
    cdef int priority
    cdef double secondary_for(self, const double* bonuses, double accuracy, int option_index) noexcept nogil
    cdef void evaluate(self, const int* slots, int role_index, bint metric, Score* output, const int* order=*) noexcept nogil
