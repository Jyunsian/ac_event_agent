"""Bounded, invocation-local reuse for identical full-cohort memberships.

The owner fixes user order, revenues, dates, sources and statistical rules for
one validation invocation. Keys are exact bitmaps, never hashes or rounded
metrics. Bare bitmaps never identify trigger delay or window-dependent evidence;
fixed-window evidence must use the explicit window_key domain instead.
"""
from collections import OrderedDict
import json
import math
import struct


class MembershipEvidenceMemo:
    def __init__(self,population,*,max_entries=256,max_bytes=32*1024*1024):
        self.population=population
        self.max_entries=max_entries
        self.max_bytes=max_bytes
        self.entries=OrderedDict()
        self.bytes=0

    def key(self,delays):
        bits=bytearray((self.population+7)//8)
        for index,delay in delays.items():
            if type(index) is not int or not 0<=index<self.population:
                raise ValueError('INVALID_METRIC_MEMBERSHIP')
            if delay is None or not math.isfinite(delay) or delay<0:
                raise ValueError('INVALID_TRIGGER_DELAY')
            bits[index//8]|=1<<(index%8)
        return bytes(bits)

    def get(self,key):
        value=self.entries.get(key)
        if value is None:return None
        self.entries.move_to_end(key)
        # Fresh nested objects: per-candidate status correction/checkpoint
        # mutation must never modify another candidate's evidence.
        return json.loads(value)

    def window_key(self,window_hours,membership):
        """Explicit fixed-window domain; never reuse a bitmap alone for revenue."""
        if type(window_hours) not in (int,float) or not math.isfinite(window_hours) or not 0<window_hours<=168:
            raise ValueError('INVALID_REVENUE_WINDOW')
        if type(membership) is not bytes or len(membership)!=(self.population+7)//8:
            raise ValueError('INVALID_METRIC_MEMBERSHIP')
        return b'W'+struct.pack('>d',window_hours)+membership

    def put(self,key,value):
        if self.max_entries<=0:return
        encoded=json.dumps(value,allow_nan=False,separators=(',',':')).encode()
        size=len(key)+len(encoded)
        if size>self.max_bytes:return
        if key in self.entries:
            self.bytes-=len(key)+len(self.entries.pop(key))
        while self.entries and (len(self.entries)>=self.max_entries or self.bytes+size>self.max_bytes):
            old_key,old_value=self.entries.popitem(last=False)
            self.bytes-=len(old_key)+len(old_value)
        self.entries[key]=encoded
        self.bytes+=size
