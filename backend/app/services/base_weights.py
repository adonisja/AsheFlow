def get_base_weights(truck_list: list) -> dict:
    """Compute equal base weights for a list of trucks.

    Args:
        truck_list: List of truck IDs to weight.

    Returns:
        A dict mapping each truck ID to ``1 / len(truck_list)``.

    Raises:
        ValueError: If ``truck_list`` is empty.
    """
    if not truck_list:
        raise ValueError("Truck list cannot be empty")

    return {truck_id: 1/len(truck_list) for truck_id in truck_list}