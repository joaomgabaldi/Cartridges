# The upstream `Location` class (candidate roots for a source's files, resolved
# into a GSettings key) lived here. The fork's only source, the shortcuts one,
# reads its folder straight from the schema and never had a location, so the
# class was dead and is gone. The exception stays because the importer still
# catches it around `iter(source)`: a source that cannot find its files skips
# the scan instead of reporting every game as removed.


class UnresolvableLocationError(Exception):
    def __init__(self, optional: bool = False):
        self.optional = optional
