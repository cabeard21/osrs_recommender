"""Pack and scan bounded Cartesian option products in Python product order."""

from cpython.ref cimport PyObject, Py_INCREF
from cpython.pyport cimport PY_SSIZE_T_MAX
from cpython.tuple cimport PyTuple_New, PyTuple_SET_ITEM
from libc.math cimport fabs, isnan
from libc.string cimport memcpy


cdef struct ProductSum:
    double hi
    double lo


cdef inline void product_add(ProductSum* acc, double term) noexcept:
    # Match CPython 3.12 sum(float) and the role order used by VectorSearch.
    cdef double total = acc.hi + term
    if fabs(acc.hi) >= fabs(term):
        acc.lo += (acc.hi - total) + term
    else:
        acc.lo += (term - total) + acc.hi
    acc.hi = total


cdef inline double product_total(ProductSum acc) noexcept:
    return acc.hi + acc.lo if acc.lo and isfinite(acc.lo) else acc.hi


cdef struct CostTerm:
    double spend
    double damage
    bint known


cdef CostTerm pack_cost(object cost, double weight, double weighted_dps) except *:
    cdef CostTerm term = CostTerm(0.0, 0.0, True)
    cdef double hourly
    # Absent costs are excluded entirely by VectorSearch.weighted. A present
    # unavailable cost instead makes the whole combination unpriced.
    if cost is not None and weight > 0:
        term.known = cost.status == "known" and cost.gp_per_hour is not None
        if term.known:
            hourly = cost.gp_per_hour
            term.known = isfinite(hourly) and hourly >= 0
            term.spend = weight * hourly / 3600.0
            term.damage = weighted_dps
    return term


cdef class PackedRole:
    """Immutable numeric alternatives and their owning OptionVariant tuple."""

    cdef tuple variants
    cdef vector[double] coordinates
    cdef vector[CostTerm] costs
    cdef int width, cost_index
    cdef double weight
    cdef bint special

    def __cinit__(self, tuple variants not None, double weight, bint special, int width,
                  int cost_index):
        if not 1 <= width <= 65 or (cost_index != -1 and not 1 <= cost_index < width):
            raise ValueError("Invalid option dimensions")
        if not isfinite(weight) or weight < 0:
            raise ValueError("Invalid option weight")
        if len(variants) > PY_SSIZE_T_MAX // width:
            raise ValueError("Too many options")
        self.variants = variants
        self.width = width
        self.cost_index = cost_index
        self.weight = weight
        self.special = special
        self.coordinates.resize(len(variants) * width)
        if cost_index >= 0:
            self.costs.resize(len(variants))
        cdef Py_ssize_t i, dim
        cdef double value
        for i, option in enumerate(variants):
            values = option.values
            if len(values) != width:
                raise ValueError("Mismatched option dimensions")
            for dim in range(width):
                value = values[dim]
                self.coordinates[i * width + dim] = value if special else value * weight
            if cost_index >= 0 and not special:
                self.costs[i] = pack_cost(option.cost, weight, self.coordinates[i * width])


cdef struct RoleView:
    Py_ssize_t length
    const double* coordinates
    const CostTerm* costs
    bint special


cdef struct ProductIndexes:
    PyObject* archives[32]
    int count


cdef enum RowKind:
    PRICED
    UNPRICED
    UNSUPPORTED


cdef RowKind finish_cost(double* row, int cost_index, bint known, double spend,
                         double damage) noexcept:
    if not known or damage <= 0:
        return UNPRICED
    if not isfinite(spend) or not isfinite(damage):
        return UNSUPPORTED
    row[cost_index] = -spend / damage
    return PRICED


