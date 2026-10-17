"""One configured connection entrypoint for every analysis stage."""
import duckdb
from server.resources import duck_config


def connect(*args,config=None,**kwargs):
    return duckdb.connect(*args,config=duck_config(config),**kwargs)
