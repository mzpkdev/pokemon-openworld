# Repository instructions

## Product-owned C tests

Place Pokemon OpenWorld-owned C tests under `test/openworld/`. Do not add them to inherited RHH test directories or root test files unless an upstream test must change for compatibility.

Use `make TEST_TIER=openworld check` for the required product test tier. `make check` remains the explicit complete local suite, including inherited RHH coverage.
