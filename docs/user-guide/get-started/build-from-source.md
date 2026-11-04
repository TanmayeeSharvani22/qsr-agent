# Build from Source

By default, `make up` pulls the published `intel/qsr-agent` image. Build it
locally when you change the source or before an image is published.

## Build and Run

```bash
make up REGISTRY=false
```

This builds two images and starts the stack:

| Image | Built from |
| --- | --- |
| `intel/qsr-agent:<TAG>` | Repository root `Dockerfile` (operator UI, agent runtime, skills) |
| `intel/qsr-weather:<TAG>` | `services/weather/` |

The OpenVINO™ Model Server image (`openvino/model_server:2026.2-gpu`) is always
pulled from Docker Hub.

To build without starting containers:

```bash
make build REGISTRY=false
```

## Options

| Variable | Description |
| --- | --- |
| `TAG` | Tag for the built images (default `latest`) |
| `REGISTRY_URL` | Image name prefix (default `intel/`) |
| `HERMES_INSTALL_COMMIT` | Pin the agent-runtime installer to a specific revision for reproducible builds |

```bash
make up REGISTRY=false TAG=dev
```

## Builds Behind a Proxy

Export `http_proxy`, `https_proxy`, and `no_proxy` before building. They are
passed to the image build as build arguments. See
[Configuration](./configuration.md#proxy).

The agent-runtime installer downloads `uv` from GitHub release assets. Some
proxy nodes intercept that host with a certificate the build image doesn't
trust, and the build fails after five attempts with `failed to download pinned
uv ... (curl 60)`. Point the build at a proxy node that passes GitHub through
(for a corporate network, ask which one), for example:

```bash
https_proxy=http://<other-proxy>:<port> http_proxy=$https_proxy make build REGISTRY=false
```

To rebuild from scratch rather than from cached layers:

```bash
docker compose build --no-cache --pull qsr-agent weather
```

## Deploy a Code Change

The operator UI and agent code are part of the image. After you change them,
rebuild and recreate the agent container:

```bash
docker compose build qsr-agent
docker compose up -d --no-deps --force-recreate qsr-agent
```

Changes to `qsr-skills/` and `agent-config/` don't need a rebuild. Run
`make restart` instead.

---

[Back to Get Started](../get-started.md)
