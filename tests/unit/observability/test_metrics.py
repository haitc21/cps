from cps.observability.metrics import MetricsRegistry


def test_metrics_render_only_counter_names_and_values() -> None:
    registry = MetricsRegistry()
    registry.increment("cps_operations_created_total", 2)
    registry.increment("cps_operations_created_total")
    assert registry.render_prometheus() == "cps_operations_created_total 3\n"
