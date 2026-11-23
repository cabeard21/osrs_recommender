# cython: boundscheck=False, wraparound=False
"""Numeric dominance for complete vector archives."""

from libc.math cimport isfinite
from libcpp.string cimport string
from libcpp.unordered_map cimport unordered_map
from libcpp.vector cimport vector

cdef extern from *:
    """
    #include <algorithm>
    #include <numeric>
    #include <vector>

    static void gear_vector_order(
        const double* data, size_t count, size_t width, std::vector<size_t>& order
    ) {
        order.resize(count);
        std::iota(order.begin(), order.end(), size_t(0));
        std::sort(order.begin(), order.end(), [=](size_t a, size_t b) {
            const double* left = data + a * width;
            const double* right = data + b * width;
            for (size_t i = 0; i < width; ++i) {
                if (left[i] != right[i]) return left[i] > right[i];
            }
            return a < b;
        });
    }
    """
    void gear_vector_order(const double*, size_t, size_t, vector[size_t]&) except + nogil


cdef bint dominates(const double* left, const double* right, size_t width) noexcept nogil:
    cdef size_t dimension
    cdef bint strict = False
    for dimension in range(width):
        if left[dimension] < right[dimension]:
            return False
        strict |= left[dimension] > right[dimension]
    return strict


cdef double finite(double value) except *:
    if not isfinite(value):
        raise ValueError("Objective vector values must be finite")
    return value


cdef class CapBaselines:
    """DPS baseline eligibility across feasible swap caps and the unrestricted cap."""

    cdef int unrestricted
    cdef vector[double] scores
    cdef list prefixes

    def __init__(self, int max_swaps):
        if not 0 <= max_swaps < 31:
            raise ValueError("Invalid maximum swap count")
        self.unrestricted = max_swaps + 1
        self.scores.resize(max_swaps + 2)
        self.prefixes = [None] * (max_swaps + 2)

    def update(self, cap, double score, tuple prefix):
        cdef int index = self.unrestricted if cap is None else cap
        if not 0 <= index <= self.unrestricted:
            raise ValueError("Invalid swap cap")
        self.scores[index] = finite(score)
        self.prefixes[index] = prefix

    def may_win(self, int maximum_actions, double score, candidate):
        cdef int index
        if maximum_actions < 0:
            raise ValueError("Invalid action count")
        finite(score)
        for index in range(min(maximum_actions, self.unrestricted), self.unrestricted + 1):
            previous = self.prefixes[index]
            if previous is None or score > self.scores[index]:
                return True
            if score == self.scores[index] and candidate.baseline_prefix <= previous:
                # Rich lexical comparison resolves any ties surviving the prefix.
                return True
        return False


def pareto_indices(const double[::1] values, int dimensions, cancelled=None):
    """Return exact skyline row handles in input order, retaining equal rows."""
    if not 1 <= dimensions <= 65 or values.shape[0] % dimensions:
        raise ValueError("Invalid frontier dimensions")
    if cancelled is not None and cancelled():
        raise ValueError("optimization_cancelled")
    if not values.shape[0]:
        return []
    cdef size_t count = values.shape[0] // dimensions
    cdef size_t i, end, pos, candidate, other, index
    cdef bint rejected
    cdef vector[size_t] order, skyline
    cdef vector[unsigned char] kept
    cdef const double* data = &values[0]
    for i in range(values.shape[0]):
        finite(data[i])
    with nogil:
        gear_vector_order(data, count, dimensions, order)
        kept.resize(count, 0)
    pos = 0
    while pos < count:
        if cancelled is not None and cancelled():
            raise ValueError("optimization_cancelled")
        end = min(pos + 128, count)
        with nogil:
            for index in range(pos, end):
                candidate = order[index]
                rejected = False
                # Lexicographic descending order puts all dominators before
                # this row, including when the leading coordinate is tied.
                for i in range(skyline.size()):
                    other = skyline[i]
                    if dominates(data + other * dimensions, data + candidate * dimensions,
                                 dimensions):
                        rejected = True
                        break
                if not rejected:
                    skyline.push_back(candidate)
                    kept[candidate] = 1
        pos = end
    return [i for i in range(count) if kept[i]]


