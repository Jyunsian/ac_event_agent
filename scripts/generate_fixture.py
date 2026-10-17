"""Generate synthetic CSV incrementally; never overwrite an existing destination."""
import argparse
import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

def generate(destination: Path, users: int, events: int, seed: int = 42, *, id_padding: int = 0, duplicate_every: int = 0):
    if users < 1 or events < 0:
        raise ValueError("users >= 1 and events >= 0 required")
    if type(id_padding) is not int or not 0 <= id_padding <= 4096 or type(duplicate_every) is not int or duplicate_every < 0 or duplicate_every == 1:
        raise ValueError('INVALID_STRESS_PROFILE')
    # Exclusive directory creation prevents source/fixture overwrite.
    destination.mkdir(parents=True, exist_ok=False)
    rng = random.Random(seed)
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    padding='x'*id_padding
    def stamp(value):
        return value.isoformat().replace("+00:00", "Z")
    with (destination / "users.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["app_id","user_id","installed_at","platform","country"])
        for i in range(users):
            writer.writerow(["synthetic",f"u{i}{padding}",stamp(origin + timedelta(days=i % 14)),
                             "android" if i % 2 else "ios","US" if i % 3 else "TW"])
    with (destination / "events.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["app_id","user_id","event_id","event_name","event_time",
                         "available_at","ad_format","revenue_usd"])
        for i in range(events):
            if duplicate_every and (i+1)%duplicate_every==0:
                writer.writerow(previous)
                continue
            # Leave at least one zero-event user when possible; skew half toward u0.
            uid = 0 if i % 2 == 0 else rng.randrange(max(1, users - 1))
            when = origin + timedelta(days=uid % 14, seconds=rng.randrange(8 * 86400))
            previous=["synthetic",f"u{uid}{padding}",f"e{i}{padding}","ad_impression",
                             stamp(when),stamp(when),"rewarded" if i % 3 else "interstitial",
                             f"{rng.randrange(0, 100) / 10000:.4f}"]
            writer.writerow(previous)
    (destination / "export.json").write_text(json.dumps({
        "schema_version":"1.0","complete_through":"2026-02-01T00:00:00Z",
        "exported_at":"2026-02-02T00:00:00Z","origin":"first_open",
        "id_policy":"one anonymous ID per synthetic install",
        "revenue_timing":"immediate","synthetic":True
    }, sort_keys=True, indent=2))
    (destination / "generator.json").write_text(json.dumps(
        {"synthetic":True,"users":users,"events":events,"seed":seed,
         "id_padding":id_padding,"duplicate_every":duplicate_every},sort_keys=True))
    return destination

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--users",type=int,default=1000)
    parser.add_argument("--events",type=int,default=10000)
    parser.add_argument("--seed",type=int,default=42)
    args = parser.parse_args()
    generate(args.output,args.users,args.events,args.seed)
    print(f"Synthetic data generated: {args.output} ({args.users} users, {args.events} events)")
