"""Immutable PG/S3 checkpoints for descriptive batches, never partial verdicts."""
import json
import tempfile
from pathlib import Path

from server.db import fingerprint
from server.checkpoints import CheckpointError


class ValidationBatches:
    size=50

    def __init__(self, runner, frozen_sha256, candidate_ids, *, version='2.0'):
        self.runner=runner
        self.frozen_sha256=frozen_sha256
        self.candidate_ids=list(candidate_ids)
        if version not in ('2.0','3.0','4.0'):raise CheckpointError('INVALID_VALIDATION_BATCH_VERSION')
        self.version=version

    def _identity(self,index):
        if type(index) is not int or not 0<=index*self.size<len(self.candidate_ids):
            raise CheckpointError('INVALID_VALIDATION_BATCH')
        stage=f'validation_batch_{index:04d}'
        upstream={'frozen_sha256':self.frozen_sha256,'candidate_ids':self.candidate_ids[index*self.size:(index+1)*self.size]}
        identity=fingerprint({**self.runner.identity,'stage':stage,'version':self.version,'upstream':upstream})
        return stage,upstream,identity

    def _validate(self,payload,index):
        _,upstream,_=self._identity(index)
        if (payload.get('frozen_sha256')!=self.frozen_sha256 or payload.get('family_correction_complete') is not False
                or [r['row']['candidate_id'] for r in payload.get('entries',[])]!=upstream['candidate_ids']):
            raise CheckpointError('VALIDATION_BATCH_MISMATCH')
        for entry in payload['entries']:
            row=entry['row']
            if self.version=='4.0' and row.get('evidence_status')!='pending_family_correction':
                raise CheckpointError('PARTIAL_VALIDATION_VERDICT_FORBIDDEN')
            if row.get('evidence_status')=='historically_validated' or (row.get('metrics') or {}).get('evidence_status')=='historically_validated':
                raise CheckpointError('PARTIAL_VALIDATION_VERDICT_FORBIDDEN')
        return payload['entries']

    def load(self,index):
        stage,_,identity=self._identity(index)
        saved=self.runner.store.lookup(stage,self.version,identity)
        if saved is None:return None
        parent=Path(tempfile.mkdtemp(prefix=stage+'-',dir=self.runner.workspace))
        path=self.runner.store.restore(saved,parent/'result')
        return self._validate(json.loads((path/'manifest.json').read_text()),index)

    def save(self,index,entries):
        stage,upstream,_=self._identity(index)
        payload={'schema_version':self.version,'stage':stage,'frozen_sha256':self.frozen_sha256,
                 'family_correction_complete':False,'entries':entries}
        self._validate(payload,index)
        def build(path):
            path.mkdir(parents=True,exist_ok=False)
            with (path/'manifest.json').open('x') as stream:
                json.dump(payload,stream,sort_keys=True,allow_nan=False)
        path,_,_=self.runner.run(stage,self.version,build,upstream=upstream)
        return self._validate(json.loads((path/'manifest.json').read_text()),index)
