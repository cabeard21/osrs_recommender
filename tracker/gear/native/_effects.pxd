"""Typed ports of bolts.py; caller supplies immutable reviewed effect metadata."""

cimport cython
from libc.math cimport floor


cdef struct BoltResult:
    double expected
    long long maximum
    double activation


@cython.cdivision(True)
cdef inline long long floor_div(long long numerator, long long divisor) noexcept nogil:
    # Every divisor here is positive. C division truncates, Python floors.
    cdef long long quotient = numerator // divisor
    if numerator < 0 and numerator % divisor:
        quotient -= 1
    return quotient


cdef inline long long floor_sum(long long maximum, long long divisor) noexcept nogil:
    cdef long long quotient, remainder
    if maximum < 0:
        return 0
    quotient = floor_div(maximum, divisor)
    remainder = maximum - quotient * divisor
    return floor_div(divisor * quotient * (quotient - 1), 2) + quotient * (remainder + 1)

cdef enum:
    V_LEGAL, V_WEAPON_ACCURACY, V_RING_ACCURACY, V_WEAPON_DAMAGE, V_RING_DAMAGE, V_DIVISOR, V_CAP, V_WIDTH


cdef inline long long vampyre_hit(long long roll, const int* rule, long long armour,
                                  long long hit_floor=1, long long bonus=0,
                                  long long shot_divisor=1, bint replacement=False) noexcept nogil:
    # Ring and weapon are independently rounded. The NPC cap/divisor applies
    # to each hitsplat, including a hopper's reduced secondary shot.
    if not replacement:
        roll = floor_div(roll * (100 + rule[V_RING_DAMAGE]), 100)
        roll = floor_div(roll * (100 + rule[V_WEAPON_DAMAGE]), 100)
    roll = floor_div(max(hit_floor, roll + bonus), shot_divisor * rule[V_DIVISOR])
    if rule[V_CAP]:
        roll = min(roll, rule[V_CAP])
    return max(0, roll - armour)


cdef inline double vampyre_mean(long long maximum, const int* rule, long long armour,
                                long long hit_floor=1, long long bonus=0, long long divisor=1,
                                long long minimum=0, bint sang=False, bint replacement=False) noexcept nogil:
    cdef long long roll, total = 0
    for roll in range(minimum, maximum + 1):
        total += vampyre_hit(max(1, roll) + 8 if sang else roll, rule, armour, hit_floor, bonus, divisor, replacement)
    return <double>total / (maximum - minimum + 1)


cdef inline double positive_chance(long long maximum, const int* rule, long long armour,
                                   long long divisor=1) noexcept nogil:
    # Threshold for nonzero damage in a monotonic, uniformly distributed hit.
    cdef long long lower = 0, upper = maximum + 1, middle, damage
    while lower < upper:
        middle = lower + (upper - lower) // 2
        damage = vampyre_hit(middle, rule, armour, 1, 0, divisor) if rule != NULL else floor_div(max(1, middle), divisor) - armour
        if damage > 0:
            upper = middle
        else:
            lower = middle + 1
    return <double>(maximum + 1 - lower) / (maximum + 1)


cdef inline double damage_mean(long long maximum, long long armour,
                               long long bonus, long long divisor, const int* rule=NULL) noexcept nogil:
    cdef long long first, count, integer_total
    cdef double ordinary_total
    if rule != NULL:
        return vampyre_mean(maximum, rule, armour, 1, bonus, divisor)
    if divisor == 1:
        first = max(0, armour - bonus + 1)
        count = max(0, maximum - first + 1)
        ordinary_total = count * (first + maximum + 2 * (bonus - armour)) / 2.0
        if bonus == 0:
            ordinary_total += max(0, 1 - armour) - max(0, -armour)
        return ordinary_total / (maximum + 1)
    first = max(0, divisor * (armour + 1) - bonus)
    count = max(0, maximum - first + 1)
    integer_total = (floor_sum(maximum + bonus, divisor)
                     - floor_sum(first + bonus - 1, divisor)
                     - count * armour) if count else 0
    if bonus == 0:
        integer_total += max(0, floor_div(1, divisor) - armour) - max(0, -armour)
    return <double>integer_total / (maximum + 1)


