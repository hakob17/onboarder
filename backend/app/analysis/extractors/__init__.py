from .spring import SpringExtractor

EXTRACTORS = [SpringExtractor()]


def find_extractor(stack: str):
    return next((e for e in EXTRACTORS if e.matches(stack)), None)
