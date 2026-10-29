# Troubleshooting

## Start-Up

| Symptom | Resolution |
|---|---|
| `No Intel render device found at /dev/dri/render*` | Install the Intel GPU driver and confirm `ls /dev/dri/renderD*` lists a device. |
| `Model missing: .../config.json` | Run `make download-models`, or set `MODEL_ROOT` and `MODEL_ID` to an existing model. |
| `Docker daemon is not available to this user` | Add your user to the `docker` group, then log out and back in. |
| `qsr-agent` stays `starting` for several minutes | The model is loading and warming up on the GPU. Follow progress with `make logs`. |
| `ovms` restarts repeatedly | Check `docker compose logs ovms`. Common causes are insufficient GPU memory and a GPU device the container cannot access. |
| Settings changes have no effect | Edit `.env.example`, not `.env`. `make up` overwrites `.env`. |
| Image pull fails | Check registry access and proxy settings, or build locally with `make up REGISTRY=false`. |

## Store Services

| Symptom | Resolution |
|---|---|
| A service shows as unavailable in **Connected apps** | Confirm the service is running and its URL is reachable from the agent container. Use `host.docker.internal`, not `127.0.0.1`, for services on the same machine. |
| A remote service is unreachable behind a proxy | Add the service host to `QSR_EXTRA_NO_PROXY` in `.env.example`, then run `make up`. |
| An HTTPS service fails after it restarted | The service may have generated a new certificate. Run `make restart`. |
| Changes to `agent-config/` or `qsr-skills/` are ignored | Run `make restart`. |

## Chat and Decisions

| Symptom | Resolution |
|---|---|
| A store question is declined as out of scope | Rephrase it using store terms such as menu, queue, order, table, or kitchen. Confirm the related service is connected. |
| The answer says data is unavailable | The service that owns the data is not reachable. Check **Connected apps**. |
| An answer takes longer than usual | Long conversations are occasionally summarised to fit the model's context. Select **New chat** to start fresh. |
| An event shows **Failed** | Check `make logs`, then resend the event with the same `event_id` to retry it. |
| Approve returns an error | The proposal expired after five minutes or was already decided. |
| The weather event does nothing | Use a valid condition (`clear`, `cloudy`, `fog`, `drizzle`, `rain`, `storm`, `snow`), and don't pass `NO_EVENT=1`. |

## Collect Diagnostics

```bash
make status
make logs
docker compose logs ovms --tail=200
curl -s http://localhost:8600/status?force=1
```
