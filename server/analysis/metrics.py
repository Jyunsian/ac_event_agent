"""User-level descriptive metrics; qualification is separate from calculation."""
import math
from server.analysis.bootstrap import bootstrap_differences,METHOD
from collections import defaultdict
from statistics import fmean
from datetime import date, timedelta


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered)-1)*q
    low = int(position)
    high = min(low+1, len(ordered)-1)
    return ordered[low]+(ordered[high]-ordered[low])*(position-low)


def _mean(values):
    return fmean(values) if values else None


def summarize_users(rows, *, seed=42, bootstrap_replicates=1000, min_group_users=100,
                    frozen=False, split="exploration", quality_allowed=True):
    """Rows: one mature user each, with revenue_usd, install_day, triggered, delay_seconds.

    Missing revenue is not dropped: affected group means and comparisons are null.
    A common full-cohort draw preserves covariance when comparing hits to all users.
    Trigger-vs-nontrigger differences use stratified user draws from the two groups.
    """
    if type(seed) is not int or seed < 0 or type(bootstrap_replicates) is not int or not 100 <= bootstrap_replicates <= 10000:
        raise ValueError("INVALID_BOOTSTRAP_CONFIG")
    if type(min_group_users) is not int or min_group_users < 2 or split not in ("exploration", "holdout"):
        raise ValueError("INVALID_METRIC_CONFIG")
    rows = sorted(rows, key=lambda row: (row["app_id"], row["user_id"]))
    if len({(row["app_id"], row["user_id"]) for row in rows}) != len(rows):
        raise ValueError("DUPLICATE_METRIC_USER")
    for row in rows:
        revenue = row["revenue_usd"]
        if revenue is not None and (isinstance(revenue, bool) or not math.isfinite(revenue) or revenue < 0):
            raise ValueError("INVALID_METRIC_REVENUE")
        if type(row["triggered"]) is not bool:
            raise ValueError("INVALID_TRIGGER_FLAG")
        if row["triggered"] and (row["delay_seconds"] is None or not math.isfinite(row["delay_seconds"]) or row["delay_seconds"] < 0):
            raise ValueError("INVALID_TRIGGER_DELAY")
    hits = [row for row in rows if row["triggered"]]
    misses = [row for row in rows if not row["triggered"]]
    def group_summary(group):
        unknown = sum(row["revenue_usd"] is None for row in group)
        values = [row["revenue_usd"] for row in group]
        return {"users": len(group), "unknown_revenue_users": unknown,
                "revenue_usd": math.fsum(values) if group and not unknown else None,
                "arpu_usd": _mean(values) if not unknown else None}
    groups = {"all": group_summary(rows), "triggered": group_summary(hits), "untriggered": group_summary(misses)}
    hit_mean, miss_mean, all_mean = [groups[key]["arpu_usd"] for key in ("triggered", "untriggered", "all")]
    def difference(a, b):
        return a-b if a is not None and b is not None else None
    def ratio(a, b):
        return a/b if a is not None and b is not None and b != 0 else None
    intervals = {"triggered_minus_untriggered": None, "triggered_minus_all": None}
    valid = not groups["all"]["unknown_revenue_users"]
    if hits and misses and valid:
        hit_values = [row["revenue_usd"] for row in hits]
        miss_values = [row["revenue_usd"] for row in misses]
        differences, paired_differences = bootstrap_differences(hit_values,miss_values,
            seed=seed,replicates=bootstrap_replicates)
        for key, samples in (("triggered_minus_untriggered", differences), ("triggered_minus_all", paired_differences)):
            intervals[key] = {"lower": percentile(samples, .025), "upper": percentile(samples, .975),
                              "valid_replicates": len(samples), "requested_replicates": bootstrap_replicates}
    by_day = defaultdict(list)
    for row in rows:
        by_day[str(row["install_day"])].append(row)
    if by_day:
        first,last=map(date.fromisoformat,(min(by_day),max(by_day)))
        for offset in range((last-first).days+1):
            by_day.setdefault((first+timedelta(days=offset)).isoformat(),[])
    days = []
    for day, cohort in sorted(by_day.items()):
        day_hits = group_summary([row for row in cohort if row["triggered"]])
        day_misses = group_summary([row for row in cohort if not row["triggered"]])
        days.append({"install_day": day, "triggered": day_hits, "untriggered": day_misses,
                     'users':len(cohort),'triggered_users':day_hits['users'],
                     'coverage':day_hits['users']/len(cohort) if cohort else None,
                     'interpretation':'install_cohort_observed_not_platform_conversions',
                     "difference_usd": difference(day_hits["arpu_usd"], day_misses["arpu_usd"])})
    reasons = []
    if not frozen or split != "holdout":
        reasons.append("NOT_FROZEN_HOLDOUT_VALIDATION")
    if not quality_allowed:
        reasons.append("QUALITY_GATE_FAILED")
    if not valid:
        reasons.append("UNKNOWN_REVENUE")
    if len(hits) < min_group_users or len(misses) < min_group_users:
        reasons.append("INSUFFICIENT_GROUP_USERS")
    eligible_days = [day for day in days if day["triggered"]["users"] >= 20 and day["untriggered"]["users"] >= 20]
    if len(eligible_days) < 2:
        reasons.append("INSUFFICIENT_VALIDATION_DAYS")
    if any(day["difference_usd"] is None or day["difference_usd"] <= 0 for day in days if day['users']):
        reasons.append("UNSTABLE_OR_NONPOSITIVE_DAILY_DIFFERENCE")
    interval = intervals["triggered_minus_untriggered"]
    if interval is None or interval["lower"] <= 0:
        reasons.append("DIFFERENCE_INTERVAL_NOT_POSITIVE")
    delays = [row["delay_seconds"] for row in hits]
    return {"groups": groups, "coverage": len(hits)/len(rows) if rows else None,
            "delay_seconds": {"median": percentile(delays, .5), "p90": percentile(delays, .9)},
            "comparisons": {"triggered_minus_untriggered": difference(hit_mean, miss_mean),
                            "triggered_minus_all": difference(hit_mean, all_mean),
                            "triggered_over_untriggered": ratio(hit_mean, miss_mean),
                            "triggered_over_all": ratio(hit_mean, all_mean)},
            "bootstrap": {"seed": seed, "replicates": bootstrap_replicates, "intervals": intervals,
                          "method": METHOD},
            "days": days, "evidence_status": "historically_validated" if not reasons else
                ("insufficient_data" if any(reason.startswith("INSUFFICIENT") or reason == "UNKNOWN_REVENUE" for reason in reasons) else "exploratory"),
            "reasons": reasons, "warnings": ["Historical association is not campaign uplift.",
                "Descriptive intervals are not multiple-comparison corrected or causal evidence."]}
