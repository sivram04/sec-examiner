"""The judge: the fixed yardstick every version of the SEC Examiner is graded by.

The self-improving worker may change anything about itself except this package. Its files are
hash-sealed (MANIFEST.json); the harness refuses to grade if the seal doesn't match, so a
version cannot pass by editing its own tests, labels, splits or thresholds.
"""
