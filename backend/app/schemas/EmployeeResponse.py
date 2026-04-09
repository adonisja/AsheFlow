def EmployeeResponse(id: UUID, name: str, discord_id: str, role: str, is_active: bool) -> dict:
    return dict(id=id, name=name, discord_id=discord_id, role=role, is_active=is_active)