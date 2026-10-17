import pytest

from server.analysis.metrics import summarize_users


def row(identity, revenue, triggered, day="2026-01-01", delay=3600):
    return {"app_id": "synthetic", "user_id": str(identity), "revenue_usd": revenue,
            "triggered": triggered, "install_day": day, "delay_seconds": delay if triggered else None}


def test_independent_hand_metrics_and_zero_denominator():
    rows = [row("u1", .15, True, delay=18000), row("u2", 0, False), row("u3", .05, False),
            row("u4", .1, False), row("u5", .02, False)]
    result = summarize_users(rows, bootstrap_replicates=100)
    assert result["groups"]["all"]["users"] == 5
    assert result["groups"]["all"]["arpu_usd"] == pytest.approx(.064)
    assert result["groups"]["untriggered"]["arpu_usd"] == pytest.approx(.0425)
    assert result["coverage"] == .2
    assert result["delay_seconds"]["median"] == 18000
    assert result["comparisons"]["triggered_minus_all"] == pytest.approx(.086)
    assert result["evidence_status"] == "insufficient_data"
    zero = summarize_users([row(1, 0, True), row(2, 0, False)], bootstrap_replicates=100)
    assert zero["comparisons"]["triggered_over_all"] is None
    assert zero["bootstrap"]["intervals"]["triggered_minus_untriggered"]["lower"] == 0
    assert zero["evidence_status"] != "historically_validated"


def test_missing_revenue_retains_denominator_and_prevents_validation():
    result = summarize_users([row(1, None, True), row(2, 0, False)], bootstrap_replicates=100)
    assert result["groups"]["all"]["users"] == 2
    assert result["groups"]["all"]["arpu_usd"] is None
    assert result["bootstrap"]["intervals"]["triggered_minus_all"] is None
    assert "UNKNOWN_REVENUE" in result["reasons"]


def test_reproducible_and_qualifies_only_frozen_stable_holdout():
    rows = [row(f"{day}-{i}", 2 if i<50 else 0, i<50, day=day)
            for day in ("2026-01-01", "2026-01-02") for i in range(100)]
    result = summarize_users(rows, frozen=True, split="holdout")
    assert result == summarize_users(list(reversed(rows)), frozen=True, split="holdout")
    assert result["evidence_status"] == "historically_validated"
    assert result["bootstrap"]["intervals"]["triggered_minus_untriggered"]["lower"] == 2
    assert summarize_users(rows, bootstrap_replicates=100)["evidence_status"] != "historically_validated"
    assert summarize_users(rows, frozen=True, split="holdout", quality_allowed=False, bootstrap_replicates=100)["evidence_status"] != "historically_validated"
    for item in rows:
        if item["install_day"] == "2026-01-02":
            item["revenue_usd"] = 0 if item["triggered"] else 1
    unstable = summarize_users(rows, frozen=True, split="holdout", bootstrap_replicates=100)
    assert "UNSTABLE_OR_NONPOSITIVE_DAILY_DIFFERENCE" in unstable["reasons"]
    assert unstable["evidence_status"] != "historically_validated"


def test_duplicate_user_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_METRIC_USER"):
        summarize_users([row(1, 1, True), row(1, 1, True)])


def test_hit_all_bootstrap_preserves_overlap_covariance():
    # Exhaustive two-user draw possibilities: HH => difference 0; HM/MH => 1;
    # MM has no triggered mean and must be counted as an invalid replicate.
    result = summarize_users([row("hit", 2, True), row("miss", 0, False)])
    paired = result["bootstrap"]["intervals"]["triggered_minus_all"]
    assert paired["lower"] == 0 and paired["upper"] == 1
    assert 0 < paired["valid_replicates"] < paired["requested_replicates"]
    separate = result["bootstrap"]["intervals"]["triggered_minus_untriggered"]
    assert separate["lower"] == separate["upper"] == 2
