import re
from dataclasses import dataclass

_DIRECTION_MAP = {
    "w": "W", "west": "W",
    "e": "E", "east": "E",
    "n": "N", "north": "N",
    "s": "S", "south": "S"
}

_STREET_TYPE_MAP = {
    "st": "St", "street": "St",
    "ave": "Ave", "avenue": "Ave", "av": "Ave",
    "blvd": "Blvd", "boulevard": "Blvd",
    "ln": "Ln", "lane": "Ln",
    "ct": "Ct", "crt": "Ct", "court": "Ct", "courts": "Ct",
    "pl": "Pl", "place": "Pl",
    "rd": "Rd", "road": "Rd",
    "dr": "Dr", "drive": "Dr",
}

@dataclass
class ParsedBlock:
    block_key: str

@dataclass
class UnparseableAddress:
    raw_address: str
    reason: str     # "missing_house_number" | "unrecognized_format"
    tba: str

def _range_and_side(number: int) -> tuple[str, str]:
    range_str = f"{(number // 10) * 10}s"
    side = "odd" if number % 2 == 1 else "even" 

    return (range_str, side)

def derive_block_key(
    address: str,
    tba: str,
) -> ParsedBlock | UnparseableAddress:
    
    # 1. Strip noise suffix
    noise_pattern = r'\b(Attn|Attention|APT|Unit|Ground|Floor|Fl|Host|Suite|Ste|Basement|Bsmt|Lobby|Rear|Front)\b'
    clean = re.split(noise_pattern, address, flags=re.IGNORECASE)[0]
    clean = clean.strip().rstrip(',')

    # 2. Extract House Number
    tokens = clean.split()
    if not tokens:
        return UnparseableAddress(raw_address=address, reason="missing_house_number", tba=tba)
    
    try:
        house_number = int(tokens[0])
    except ValueError:
        return UnparseableAddress(raw_address=address, reason="missing_house_number", tba=tba)
    
    # 3. Identify the pattern and extract parts
    rest = tokens[1:]

    if not rest:
        return UnparseableAddress(raw_address=address, reason="unrecognized_format", tba=tba)
    
    # Pattern A - street (direction present)
    if rest[0].lower() in _DIRECTION_MAP:
        if len(rest) < 3:
            return UnparseableAddress(raw_address=address, reason="unrecognized_street_format", tba=tba)
        direction = _DIRECTION_MAP[rest[0].lower()]
        street_num = int(re.sub(r'(?i)(st|nd|rd|th)$', '', rest[1]))
        street_type_raw = rest[2].lower().rstrip('.')
        if street_type_raw not in _STREET_TYPE_MAP:
            return UnparseableAddress(raw_address=address, reason="unrecognized_street_format", tba=tba)
        street_type = _STREET_TYPE_MAP[street_type_raw]

    else:
        if len(rest) < 2:
            return UnparseableAddress(raw_address=address, reason="unrecognized_avenue_format", tba=tba)
        direction = None
        street_num = int(re.sub(r'(?i)(st|nd|rd|th)$', '', rest[0]))
        street_type_raw = rest[1].lower().rstrip('.')
        if street_type_raw not in _STREET_TYPE_MAP:
            return UnparseableAddress(raw_address=address, reason="unrecognized_avenue_format", tba=tba)
        street_type = _STREET_TYPE_MAP[street_type_raw]

    # 4. Assemble and return the block_key
    range_str, side = _range_and_side(house_number)

    if direction:
        block_key = f"{direction}_{street_num}_{street_type}_{range_str}_{side}"
    else:
        block_key = f"{street_num}_{street_type}_{range_str}_{side}"
    
    return ParsedBlock(block_key=block_key)