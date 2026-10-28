# Studio API

Start with a random ANIMODE_API_TOKEN (at least 24 characters) in .env:

~~~bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -m animode.api
~~~

Default binding: 127.0.0.1:8000. Use one worker. Every endpoint requires Authorization: Bearer TOKEN.
Set the matching secret in your shell before using curl; the shell does not automatically read .env.

| Method | Route | Purpose |
|---|---|---|
| GET | /v1/health | Service health, not model readiness |
| GET | /v1/openapi.json | Authenticated API specification |
| POST | /v1/projects | Raw video body → queued analysis |
| GET | /v1/tasks/{id} | Task state and resulting project ID |
| GET | /v1/projects/{id} | Script, characters and revision |
| PUT | /v1/projects/{id}/dialogue | Validated script/time/speaker edits |
| PUT | /v1/projects/{id}/voices/{speaker} | Character name/style |
| POST | /v1/projects/{id}/render | Queue render of an expected revision |
| GET | /v1/projects/{id}/exports/{kind} | video/master/srt/vtt/csv/bundle |

Custom reference audio and individual previews are Studio UI/Python features; API voice edits
change metadata only. The API never accepts arbitrary local file paths.

## Analyze

~~~bash
curl --fail-with-body \
  -H "Authorization: Bearer $ANIMODE_API_TOKEN" \
  -H 'Content-Type: video/mp4' --data-binary @anime.mp4 \
  'http://127.0.0.1:8000/v1/projects?source_language=ja&extension=mp4&speakers=0'
~~~

A 202 response returns task_id. Poll /v1/tasks/TASK_ID; completion supplies project_id.
Upload limit: 1 GiB. Analysis rejects videos over 30 minutes. Media validation happens inside
the worker, and server-generated filenames prevent client path injection.

## Edit

PUT every existing row to /v1/projects/PROJECT_ID/dialogue. Retain IDs. String columns are:
ID, speaker, start seconds, end seconds, source, Hindi.

~~~json
{"revision":0,"rows":[["0","SPEAKER_00","0.2","2.6","Hello, my friend.","नमस्ते, मेरे दोस्त।"]]}
~~~

Response revisions increase after each edit. Unknown speakers, invalid times, changed IDs and
overlapping slots are rejected. HTTP 409 means stale revision or active work; refetch first.
Voice metadata uses:

~~~json
{"revision":1,"name":"Hero","style":"confident"}
~~~

Edits invalidate old exports.

## Render

~~~bash
curl --fail-with-body \
  -H "Authorization: Bearer $ANIMODE_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"revision":1,"keep_background":true,"background_gain":0.35,"master":true}' \
  http://127.0.0.1:8000/v1/projects/PROJECT_ID/render
~~~

Set accept_source_overlap=true only after reviewing flagged scenes. Missing references, unsafe
tempo and audible truncation stop the job. Inspect private task logs/project status.json,
correct the script and resubmit. Successful speech cache entries survive later-stage failure.

## Worker contract

One model subprocess and at most eight queued/running tasks. A four-hour timeout kills the worker
process group on POSIX; non-POSIX hosts only kill the worker itself. Use Linux/WSL2 service hosting.
Graceful shutdown waits for queued tasks. Restart marks unfinished work interrupted rather than
automatically repeating synthesis. Failed analysis must be resubmitted; completed analysis can
be rendered again. There is no per-stage analysis recovery.

The local runner is not a distributed queue or multi-tenant SaaS platform. Accounts, billing,
quotas, distributed workers, monitoring and retention remain deployment responsibilities.
