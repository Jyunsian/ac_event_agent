"""Reuse only exact inputs; a cache hit still verifies every S3 object."""
import json
from sqlalchemy import text
from server.db import fingerprint
from server.jobs import JobQueue

DEPENDENCIES={'normalized':[],'quality':['normalized'],'targets':['normalized'],
              'exploration':['normalized','targets'],'features':['normalized']}


def stage_identity(stage,dataset,config,calculation_version,upstream):
    if stage not in DEPENDENCIES:return None
    evidence={name:[{'path':entry['path'],'sha256':entry['object']['sha256']} for entry in upstream[name]['files']]
              for name in DEPENDENCIES[stage]}
    return {'cache_version':'1.0','stage':stage,'stage_version':'1.0',
            'dataset_fingerprint':dataset['fingerprint'],'mapping_sha256':fingerprint(dataset['mapping']),
            'calculation_version':calculation_version,'seed':config['seed'],
            'split_definition':{'exploration_fraction':config['exploration_fraction'],'export_metadata':dataset['export_metadata']},
            'feature_definition':{'version':'1.0','windows_hours':config['windows_hours'] if stage in ('features','exploration') else None},
            'upstream':evidence}


class StageCache:
    def __init__(self,engine,runner,dataset,config,version,allow_reuse):
        self.engine,self.runner,self.dataset,self.config,self.version=engine,runner,dataset,config,version
        self.allow_reuse=allow_reuse;self.audit=[]

    def run(self,name,builder,saved,upstream):
        identity=stage_identity(name,self.dataset,self.config,self.version,saved)
        if identity is None:return self.runner.run(name,'1.0',builder,upstream=upstream)
        key=fingerprint(identity);entry=None
        if self.allow_reuse:
            with self.engine.connect() as c:
                entry=c.execute(text('''SELECT k.source_run_id,k.identity,s.manifest FROM analysis_stage_cache k
                  JOIN stage_checkpoints s ON s.run_id=k.source_run_id AND s.stage=k.stage
                    AND s.stage_version=k.stage_version AND s.input_sha256=k.input_sha256
                  WHERE k.cache_key=:key'''),{'key':key}).mappings().one_or_none()
            if entry and entry['identity']!=identity:raise ValueError('CACHE_IDENTITY_MISMATCH')
        def build(output):
            if entry:
                # restore enforces relative paths, root commit marker and checksums.
                self.runner.store.restore(entry['manifest'],output)
            else:builder(output)
        path,manifest,mode=self.runner.run(name,'1.0',build,upstream=upstream)
        with self.engine.begin() as c:
            JobQueue(self.engine)._owned(c,self.runner.store.lease)
            c.execute(text('''INSERT INTO analysis_stage_cache(cache_key,identity,source_run_id,stage,stage_version,input_sha256)
              VALUES(:key,CAST(:identity AS jsonb),:run,:stage,'1.0',:input) ON CONFLICT(cache_key) DO NOTHING'''),
              {'key':key,'identity':json.dumps(identity),'run':self.runner.store.lease.run_id,'stage':name,'input':manifest['input_sha256']})
        outcome='restored' if mode=='restored' else 'cached' if entry else 'computed'
        self.audit.append({'stage':name,'cache_key':key,'mode':outcome,
                           'source_run_id':str(entry['source_run_id']) if entry and mode!='restored' else str(self.runner.store.lease.run_id),
                           'reason':'exact_inputs_verified' if outcome=='cached' else 'own_checkpoint_verified' if outcome=='restored' else 'no_exact_cache_entry' if self.allow_reuse else 'baseline_computation'})
        return path,manifest,outcome
