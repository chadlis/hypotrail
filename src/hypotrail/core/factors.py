"""The factors a request can declare as the intentional difference of an agent Comparison (`compare --factor`).

Standard library only, so the command line can offer them without loading the Comparison.
"""

DEFAULT_FACTOR = "configuration"
FACTORS = (DEFAULT_FACTOR, "repeats", "tools", "model", "budgets")
