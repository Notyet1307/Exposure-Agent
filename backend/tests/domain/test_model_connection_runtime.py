from app.integrations.model_connection_runtime import normalized_projection


def test_only_empty_docker_projection_is_equivalent() -> None:
    submitted = {
        "agents": [{"name": "worker", "driver": {"name": "docker", "docker": {}}}]
    }
    stored = {"agents": [{"name": "worker", "driver": {"name": "docker"}}]}
    assert normalized_projection(submitted) == stored
    assert "docker" in submitted["agents"][0]["driver"]
    changed = {
        "agents": [
            {
                "name": "worker",
                "driver": {"name": "docker", "docker": {"network": "other"}},
            }
        ]
    }
    assert normalized_projection(changed) != stored
    other_driver = {
        "agents": [{"name": "worker", "driver": {"name": "boxlite", "boxlite": {}}}]
    }
    assert normalized_projection(other_driver) != stored
