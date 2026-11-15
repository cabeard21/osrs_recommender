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


cdef inline double damage_mean(long long maximum, long long armour,
                               long long bonus, long long divisor) noexcept nogil:
    cdef long long first, count, integer_total
    cdef double ordinary_total
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
                                   long long divisor, double chance_multiplier) noexcept nogil:
    # Family: opal=1 pearl=2 ruby=3 diamond=4 dragonstone=5 onyx=6.
    # Trait mask: fiery=1 dragon=2 undead=4. HP -1 is unavailable.
    cdef BoltResult result
    cdef double ordinary = damage_mean(maximum, armour, 0, divisor)
    cdef long long normal_max = max(0, floor_div(max(1, maximum), divisor) - armour)
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
        damage = max(0, floor_div(damage, divisor) - armour)
        result.expected = (1 - chance) * base + chance * damage
        result.maximum = max(normal_max, damage)
        result.activation = chance
        return result
    if family == 4 or family == 6:
        multiplier = (126 if zaryte else 115) if family == 4 else (132 if zaryte else 120)
        effect_max = floor_div(maximum * multiplier, 100)
        effect_mean = damage_mean(effect_max, armour, 0, divisor)
        result.activation = chance if family == 4 else chance * accuracy
        result.expected = ((1 - chance) * base + chance * effect_mean if family == 4
                           else accuracy * ((1 - chance) * ordinary + chance * effect_mean))
        result.maximum = max(normal_max, max(0, floor_div(max(1, effect_max), divisor) - armour))
        return result
    if family == 1:
        bonus = floor_div(ranged, 9 if zaryte else 10)
    elif family == 2:
        pearl_divisor = 15 if traits & 1 else 20
        bonus = floor_div(ranged, pearl_divisor - 2 if zaryte else pearl_divisor)
    else:
        bonus = <long long>floor(ranged * 2 / <double>(9 if zaryte else 10))
    result.activation = chance * accuracy if family == 5 else chance
    increment = damage_mean(maximum, armour, bonus, divisor) - ordinary
    result.expected = base + chance * accuracy * increment
    if family != 5:
        result.expected += chance * (1 - accuracy) * floor_div(bonus, divisor)
    result.maximum = max(normal_max, max(0, floor_div(max(1, maximum + bonus), divisor) - armour),
                         floor_div(bonus, divisor) if family != 5 else 0)
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
