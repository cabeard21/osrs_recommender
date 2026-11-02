def test_manual_evaluation_publishes_unknown_consumption_cost(make_content):
    from tests.gear.test_evaluation import fixed_context
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig

    service, snapshot, now = fixed_context(make_content)
    request = OptimizationRequest(roles=(RoleConfig(id="single", style="ranged"),), mode="owned")
    equipment = {"weapon": 1, "ammunition": 2}
    result = service.evaluate(snapshot, request, equipment, equipment, now=now)
    assert result["baseline"]["status"] == "valid"
    cost = result["baseline"]["running_cost"]
    assert cost["status"] == "unavailable"
    assert cost["gp_per_damage"] is None
