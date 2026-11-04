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
| Build fails with `failed to download pinned uv ... (curl 60)` | A proxy node intercepts GitHub downloads. See [Builds Behind a Proxy](get-started/build-from-source.md#builds-behind-a-proxy). |

## Store Services

| Symptom | Resolution |
|---|---|
| A service shows as unavailable in **Connected apps** | Confirm the service is running and its URL is reachable from the agent container. Use `host.docker.internal`, not `127.0.0.1`, for services on the same machine. |
| A remote service is unreachable behind a proxy | Add the service host to `QSR_EXTRA_NO_PROXY` in `.env.example`, then run `make up`. |
| An HTTPS service fails after it restarted | The service may have generated a new certificate. Run `make restart`. |
| Changes to `agent-config/` or `qsr-skills/` are ignored | Run `make restart`. |
| A remote service stops answering after it restarted | The agent keeps its MCP session. Run `make restart`. |
| A remote service is reachable again but still shows as unavailable | After repeated failures the agent parks the connection and retries every five minutes. Run `make restart` to reconnect now. If its port accepts connections but MCP requests time out, restart the service on its host. |
| No events arrive from a remote service | On the service host, check its event URL points to `http://<agent-host>:8600/autonomy/events`, its store ID matches the agent's (`qsr-001`), and the agent host bypasses its proxy. |
| Events from one host fail with a clock-skew or "evidence expired" error | That host's clock is behind the agent's. Enable NTP on every host (`timedatectl`), for example with your network's time server. |

## Chat and Decisions

| Symptom | Resolution |
|---|---|
| A store question is declined as out of scope | Rephrase it using store terms such as menu, queue, order, table, or kitchen. Confirm the related service is connected. |
| The answer says data is unavailable | The service that owns the data is not reachable. Check **Connected apps**. |
| An answer takes longer than usual | Long conversations are occasionally summarised to fit the model's context. Select **New chat** to start fresh. |
| Chat stops answering and **New chat** hangs | A very large answer can exhaust the model's context. Run `make restart`; operator memory, decisions and learning are kept. |
| An event shows **Failed** | Check `make logs`, then resend the event with the same `event_id` to retry it. |
| Approve returns an error | The proposal expired after five minutes or was already decided. |
| The weather event does nothing | Use a valid condition (`clear`, `cloudy`, `fog`, `drizzle`, `rain`, `storm`, `snow`), and don't pass `NO_EVENT=1`. |

## Learning

| Symptom | Resolution |
|---|---|
| **Learn now** does not appear | The UI needs 20 responses for the service and 5 for one event type. `make learn ARGS=status` shows the counts; `make learn ARGS=run` needs only the 5. |
| `Nothing to learn` or `no proposed rule is supported by the records` | Collect more varied responses. A rule needs at least two taught records and must not be rejected as often as taught. |
| A learned rule refers to fields or item IDs your services don't have | It was learned from data for different services. Delete `learning/skills/learned-<service>` in the `learning` volume and learn again from your own records. |
| Learned skills are not in the repository's `learning/` folder | They are in the `learning` Docker volume. See [Stored Data](how-it-works.md#stored-data). |

## Collect Diagnostics

```bash
make status
make logs
docker compose logs ovms --tail=200
curl -s http://localhost:8600/status?force=1
```