cdef inline BoltResult bolt_damage(int family, long long ranged, long long maximum,
                                   double accuracy, long long hp, bint diary,
                                   bint zaryte, int traits, long long armour,
                                   long long divisor, double chance_multiplier,
                                   const int* rule=NULL) noexcept nogil:
    # Family: opal=1 pearl=2 ruby=3 diamond=4 dragonstone=5 onyx=6.
    # Trait mask: fiery=1 dragon=2 undead=4. HP -1 is unavailable.
    cdef BoltResult result
    cdef double ordinary = damage_mean(maximum, armour, 0, divisor, rule)
    cdef long long normal_max = vampyre_hit(maximum, rule, armour, 1, 0, divisor) if rule != NULL else max(0, floor_div(max(1, maximum), divisor) - armour)
    cdef double base = accuracy * ordinary
    cdef double chance, effect_mean, increment
    cdef long long damage, multiplier, effect_max, bonus, pearl_divisor
    result.expected, result.maximum, result.activation = base, normal_max, 0
    if family == 0:
        return result
    if family == 1:
        chance = 0.05
    elif family == 4:
        chance = 0.10
    elif family == 6:
        chance = 0.11
    else:
        chance = 0.06
    chance = chance * (1.1 if diary else 1) * chance_multiplier
    if chance == 0 or (family == 6 and traits & 4) or (family == 5 and traits & 3):
        return result
    if family == 3:
        if hp < 0:
            result.maximum = -1
            return result
        damage = min(110 if zaryte else 100, floor_div(hp * (22 if zaryte else 20), 100))
        damage = vampyre_hit(0, rule, armour, 0, damage, divisor) if rule != NULL else max(0, floor_div(damage, divisor) - armour)
        result.expected = (1 - chance) * base + chance * damage
        result.maximum = max(normal_max, damage)
        result.activation = chance
        return result
    if family == 4 or family == 6:
        multiplier = (126 if zaryte else 115) if family == 4 else (132 if zaryte else 120)
        effect_max = floor_div(maximum * multiplier, 100)
        effect_mean = vampyre_mean(effect_max, rule, armour, 1, 0, divisor, 0, False, True) if rule != NULL else damage_mean(effect_max, armour, 0, divisor)
        result.activation = chance if family == 4 else chance * accuracy
        result.expected = ((1 - chance) * base + chance * effect_mean if family == 4
                           else accuracy * ((1 - chance) * ordinary + chance * effect_mean))
        result.maximum = max(normal_max, vampyre_hit(effect_max, rule, armour, 1, 0, divisor, True) if rule != NULL else max(0, floor_div(max(1, effect_max), divisor) - armour))
        return result
    if family == 1:
        bonus = floor_div(ranged, 9 if zaryte else 10)
    elif family == 2:
        pearl_divisor = 15 if traits & 1 else 20
        bonus = floor_div(ranged, pearl_divisor - 2 if zaryte else pearl_divisor)
    else:
        bonus = <long long>floor(ranged * 2 / <double>(9 if zaryte else 10))
    result.activation = chance * accuracy if family == 5 else chance
    increment = damage_mean(maximum, armour, bonus, divisor, rule) - ordinary
    result.expected = base + chance * accuracy * increment
    if family != 5:
        result.expected += chance * (1 - accuracy) * (vampyre_hit(0, rule, 0, 0, bonus, divisor) if rule != NULL else floor_div(bonus, divisor))
    result.maximum = max(normal_max,
                         vampyre_hit(maximum, rule, armour, 1, bonus, divisor) if rule != NULL else max(0, floor_div(max(1, maximum + bonus), divisor) - armour),
                         (vampyre_hit(0, rule, 0, 0, bonus, divisor) if rule != NULL else floor_div(bonus, divisor)) if family != 5 else 0)
    return result


cdef inline long long linear_floor_sum(long long count, long long modulus, long long multiplier) noexcept nogil:
    cdef long long offset = 0, result = 0, upper, previous
    while True:
        result += (count - 1) * count * (multiplier // modulus) // 2
        multiplier %= modulus
        result += count * (offset // modulus)
        offset %= modulus
        upper = multiplier * count + offset
        if upper < modulus:
            return result
        count, offset = upper // modulus, upper % modulus
        previous = modulus
        modulus, multiplier = multiplier, previous


cdef inline long long marked_damage_total(long long maximum, long long percent, long long vulnerability) noexcept nogil:
    cdef long long divisor = 100 // percent
    cdef long long quotient = maximum // divisor, remainder = maximum % divisor
    cdef long long bonus = divisor * linear_floor_sum(quotient, 100, vulnerability)
    bonus += (remainder + 1) * (quotient * vulnerability // 100)
    return maximum * (maximum + 1) // 2 + 1 + bonus
