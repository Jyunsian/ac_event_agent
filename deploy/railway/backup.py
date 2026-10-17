"""Daily database archive; retention applies only to this service's backup prefix."""
import hashlib,json,os,subprocess,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit,unquote
import boto3
from botocore.config import Config

def main():
    u=urlsplit(os.environ['DATABASE_URL'].replace('postgresql+psycopg://','postgresql://',1))
    env={**os.environ,'PGHOST':u.hostname,'PGPORT':str(u.port or 5432),'PGUSER':unquote(u.username),'PGPASSWORD':unquote(u.password),'PGDATABASE':u.path.lstrip('/')}
    s=boto3.client('s3',endpoint_url=os.environ['S3_ENDPOINT_URL'],region_name=os.environ['AWS_DEFAULT_REGION'],config=Config(signature_version='s3v4',s3={'addressing_style':'path'}))
    bucket=os.environ['S3_BUCKET'];now=datetime.now(timezone.utc);prefix='database-backups/production/'
    with tempfile.TemporaryDirectory() as work:
        path=Path(work)/'database.dump'
        subprocess.run(['pg_dump','--format=custom','--no-owner','--no-acl','--file',str(path)],env=env,check=True,capture_output=True)
        subprocess.run(['pg_restore','--list',str(path)],check=True,capture_output=True)
        digest=hashlib.sha256(path.read_bytes()).hexdigest();key=prefix+now.strftime('%Y%m%dT%H%M%SZ')+'.dump'
        with path.open('rb') as body:s.put_object(Bucket=bucket,Key=key,Body=body,IfNoneMatch='*',Metadata={'sha256':digest})
        assert s.head_object(Bucket=bucket,Key=key)['Metadata']['sha256']==digest
        for page in s.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=prefix):
            for obj in page.get('Contents',[]):
                if obj['LastModified']<now-timedelta(days=7):s.delete_object(Bucket=bucket,Key=obj['Key'])
        print(json.dumps({'status':'backed_up','key':key,'sha256':digest,'bytes':path.stat().st_size}))
if __name__=='__main__':main()