cdef class ArchiveIndex:
    """Dense transient membership mirror for exact online dominance checks."""

    cdef size_t width
    cdef vector[double] data
    cdef vector[string] keys
    cdef unordered_map[string, size_t] offsets
    cdef list resource_prefixes

    def __init__(self, int dimensions):
        if not 1 <= dimensions <= 65:
            raise ValueError("Invalid frontier dimensions")
        self.width = dimensions
        self.resource_prefixes = []

    cdef void pack(self, object vector, double* row) except *:
        if len(vector) != self.width:
            raise ValueError("Invalid frontier dimensions")
        cdef size_t dimension
        for dimension in range(self.width):
            row[dimension] = finite(vector[dimension])

    cdef bint contains_dominator(self, const double* row) noexcept:
        cdef size_t index
        for index in range(self.keys.size()):
            if dominates(&self.data[index * self.width], row, self.width):
                return True
        return False

    def strictly_dominated(self, vector):
        cdef double row[65]
        self.pack(vector, row)
        return self.contains_dominator(row)

    def probe_update(self, vector):
        """Return the equal key and strict victims, or None if dominated."""
        cdef double row[65]
        self.pack(vector, row)
        cdef size_t index, dimension
        cdef const double* stored
        cdef bint better, worse
        equal = None
        victims = []
        for index in range(self.keys.size()):
            stored = &self.data[index * self.width]
            better = worse = False
            for dimension in range(self.width):
                better |= row[dimension] > stored[dimension]
                worse |= row[dimension] < stored[dimension]
                if better and worse:
                    break
            if worse:
                if not better:
                    return None
            elif better:
                victims.append(self.keys[index].decode())
            else:
                equal = self.keys[index].decode()
        return equal, victims

    cdef bint may_admit(self, const double* row, tuple prefix) except -1:
        cdef size_t index, dimension
        cdef const double* stored
        cdef bint strict
        for index in range(self.keys.size()):
            stored = &self.data[index * self.width]
            strict = False
            for dimension in range(self.width):
                if stored[dimension] < row[dimension]:
                    break
                strict |= stored[dimension] > row[dimension]
            else:
                previous = self.resource_prefixes[index]
                if strict or (previous is not None and previous < prefix):
                    return False
        return True

    def next_candidate(self, tuple variants, Py_ssize_t start, Py_ssize_t stop,
                       trip_loss=None, int risk_dimension=-1):
        """Find the first admissible option against the archive's current membership."""
        if not 0 <= start <= stop <= len(variants):
            raise ValueError("Invalid native candidate range")
        if trip_loss is not None and not 0 <= risk_dimension < self.width:
            raise ValueError("Invalid native risk dimension")
        cdef double row[65]
        cdef Py_ssize_t position
        for position in range(start, stop):
            variant = variants[position]
            if trip_loss is not None:
                loss = trip_loss((variant,))
                if loss is None:
                    continue
            try:
                self.pack(variant.values, row)
                if trip_loss is not None:
                    row[risk_dimension] = finite(-loss)
            except ValueError:
                return -1
            if not self.contains_dominator(row):
                return position
        return stop

    def insert(self, str identity, vector, tuple resource_prefix=None):
        cdef string key = identity.encode()
        cdef double row[65]
        cdef size_t index, dimension
        self.pack(vector, row)
        if not self.offsets.count(key):
            index = self.keys.size()
            self.offsets[key] = index
            self.keys.push_back(key)
            self.data.resize((index + 1) * self.width)
            self.resource_prefixes.append(resource_prefix)
        else:
            index = self.offsets[key]
            self.resource_prefixes[index] = resource_prefix
        for dimension in range(self.width):
            self.data[index * self.width + dimension] = row[dimension]

    cdef void erase(self, size_t index) except *:
        cdef size_t last = self.keys.size() - 1
        cdef size_t dimension
        self.offsets.erase(self.keys[index])
        if index != last:
            self.keys[index] = self.keys[last]
            self.offsets[self.keys[index]] = index
            self.resource_prefixes[index] = self.resource_prefixes[last]
            for dimension in range(self.width):
                self.data[index * self.width + dimension] = self.data[last * self.width + dimension]
        self.keys.pop_back()
        self.resource_prefixes.pop()
        self.data.resize(last * self.width)

    def discard(self, str identity):
        cdef string key = identity.encode()
        if self.offsets.count(key):
            self.erase(self.offsets[key])

    def remove_dominated(self, vector):
        cdef double row[65]
        cdef size_t index = 0
        self.pack(vector, row)
        while index < self.keys.size():
            if dominates(row, &self.data[index * self.width], self.width):
                self.erase(index)
            else:
                index += 1

    def __len__(self):
        return self.keys.size()


def admission_mask(tuple indexes, tuple values, tuple resource_prefix):
    """Check a complete numeric row across swap caps before allocating its report."""
    cdef size_t width = len(values)
    if not 1 <= width <= 65 or len(indexes) > 32:
        raise ValueError("Invalid frontier dimensions")
    cdef double row[65]
    cdef size_t dimension, cap
    cdef unsigned int mask = 0
    cdef ArchiveIndex index
    for dimension in range(width):
        row[dimension] = finite(values[dimension])
    for cap in range(len(indexes)):
        index = indexes[cap]
        if index is not None and index.width != width:
            raise ValueError("Invalid frontier dimensions")
        if index is None or index.may_admit(row, resource_prefix):
            mask |= (<unsigned int>1) << cap
    return mask


include "_option_product.pxi"
