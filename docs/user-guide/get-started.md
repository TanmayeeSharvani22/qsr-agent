# Get Started

This guide takes you from a fresh Intel® edge system to a running QSR Store
Agent.

## Prerequisites

- A Linux system with an Intel® GPU that meets the
  [System Requirements](get-started/system-requirements.md).
- Docker Engine with the Compose plugin, Git, `make`, and Python 3.
- Network access to GitHub, Docker Hub, and Hugging Face. Behind a proxy, see
  [Configuration](get-started/configuration.md#proxy).

## Step 1: Get the Code

```bash
git clone https://github.com/intel-retail/qsr-agent.git
cd qsr-agent
```

## Step 2: Download the Model

```bash
make download-models
```

This downloads the model set by `MODEL_ID` in `.env.example` (default
`OpenVINO/Qwen3-30B-A3B-Instruct-2507-int4-ov`, about 16 GB) into `./models`. The download is skipped if the model is already present.

## Step 3: Start the Agent

```bash
make up
```

`make up` checks Docker, the Intel GPU device, and the model. It then pulls the
agent image and starts three containers:

| Container | Role |
|---|---|
| `ovms` | OpenVINO™ Model Server running the language model on the Intel® GPU |
| `qsr-agent` | Operator UI and agent runtime |
| `weather` | Weather service (simulated by default) |

The first start loads the model onto the GPU and warms it up. This can take a
few minutes. Check progress with:

```bash
make status
```

The agent is ready when `qsr-agent` reports `healthy`.

## Step 4: Open the Operator UI

Open `http://<host>:8600` in a browser, or `http://localhost:8600` on the same
machine.

Try a few questions in **Operator Chat**:

- *What is the current queue count?*
- *What is the current order accuracy rate?*
- *What's the weather at the store right now?*

## Step 5: Trigger an Event

Change the simulated weather. This also sends a weather event to the agent:

```bash
make weather CONDITION=rain TEMP=12
```

The event appears in the **Autonomy Decisions** panel, and the agent evaluates
it. If the
agent proposes a change, such as adding hot drinks to the menu, select
**Approve** or **Reject**. See the [Operator Guide](operator-guide.md) for more.

## Stop the Agent

```bash
make down
```

Settings, decisions, and learned behaviour are kept in Docker volumes and are
restored on the next `make up`.

## Next Steps

- Connect your store services: [Configuration](get-started/configuration.md).
- Understand the system: [How It Works](how-it-works.md).
- Build the images yourself: [Build from Source](get-started/build-from-source.md).
