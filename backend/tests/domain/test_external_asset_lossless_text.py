from app.domain.external_asset_models import external_record_projections


def test_external_record_projections_preserve_nul_and_ignore_non_strings() -> None:
    fields = {
        "root_domain": "root\0example.test",
        "subdomain": "api\0edge.example.test",
        "status": "va\0lid",
        "banner": "synthetic\0banner",
        "nested": {"tag": "synthetic\0tag"},
    }

    assert external_record_projections(fields) == {
        "root_domain_segments": ["root", "example.test"],
        "subdomain_segments": ["api", "edge.example.test"],
        "status_segments": ["va", "lid"],
    }
    assert fields["banner"] == "synthetic\0banner"
    assert fields["nested"] == {"tag": "synthetic\0tag"}


def test_external_record_projections_keep_missing_and_null_as_null() -> None:
    assert external_record_projections({"root_domain": None, "status": 1}) == {
        "root_domain_segments": None,
        "subdomain_segments": None,
        "status_segments": None,
    }