cdef class OptionProduct:
    """Stream weighted rows against the live cap archives, stopping at each survivor."""

    cdef tuple packed_roles
    cdef readonly object size
    cdef RoleView roles[4]
    cdef int role_count, width, cost_index, risk_index
    cdef double total_weight
    cdef bint direct_row, unit_pair

    def __cinit__(self, tuple packed_roles not None, int cost_index, int risk_index):
        if not 1 <= len(packed_roles) <= 4:
            raise ValueError("Expected one to four option roles")
        cdef int i
        cdef PackedRole role
        cdef ProductSum weights = ProductSum(0.0, 0.0)
        cdef bint all_special = True
        self.packed_roles = packed_roles  # owns every pointer in roles
        self.role_count = len(packed_roles)
        self.cost_index, self.risk_index = cost_index, risk_index
        self.size = 1
        self.unit_pair = len(packed_roles) == 2 and risk_index == -1 and cost_index >= 1
        for i in range(self.role_count):
            role = packed_roles[i]
            if role is None:
                raise ValueError("Missing packed role")
            if i == 0:
                self.width = role.width
            if role.width != self.width or role.cost_index != cost_index:
                raise ValueError("Incompatible packed roles")
            self.roles[i].length = len(role.variants)
            self.size = self.size * len(role.variants)
            self.roles[i].coordinates = role.coordinates.data()
            self.roles[i].costs = role.costs.data()
            self.roles[i].special = role.special
            if not role.special:
                all_special = False
                product_add(&weights, role.weight)
            self.unit_pair &= not role.special and role.weight == 1.0 and role.width == 3
        if risk_index != -1 and (not 1 <= risk_index < self.width or risk_index == cost_index):
            raise ValueError("Invalid option risk dimension")
        self.total_weight = product_total(weights) or 1.0
        self.direct_row = all_special or (self.role_count == 1 and cost_index == -1 and weights.hi == 1)

    cdef RowKind pair_row(self, Py_ssize_t* digits, double* row) noexcept:
        # For two finite terms the final CPython sum rounds to their ordinary
        # binary64 sum. In the common GP/prayer pair only two coordinates survive.
        cdef int other = 3 - self.cost_index
        cdef const double* left = self.roles[0].coordinates + digits[0] * 3
        cdef const double* right = self.roles[1].coordinates + digits[1] * 3
        cdef CostTerm a = self.roles[0].costs[digits[0]]
        cdef CostTerm b = self.roles[1].costs[digits[1]]
        row[0] = (left[0] + right[0]) / 2.0
        row[other] = (left[other] + right[other]) / 2.0
        return finish_cost(row, self.cost_index, a.known and b.known, a.spend + b.spend,
                           a.damage + b.damage)

    cdef RowKind weighted_row(self, Py_ssize_t* digits, double* row) noexcept:
        cdef ProductSum coordinates[65]
        cdef ProductSum spend = ProductSum(0.0, 0.0)
        cdef ProductSum damage = ProductSum(0.0, 0.0)
        cdef int i, dim
        cdef bint known = True
        cdef CostTerm cost
        cdef const double* values
        if self.direct_row:
            values = self.roles[0].coordinates + digits[0] * self.width
            memcpy(row, values, self.width * sizeof(double))
            return UNPRICED if self.cost_index >= 0 else PRICED
        for dim in range(self.width):
            coordinates[dim] = ProductSum(0.0, 0.0)
        for i in range(self.role_count):
            if self.roles[i].special:
                continue
            values = self.roles[i].coordinates + digits[i] * self.width
            for dim in range(self.width):
                product_add(&coordinates[dim], values[dim])
            if self.cost_index >= 0:
                cost = self.roles[i].costs[digits[i]]
                known &= cost.known
                product_add(&spend, cost.spend)
                product_add(&damage, cost.damage)
        for dim in range(self.width):
            row[dim] = product_total(coordinates[dim]) / self.total_weight
        if self.cost_index >= 0:
            return finish_cost(row, self.cost_index, known, product_total(spend),
                               product_total(damage))
        return PRICED

    cdef void decode(self, object start, Py_ssize_t* digits) except *:
        cdef int i
        cdef Py_ssize_t cursor
        if start <= PY_SSIZE_T_MAX:
            cursor = start
            for i in range(self.role_count - 1, -1, -1):
                digits[i] = cursor % self.roles[i].length
                cursor = cursor // self.roles[i].length
        else:
            for i in range(self.role_count - 1, -1, -1):
                start, digits[i] = divmod(start, self.roles[i].length)

    cdef void advance(self, Py_ssize_t* digits) noexcept:
        cdef int i
        for i in range(self.role_count - 1, -1, -1):
            digits[i] += 1
            if digits[i] < self.roles[i].length:
                break
            digits[i] = 0

    cdef tuple selection(self, Py_ssize_t* digits):
        # Only surviving rows (or Python whole-trip evaluations) need objects.
        cdef tuple selected = PyTuple_New(self.role_count)
        cdef int i
        for i in range(self.role_count):
            option = (<PackedRole>self.packed_roles[i]).variants[digits[i]]
            Py_INCREF(option)  # The new tuple steals this reference.
            PyTuple_SET_ITEM(selected, i, option)
        return selected

    cdef bint survives(self, double* row, ProductIndexes* indexes) noexcept:
        cdef int i
        for i in range(indexes.count):
            if not (<ArchiveIndex><object>indexes.archives[i]).contains_dominator(row):
                return True
        return False

    cdef tuple scan_chunk(self, Py_ssize_t* digits, Py_ssize_t count, ProductIndexes* indexes,
                          double floor, object trip_loss, object cancelled):
        cdef double row[65]
        cdef RowKind kind
        cdef Py_ssize_t i
        cdef int dim
        cdef bint admit
        for i in range(count):
            if cancelled is not None and cancelled():
                return i, None, "cancelled"
            kind = self.pair_row(digits, row) if self.unit_pair else self.weighted_row(digits, row)
            selected = None
            if trip_loss is not None:
                selected = self.selection(digits)
                loss = trip_loss(selected)
                if loss is None:
                    self.advance(digits)
                    continue
                if kind == PRICED:
                    try:
                        row[self.risk_index] = -loss
                    except (OverflowError, TypeError, ValueError):
                        return i, None, "reference"
                    if -row[self.risk_index] != loss:
                        return i, None, "reference"
            if kind == UNSUPPORTED:
                return i, None, "reference"
            for dim in range(1 if kind == UNPRICED else self.width):
                if not isfinite(row[dim]):
                    return i, None, "reference"
            admit = row[0] >= floor if kind == UNPRICED else self.survives(row, indexes)
            if admit:
                return i + 1, selected if selected is not None else self.selection(digits), None
            self.advance(digits)
        return count, None, None

    def scan(self, start, count, tuple indices not None, double baseline_floor, trip_loss=None,
             cancelled=None):
        """Return consumed count, first surviving selection, and optional stop reason."""
        # Only builtin integer arithmetic may supply the offsets for our raw arrays.
        if type(start) is not int or type(count) is not int:
            raise ValueError("Invalid option cursor")
        if not 0 <= start <= self.size or count < 0:
            raise ValueError("Invalid option range")
        if len(indices) > 32 or isnan(baseline_floor):
            raise ValueError("Invalid option archive or baseline")
        if trip_loss is not None and (self.risk_index == -1 or not callable(trip_loss)):
            raise ValueError("Invalid trip loss callback")
        if cancelled is not None and not callable(cancelled):
            raise ValueError("Invalid cancellation callback")
        cdef ProductIndexes indexes
        cdef ArchiveIndex archive
        cdef int cap
        cdef bint missing_index = False
        indexes.count = len(indices)
        for cap in range(indexes.count):
            archive = indices[cap]
            if archive is None:
                missing_index = True
            elif archive.width != self.width:
                raise ValueError("Invalid archive width")
            indexes.archives[cap] = <PyObject*>archive
        remaining = min(count, self.size - start)
        if not remaining:
            return 0, None, None
        if missing_index:
            return 0, None, "reference"
        cdef Py_ssize_t digits[4]
        self.decode(start, digits)
        consumed = 0
        while remaining:
            used, selected, status = self.scan_chunk(digits, min(remaining, PY_SSIZE_T_MAX),
                                                     &indexes, baseline_floor, trip_loss, cancelled)
            consumed += used
            if selected is not None or status is not None:
                return consumed, selected, status
            remaining -= used
        return consumed, None, None
