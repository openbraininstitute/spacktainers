# Spackitor

Spackitor is the Spack Janitor - this is the tool that cleans up the build cache. It can do so in two ways:

  1. Either you give it a (list of) spack environment file(s). In that case it will clean anything that is not specified in them and that is older than the specified time.
  2. If you don't give it (a) spack environment file(s), it will simply remove anything older than the specified time.

Anything that depends on a deleted object will also be deleted.
Spackitor cleanup is simply a matter of removing S3 objects (both the `.spack` object and the `.sig` object). The pipeline itself takes care of updating the index file.


## The `scripts` dir

Scripts in this directory are written as helpers and may or may not be documented. Use at your own risk and make sure to read and edit them for your use case!

### s3.py

Some useful operations I've found myself doing on the buckets.

```python
from s3 import browser
```

The browser object has an s3_client property, saving you the trouble of creating it yourself, and various handy functions for bucket cleanup.
Make sure you have `~/.ssh/buildcache_keys` with two lines: first line is the access key, second line is the secret key.
Most methods should have a docstring that is clear enough.

As an example, we'll purge all the `dev` versions of `py-bbp-workflow` in the production bucket. Note that after an operation like this, you *must* rebuild the cache (see below).

```python
In [1]: from s3 import browser
In [2]: package_objects = browser.find_package_objects("py-bbp-workflow", bucket="spack-build-cache")
In [3]: browser.s3_client.delete_objects(Bucket="spack-build-cache", Delete={"Objects": [{"Key": x["Key"]} for x in package_objects if ".dev" in x["Key"]]})
Out[3]:
{'ResponseMetadata': {'RequestId': '1694685187482502',
  'HostId': '12763010',
  'HTTPStatusCode': 200,
  'HTTPHeaders': {'date': 'Thu, 14 Sep 2023 12:48:31 GMT',
   'content-type': 'application/xml',
   'transfer-encoding': 'chunked',
   'connection': 'keep-alive',
   'server': 'StorageGRID/11.6.0.7',
   'x-amz-request-id': '1694685187482502',
   'x-amz-id-2': '12763010',
   'x-ntap-sg-trace-id': '85e822f5e0207319'},
  'RetryAttempts': 0},
 'Deleted': [{'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-6unhycokwejx7iblm4z3lhi5vxxiq5xj.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-oc76gh2y3mt6impaal7vc222uxdrfvol.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-xemjhuhcwrc65aweq6zuim3gxwropzzw.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-ajsokhwhsb75v4zkpj2fjd75hzf5ha2q.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-amobtu74jahfcsnkzokt4hlohyxfepj2.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-f3fe5avblvdap7x35toopdrwoojs2wb2.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-osibvkeqa2exoxeltfbjtefk7dz256ix.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-xi6vf4zrpmjl2bt76zlu22iq4sr4gdmp.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev1-gzdxkjmp2y3wqhnyyhltrczlgci3u6pd.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev2-k2tiw5alqu2jovbhrikwb4liaa5avs3z.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev2-meyyfo45s27ztuuyolv5w5crfbwlytu4.spec.json.sig'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev2/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-6unhycokwejx7iblm4z3lhi5vxxiq5xj.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev2/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-oc76gh2y3mt6impaal7vc222uxdrfvol.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev2/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev2-xemjhuhcwrc65aweq6zuim3gxwropzzw.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev3/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-ajsokhwhsb75v4zkpj2fjd75hzf5ha2q.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev3/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-amobtu74jahfcsnkzokt4hlohyxfepj2.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev3/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-f3fe5avblvdap7x35toopdrwoojs2wb2.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev3/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-osibvkeqa2exoxeltfbjtefk7dz256ix.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.32.dev3/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.32.dev3-xi6vf4zrpmjl2bt76zlu22iq4sr4gdmp.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.33.dev1/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev1-gzdxkjmp2y3wqhnyyhltrczlgci3u6pd.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.33.dev2/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev2-k2tiw5alqu2jovbhrikwb4liaa5avs3z.spack'},
  {'Key': 'build_cache/linux-ubuntu22.04-x86_64_v3/gcc-12.3.0/py-bbp-workflow-3.1.33.dev2/linux-ubuntu22.04-x86_64_v3-gcc-12.3.0-py-bbp-workflow-3.1.33.dev2-meyyfo45s27ztuuyolv5w5crfbwlytu4.spack'}]}
```


---
A note on rebuilding the index.
You don't have to do both, just the one which is relevant. You need:
  * AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY shell variables
  * The bucket configured as a spack mirror (otherwise spack tries to go to Amazon S3 instead of our own endpoint)
  * This git diff:

```
diff --git a/lib/spack/spack/binary_distribution.py b/lib/spack/spack/binary_distribution.py
index 8ceeeea738..1d4020a66f 100644
--- a/lib/spack/spack/binary_distribution.py
+++ b/lib/spack/spack/binary_distribution.py
@@ -986,6 +986,8 @@ def file_read_method(file_path):
     sync_command_args = [
         "s3",
         "sync",
+        "--endpoint-url",
+        "https://bbpobjectstorage.epfl.ch",
         "--exclude",
         "*",
         "--include",
```

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
spack mirror add --s3-endpoint-url https://bbpobjectstorage.epfl.ch bbpS3 s3://spack-build-cache  # if not done yet
spack mirror add --s3-endpoint-url https://bbpobjectstorage.epfl.ch bbpS3-dev s3://spack-build-cache-dev  # if not done yet
spack buildcache update-index -d s3://spack-build-cache
spack buildcache update-index -d s3://spack-build-cache-dev
```
---

### purge_dependents.py

This script will purge a package and everything that depends on it from the specified cache. Don't forget to rebuild the index afterwards! (see the note above)

It's also advisable to run the spack-cacher pipeline from `main` after doing this, as a lot of packages will have to be rebuilt.

It uses the `s3.py` script under the hood, so refer to the documentation higher in this file on how to specify credentials.
