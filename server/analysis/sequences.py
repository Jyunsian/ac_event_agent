"""Greedy, non-overlapping two-step sequences over canonical event resolution."""
from collections import deque
from itertools import groupby


def first_sequence_trigger(events, steps, max_gap_seconds, repeats):
    """Consume time-sorted (time, source_sequence, event_name, event_id) records.

    At a tied timestamp, ordering is usable only if every relevant event has a
    distinct non-null sequence. Otherwise B may complete an older A, but events
    in that timestamp cannot establish A-before-B. Completion discards all
    starts up to that end, so pairs never overlap or reuse an event.
    """
    starts = deque()
    completed = 0
    previous_time = None
    for timestamp, group in groupby(events, key=lambda event: event[0]):
        if previous_time is not None and timestamp < previous_time:
            raise ValueError("SEQUENCE_INPUT_NOT_SORTED")
        previous_time = timestamp
        bucket = list(group)
        while starts and (timestamp-starts[0]).total_seconds() > max_gap_seconds:
            starts.popleft()
        sequences = [event[1] for event in bucket]
        reliable = all(sequence is not None for sequence in sequences) and len(set(sequences)) == len(sequences)
        if reliable:
            for _, _, name, _ in sorted(bucket, key=lambda event: event[1]):
                if name == steps[1] and starts:
                    completed += 1
                    starts.clear()
                    if completed == repeats:
                        return timestamp
                    continue  # A=B cannot reuse this completed end as a new start.
                if name == steps[0]:
                    starts.append(timestamp)
        else:
            ends = sum(event[2] == steps[1] for event in bucket)
            consumed_end = bool(ends and starts)
            if consumed_end:
                completed += 1
                starts.clear()
                if completed == repeats:
                    return timestamp
            # Starts tied with a completed end cannot begin another non-overlapping
            # pair: no reliable ordering proves that they came after that end.
            if not consumed_end:
                starts.extend(timestamp for event in bucket if event[2] == steps[0])
    return None
