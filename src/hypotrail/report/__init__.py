"""`report`: one self-contained HTML page per Study, rendered from the Study's records and, for a regression Study, the data profile
the command hands over (SPEC §9, chadlis/hypotrail#85).

`gather` reads and verifies the records, `render` writes the page (`render_profile` its Data profile section), `command` is the
command: it records an Exposure when the page shows `public_check` Items and publishes the page by an atomic rename. This package imports neither
Inspect, scikit-learn nor NumPy (ADR 0001, ENV-02).
"""
