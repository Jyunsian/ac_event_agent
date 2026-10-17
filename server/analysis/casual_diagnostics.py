"""Daily and acquisition-source diagnostics for V3; never a selection gate."""
from __future__ import annotations

import json
import os
from pathlib import Path

from server.analysis.connection import connect
from server.analysis.ingest import IngestError,file_hash


def build_casual_diagnostics(membership_path,target_path,user_path,destination,*,min_cell_users=20):
    membership_path,target_path,user_path,destination=map(Path,(membership_path,target_path,user_path,destination))
    hashes=(file_hash(membership_path),file_hash(target_path),file_hash(user_path))
    if type(min_cell_users) is not int or min_cell_users<2:raise IngestError("INVALID_V3_DIAGNOSTIC_CELL_SIZE")
    rows=[]
    with connect(config={"memory_limit":"256MB","threads":1,"preserve_insertion_order":False}) as c:
        c.read_parquet(str(membership_path)).create_view("memberships")
        c.read_parquet(str(target_path)).create_view("targets")
        c.read_parquet(str(user_path)).create_view("users")
        candidate_ids=[row[0] for row in c.execute("SELECT DISTINCT candidate_id FROM memberships ORDER BY candidate_id").fetchall()]
        # A single 1.3M-row join/group can consume the whole 256 MiB DuckDB
        # allowance before spilling. Candidate batches keep the exact same
        # aggregates and deterministic order with a bounded hash table.
        for offset in range(0,len(candidate_ids),100):
            batch=candidate_ids[offset:offset+100];placeholders=",".join("?" for _ in batch)
            for dimension,column in (("install_day","t.install_day"),("acquisition_source","u.acquisition_source")):
                values=c.execute(f"""SELECT m.candidate_id,CAST({column} AS VARCHAR) dimension_value,m.status,
                    count(*) users,count(*) FILTER (WHERE t.d7_revenue_usd IS NULL) unknown_revenue_users,
                    sum(t.d7_revenue_usd ORDER BY t.app_id,t.user_id) revenue_usd
                    FROM memberships m JOIN targets t USING(app_id,user_id) JOIN users u USING(app_id,user_id)
                    WHERE m.status IN ('triggered','untriggered') AND m.candidate_id IN ({placeholders})
                    GROUP BY ALL ORDER BY ALL""",batch).fetchall()
                grouped={}
                for candidate,value,status,users,unknown,revenue in values:
                    grouped.setdefault((candidate,value),{})[status]={"users":users,"unknown_revenue_users":unknown,
                        "revenue_usd":revenue if not unknown else None,"arpu_usd":revenue/users if not unknown and users else None}
                for (candidate,value),groups in sorted(grouped.items()):
                    hit=groups.get("triggered",{"users":0,"unknown_revenue_users":0,"revenue_usd":0,"arpu_usd":None})
                    miss=groups.get("untriggered",{"users":0,"unknown_revenue_users":0,"revenue_usd":0,"arpu_usd":None})
                    visible=min(hit["users"],miss["users"])>=min_cell_users and not hit["unknown_revenue_users"] and not miss["unknown_revenue_users"]
                    rows.append({"candidate_id":candidate,"dimension":dimension,"value":value,"triggered":hit,"untriggered":miss,
                        "comparison_status":"descriptive" if visible else "SMALL_OR_UNKNOWN_SAMPLE_HIDDEN",
                        "difference_usd":hit["arpu_usd"]-miss["arpu_usd"] if visible else None})
    rows.sort(key=lambda row:(row["candidate_id"],row["dimension"],row["value"]))
    if (file_hash(membership_path),file_hash(target_path),file_hash(user_path))!=hashes:raise IngestError("V3_DIAGNOSTIC_SOURCE_CHANGED")
    destination.mkdir(parents=True,exist_ok=False)
    payload={"schema_version":"3.0","stage":"diagnostics_v3","selection_role":"diagnostic_only",
             "min_cell_users":min_cell_users,"rows":rows,"source_hashes":{"memberships":hashes[0],"targets":hashes[1],"users":hashes[2]},
             "warning":"Descriptive historical association only; hidden cells never affect selection or Holm inference."}
    path=destination/"diagnostics.json"
    with path.open("x") as stream:json.dump(payload,stream,sort_keys=True,indent=2,allow_nan=False);stream.flush();os.fsync(stream.fileno())
    return {"name":"diagnostics","path":path.name,"sha256":file_hash(path),"size_bytes":path.stat().st_size,"rows":len(rows)}
