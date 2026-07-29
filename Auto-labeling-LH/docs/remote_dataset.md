# Remote LH Dataset

The configured server is an SFTP-backed Synology NAS, not a SQL database.

- Server: `10.4.10.15:2003`
- SFTP root: `/homes/LH_Dataset`
- NAS filesystem path: `/volume1/homes/LH_Dataset`
- Local cache: `temp/remote_dataset_cache`

Credentials are stored in `config/local.yaml`. That file is ignored by git.

Check the connection:

```powershell
python tools/remote_dataset_sync.py status
```

Download lightweight metadata:

```powershell
python tools/remote_dataset_sync.py pull LH_data_all_sensor_annotations --small-only
```

Download a complete selected capture:

```powershell
python tools/remote_dataset_sync.py pull LH_data_all_sensor/4_30/<capture_name>
```

Upload one cached file:

```powershell
python tools/remote_dataset_sync.py push LH_data_all_sensor_annotations_depth/<relative_path>
```

Remote synchronization is explicit because the remote depth directory is
currently empty and remote annotations currently contain only `4_29`.
Automatically replacing local roots would hide local annotations and depth
results.
