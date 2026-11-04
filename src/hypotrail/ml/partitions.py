"""The Partition roles of the temporal regression Track.

`train`, `dev` and `public_check` are protocol vocabulary (GLOSSARY: a Partition has
a fixed role in the protocol; Exposure), defined once, here. Everything else about
Partitions is the Workload's: how many there are besides these, and their date ranges.
Fitting is always on `train`; metrics and Comparisons are computed on `dev`;
`public_check` is touched only through the Exposure journal (SPEC section 2).
"""

TRAIN = "train"
DEV = "dev"
PUBLIC_CHECK = "public_check"
