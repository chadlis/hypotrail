"""`report`: one self-contained HTML page per Study, rendered from the Study's records alone (SPEC §9, chadlis/hypotrail#85).

`gather` reads and verifies the records, `render` writes the page, `command` is the command: it records an Exposure
when the page shows `public_check` Items and publishes the page by an atomic rename. This package imports neither
Inspect, scikit-learn nor NumPy (ADR 0001, ENV-02).
"""
